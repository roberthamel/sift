"""Researcher loop — iterates an OpenAI tool-call chat until `done`.

The loop maintains an OpenAI-shaped message history. Each iteration:
  1. Prepends the mode-specific researcher system prompt.
  2. Calls the LLM with the action tool schemas.
  3. Accumulates tool calls from the (optionally streaming) response.
  4. Appends the assistant tool-call message + each tool's result message.
  5. Terminates on `done`, zero tool calls, or iter cap.

Returns a `ResearcherResult` with the action log, deduped sources, and a
usage tally.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from . import actions as _actions
from . import prompts as _prompts
from .actions import ActionContext, ActionOutput
from .events import Event, EventBus, EventType
from .embed_config import EmbedConfig
from ..llm_config import LLMConfig

log = logging.getLogger("sift.research")

MAX_ITER = {"speed": 2, "balanced": 6, "quality": 25}


@dataclass
class ResearcherResult:
    actions: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=lambda: {"prompt": 0, "completion": 0, "total": 0})


def _build_history(history: list[tuple[str, str]] | None, query: str) -> list[dict[str, Any]]:
    """Build the initial user message embedding chat history (Vane-style)."""
    convo_lines = []
    if history:
        for role, text in history[-10:]:
            convo_lines.append(f"{role.capitalize()}: {text}")
    convo = "\n".join(convo_lines)
    user_msg = (
        f"<conversation>\n{convo}\nUser: {query}\n</conversation>"
        if convo
        else f"User: {query}"
    )
    return [{"role": "user", "content": user_msg}]


def _client(cfg: LLMConfig):
    import openai

    return openai.AsyncOpenAI(
        base_url=cfg.host,
        api_key=cfg.api_key or "-",
        timeout=cfg.timeout,
    )


async def _call_once(
    client, *, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
):
    """Make one chat call returning (tool_calls, usage_delta).

    Streaming-aware: if the response supports streaming we accumulate; the
    fake clients used in tests just return a normal completion.
    """
    resp = await client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
        tool_choice="auto",
    )
    choice = resp.choices[0]
    msg = choice.message
    tool_calls = []
    for tc in (getattr(msg, "tool_calls", None) or []):
        fn = getattr(tc, "function", None) or {}
        if isinstance(fn, dict):
            name = fn.get("name", "")
            args = fn.get("arguments", "{}")
        else:
            name = getattr(fn, "name", "") or ""
            args = getattr(fn, "arguments", "{}")
        tool_calls.append(
            {
                "id": getattr(tc, "id", None) or "",
                "type": "function",
                "function": {"name": name, "arguments": args},
            }
        )
    usage = getattr(resp, "usage", None)
    udelta = {
        "prompt": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion": int(getattr(usage, "completion_tokens", 0) or 0),
        "total": int(getattr(usage, "total_tokens", 0) or 0),
    } if usage else {"prompt": 0, "completion": 0, "total": 0}
    return tool_calls, udelta


async def run(
    *,
    query: str,
    history: list[tuple[str, str]] | None,
    system: str | None,
    mode: str,
    llm_cfg: LLMConfig,
    embed_cfg: EmbedConfig,
    bus: EventBus,
    runner_kwargs: dict[str, Any] | None = None,
    client=None,
) -> ResearcherResult:
    """Drive the researcher loop. `client` allows test injection."""
    mode = mode if mode in MAX_ITER else "balanced"
    max_iter = MAX_ITER[mode]
    ctx = ActionContext(
        mode=mode,
        llm_cfg=llm_cfg,
        embed_cfg=embed_cfg,
        bus=bus,
        query=query,
        runner_kwargs=runner_kwargs or {},
    )

    if client is None:
        client = _client(llm_cfg)

    bus.emit(Event(EventType.INIT, {"query": query, "mode": mode, "max_iter": max_iter}))

    messages: list[dict[str, Any]] = _build_history(history, query)
    tools = _actions.tool_schemas(mode)
    action_desc = _actions.action_descriptions(mode)

    result = ResearcherResult()
    finished = False

    for i in range(max_iter):
        sys_prompt = _prompts.get_researcher_prompt(action_desc, mode, i, max_iter)
        if system:
            sys_prompt = sys_prompt + "\n\n### User instructions\n" + system
        call_messages = [{"role": "system", "content": sys_prompt}, *messages]

        try:
            tool_calls, udelta = await _call_once(
                client, model=llm_cfg.model, messages=call_messages, tools=tools
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("loop iteration %d failed", i)
            bus.emit(Event(EventType.ERROR, {"stage": "loop", "iter": i, "error": str(exc)}))
            break

        for k in result.usage:
            result.usage[k] += udelta.get(k, 0)

        if not tool_calls:
            break

        # Append assistant tool-call message before tool results (OpenAI schema).
        messages.append({"role": "assistant", "content": "", "tool_calls": tool_calls})

        outs = await _actions.execute_all(tool_calls, ctx)

        for tc, out in zip(tool_calls, outs):
            tool_msg_content = json.dumps(out.data, ensure_ascii=False, default=str)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id") or "",
                    "name": tc.get("function", {}).get("name", ""),
                    "content": tool_msg_content,
                }
            )
            result.actions.append(
                {
                    "name": tc.get("function", {}).get("name", ""),
                    "args": _safe_args(tc),
                    "type": out.type,
                    "data": out.data,
                }
            )

        if any(tc.get("function", {}).get("name") == "done" for tc in tool_calls):
            finished = True
            break

    # Aggregate sources from every search_results action, dedupe by URL.
    by_url: dict[str, dict[str, Any]] = {}
    for a in result.actions:
        if a["type"] != "search_results":
            continue
        for r in a["data"].get("results", []) or []:
            url = r.get("url") or ""
            if not url:
                continue
            if url in by_url:
                existing = by_url[url]
                # Concatenate content
                if r.get("content") and r["content"] not in (existing.get("content") or ""):
                    existing["content"] = (existing.get("content") or "") + "\n\n" + r["content"]
                # Keep the max similarity
                if r.get("similarity", 0) > existing.get("similarity", 0):
                    existing["similarity"] = r["similarity"]
            else:
                by_url[url] = dict(r)
    result.sources = list(by_url.values())
    result.sources.sort(key=lambda r: r.get("similarity", 0.0), reverse=True)

    bus.emit(Event(EventType.SOURCES, {"sources": result.sources}))
    bus.emit(Event(EventType.DONE, {"finished": finished, "iters": len(result.actions)}))
    return result


def _safe_args(tc: dict[str, Any]) -> dict[str, Any]:
    raw = tc.get("function", {}).get("arguments", {})
    if isinstance(raw, str):
        try:
            return json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
    return raw or {}
