"""Synthesis pass: streams a cited markdown answer over the researcher's
sources. Emits one `response` event per delta and a final `sources` event.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from . import prompts as _prompts
from .events import Event, EventBus, EventType
from ..llm_config import LLMConfig

log = logging.getLogger("sift.research")


def _client(cfg: LLMConfig):
    import openai

    return openai.AsyncOpenAI(
        base_url=cfg.host,
        api_key=cfg.api_key or "-",
        timeout=cfg.timeout,
    )


_CITATION_RE = re.compile(r"\[(\d+)\]")
_FENCE_RE = re.compile(r"^\s*```", re.MULTILINE)


def close_dangling_fence(text: str) -> str:
    """Append a closing ``` if ``text`` ends with an unterminated code fence.

    A truncated synthesis can leave an open code block; appending the
    references section into it would render the whole tail as code.
    """
    if len(_FENCE_RE.findall(text)) % 2 == 1:
        sep = "" if text.endswith("\n") else "\n"
        return text + sep + "```\n"
    return text


def cited_indices(text: str | None) -> set[int]:
    """1-based source numbers actually cited as ``[n]`` in ``text``."""
    return {int(n) for n in _CITATION_RE.findall(text or "")}


def format_references(
    sources: list[dict[str, Any]], synthesis: str | None = None
) -> str:
    """Build a '## References' section from a source list.

    When ``synthesis`` is given, list only the sources actually cited as
    ``[n]`` in it, preserving their original 1-based numbers so the inline
    citations keep resolving. If the synthesis contains no ``[n]`` citations
    at all (model didn't cite, or a non-standard format), fall back to
    listing every source rather than dropping the section entirely.
    """
    if not sources:
        return ""
    cited = cited_indices(synthesis) if synthesis is not None else None
    if not cited:  # None (no filtering requested) or empty (no citations found)
        cited = None
    lines = ["\n\n## References\n"]
    any_listed = False
    for i, s in enumerate(sources, start=1):
        if cited is not None and i not in cited:
            continue
        any_listed = True
        title = s.get("title") or s.get("url") or f"Source {i}"
        url = s.get("url") or ""
        lines.append(f"{i}. [{title}]({url})")
    if not any_listed:
        return ""
    return "\n".join(lines)


def _format_context(sources: list[dict[str, Any]]) -> str:
    lines = []
    for i, s in enumerate(sources, start=1):
        title = s.get("title") or s.get("url") or f"source {i}"
        url = s.get("url") or ""
        content = (s.get("content") or "").strip()
        lines.append(f"[{i}] {title} ({url})\n{content}")
    return "\n\n".join(lines)


async def write(
    *,
    query: str,
    history: list[tuple[str, str]] | None,
    system: str | None,
    sources: list[dict[str, Any]],
    mode: str,
    llm_cfg: LLMConfig,
    bus: EventBus,
    client=None,
    existing_doc: str | None = None,
) -> str:
    """Stream a markdown synthesis. Returns the full text, also emitting events.

    When ``existing_doc`` is provided the writer uses the revision prompt,
    returning a full updated document rather than a fresh answer.
    """
    context = _format_context(sources)

    convo: list[dict[str, Any]]
    if existing_doc is not None:
        # Revision mode: no chat history — the existing document already encodes
        # prior turns, and history alongside it causes the model to treat the
        # request as a chatty follow-up rather than a document merge.
        sys_prompt = _prompts.get_document_revision_prompt(
            context, system or "", mode, existing_doc, query
        )
        convo = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": "Produce the merged document now."},
        ]
    else:
        sys_prompt = _prompts.get_writer_prompt(context, system or "", mode)
        convo = [{"role": "system", "content": sys_prompt}]
        if history:
            for role, text in history[-10:]:
                convo.append({"role": "user" if role == "human" else "assistant", "content": text})
        convo.append({"role": "user", "content": query})

    if client is None:
        client = _client(llm_cfg)

    accumulated = ""
    finish_reason = None
    try:
        stream = await client.chat.completions.create(
            model=llm_cfg.model, messages=convo, stream=True
        )
        async for chunk in stream:
            try:
                choice = chunk.choices[0]
                delta = choice.delta
                piece = getattr(delta, "content", None) or ""
                finish_reason = getattr(choice, "finish_reason", None) or finish_reason
            except (AttributeError, IndexError):
                piece = ""
            if piece:
                accumulated += piece
                bus.emit(Event(EventType.RESPONSE, {"delta": piece}))
        if finish_reason == "length":
            log.warning("writer synthesis truncated (finish_reason=length)")
            bus.emit(Event(
                EventType.ERROR,
                {"stage": "writer", "error": "synthesis truncated by token limit"},
            ))
    except Exception as exc:  # noqa: BLE001
        from ..llm_config import is_fatal_llm_error

        log.exception("writer streaming failed; falling back to non-stream")
        bus.emit(Event(EventType.ERROR, {"stage": "writer_stream", "error": str(exc)}))
        if is_fatal_llm_error(exc):
            raise
        try:
            resp = await client.chat.completions.create(model=llm_cfg.model, messages=convo)
            accumulated = resp.choices[0].message.content or ""
            bus.emit(Event(EventType.RESPONSE, {"delta": accumulated}))
        except Exception as exc2:  # noqa: BLE001
            log.exception("writer non-stream also failed")
            bus.emit(Event(EventType.ERROR, {"stage": "writer", "error": str(exc2)}))
            if is_fatal_llm_error(exc2):
                raise

    bus.emit(Event(EventType.SOURCES, {"sources": sources}))
    return accumulated
