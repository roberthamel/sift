"""Action registry — plan / search / scrape_url / done.

Each action is callable via OpenAI tool-calling. The registry exposes
`tool_schemas(mode)` for the LLM client and `execute_all(tool_calls, ctx)`
to run a batch of tool calls returned by a model.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

from . import embeddings as _embeddings
from . import prompts as _prompts
from . import utils as _utils
from .embed_config import EmbedConfig
from .events import Event, EventBus, EventType
from ..llm_config import LLMConfig

log = logging.getLogger("sift.research")


@dataclass
class ActionContext:
    mode: str  # speed | balanced | quality
    llm_cfg: LLMConfig
    embed_cfg: EmbedConfig
    bus: EventBus
    query: str  # the user's query — used as the embedding anchor for filter/dedupe
    runner_kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionOutput:
    """One executed tool-call result, appended to the assistant's tool history."""

    type: str  # "plan_reasoning" | "search_results" | "done"
    data: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# plan action
# ---------------------------------------------------------------------------

_PLAN_SCHEMA = {
    "type": "function",
    "function": {
        "name": "plan",
        "description": (
            "Use this FIRST on every turn to state your plan in natural "
            "language before any other action. Keep it short, action-focused, "
            "and tailored to the current query."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": (
                        "A concise natural-language plan in one short "
                        "paragraph. Open with a short intent phrase."
                    ),
                }
            },
            "required": ["plan"],
        },
    },
}


async def _action_plan(args: dict[str, Any], ctx: ActionContext) -> ActionOutput:
    plan_text = str(args.get("plan", "")).strip()
    ctx.bus.emit(Event(EventType.PLAN, {"plan": plan_text}))
    return ActionOutput(type="plan_reasoning", data={"plan": plan_text})


# ---------------------------------------------------------------------------
# search action
# ---------------------------------------------------------------------------

_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search",
        "description": (
            "Run web searches via SearXNG (general category). Provide 1-3 "
            "targeted queries. Returns ranked, deduped result snippets."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 3,
                    "description": "1-3 distinct, focused queries.",
                }
            },
            "required": ["queries"],
        },
    },
}


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except Exception:
        return ""


async def _run_searxng(query: str, ctx: ActionContext) -> list[dict[str, Any]]:
    """Run sift's in-process SearXNG search and return raw result dicts."""
    from .. import runner as _runner

    kwargs = dict(ctx.runner_kwargs)
    kwargs.setdefault("engine_names", None)
    kwargs.setdefault("category", "general")
    kwargs.setdefault("page", 1)
    kwargs.setdefault("lang", "all")
    kwargs.setdefault("safesearch", 0)
    kwargs.setdefault("timeout", None)
    allow = kwargs.pop("allow", None)
    block = kwargs.pop("block", None)

    def _do() -> dict:
        result = _runner.run_search(query=query, **kwargs)
        if allow or block:
            result["results"] = _runner.apply_domain_filters(
                result.get("results", []) or [], allow, block
            )
        return result

    out = await asyncio.to_thread(_do)
    return list(out.get("results", []) or [])


async def _embed_and_rank(
    query: str,
    raw_results: list[dict[str, Any]],
    ctx: ActionContext,
) -> list[dict[str, Any]]:
    """Embed query + each snippet, score, filter > 0.5, dedupe > 0.75, top-20."""
    filtered: list[tuple[dict[str, Any], str]] = []
    for r in raw_results:
        content = r.get("content") or r.get("snippet") or r.get("title") or ""
        if content.strip():
            filtered.append((r, content))
    if not filtered:
        return []
    snippets = [c for _, c in filtered]

    vectors = await _embeddings.embed_text([query, *snippets], ctx.embed_cfg)
    q_vec = vectors[0]
    s_vecs = vectors[1:]

    scored: list[dict[str, Any]] = []
    for (r, content), vec in zip(filtered, s_vecs):
        sim = _utils.cosine_similarity(q_vec, vec)
        if sim <= 0.5:
            continue
        scored.append(
            {
                "url": r.get("url"),
                "title": r.get("title"),
                "content": content,
                "similarity": sim,
                "_embedding": vec,
            }
        )

    scored.sort(key=lambda x: x["similarity"], reverse=True)

    unique: list[dict[str, Any]] = []
    for cand in scored:
        is_dup = False
        for kept in unique:
            if (
                cand["_embedding"]
                and kept["_embedding"]
                and _utils.cosine_similarity(cand["_embedding"], kept["_embedding"]) > 0.75
            ):
                is_dup = True
                break
        if not is_dup:
            unique.append(cand)
        if len(unique) >= 20:
            break

    for item in unique:
        item.pop("_embedding", None)
    return unique


async def _quality_search(
    queries: list[str], ctx: ActionContext
) -> list[dict[str, Any]]:
    """Quality-mode: gather, LLM-pick ≤3, scrape, chunk, extract facts."""
    import openai

    # Gather raw results from each query.
    all_raw: list[dict[str, Any]] = []
    for q in queries:
        try:
            all_raw.extend(await _run_searxng(q, ctx))
        except Exception as exc:  # noqa: BLE001
            log.warning("search failed for %r: %s", q, exc)
            ctx.bus.emit(Event(EventType.ERROR, {"stage": "search", "query": q, "error": str(exc)}))

    # Compact raw list for the picker.
    candidates = []
    for r in all_raw:
        candidates.append(
            {
                "url": r.get("url"),
                "title": r.get("title"),
                "content": (r.get("content") or r.get("snippet") or "")[:600],
            }
        )

    if not candidates:
        return []

    client = openai.AsyncOpenAI(
        base_url=ctx.llm_cfg.host,
        api_key=ctx.llm_cfg.api_key or "-",
        timeout=ctx.llm_cfg.timeout,
    )

    picker_user = (
        f"<queries>{', '.join(queries)}</queries>\n<search_results>"
        + "\n".join(
            f"<result indice={i}>{json.dumps(c, ensure_ascii=False)}</result>"
            for i, c in enumerate(candidates)
        )
        + "</search_results>"
    )

    try:
        resp = await client.chat.completions.create(
            model=ctx.llm_cfg.model,
            messages=[
                {"role": "system", "content": _prompts.PICKER_PROMPT},
                {"role": "user", "content": picker_user},
            ],
            response_format={"type": "json_object"},
        )
        picked = json.loads(resp.choices[0].message.content or "{}").get(
            "picked_indices", []
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("picker failed: %s", exc)
        ctx.bus.emit(Event(EventType.ERROR, {"stage": "picker", "error": str(exc)}))
        picked = list(range(min(3, len(candidates))))

    picked = [int(i) for i in picked][:3]
    chosen = [candidates[i] for i in picked if 0 <= i < len(candidates)]
    if not chosen:
        return []

    urls = [c["url"] for c in chosen if c.get("url")]
    ctx.bus.emit(Event(EventType.READING, {"urls": urls}))

    from .. import fetcher

    opts = fetcher.FetchOptions(filter="fit", timeout=30.0, concurrency=3)
    outcome = await asyncio.to_thread(fetcher.fetch_urls, urls, opts)

    by_url = {r.url: r for r in outcome.results}
    extracted: list[dict[str, Any]] = []
    for c in chosen:
        url = c.get("url")
        fetched = by_url.get(url) if url else None
        if not fetched or not fetched.markdown:
            ctx.bus.emit(
                Event(EventType.ERROR, {"stage": "scrape", "url": url, "error": "no content"})
            )
            continue
        chunks = _utils.split_text(fetched.markdown, size=4000, overlap=500)
        accumulated_parts: list[str] = []
        for chunk in chunks:
            try:
                resp = await client.chat.completions.create(
                    model=ctx.llm_cfg.model,
                    messages=[
                        {"role": "system", "content": _prompts.EXTRACTOR_PROMPT},
                        {
                            "role": "user",
                            "content": (
                                f"<queries>{', '.join(queries)}</queries>\n"
                                f"<scraped_data>{chunk}</scraped_data>"
                            ),
                        },
                    ],
                    response_format={"type": "json_object"},
                )
                facts = json.loads(resp.choices[0].message.content or "{}").get(
                    "extracted_facts", ""
                )
                if facts:
                    accumulated_parts.append(str(facts))
            except Exception as exc:  # noqa: BLE001
                log.warning("extractor failed on %s: %s", url, exc)
                ctx.bus.emit(
                    Event(EventType.ERROR, {"stage": "extract", "url": url, "error": str(exc)})
                )
        content = "\n".join(accumulated_parts) if accumulated_parts else (fetched.markdown or "")
        item = {
            "url": url,
            "title": c.get("title"),
            "content": content,
            "similarity": 1.0,
        }
        extracted.append(item)
        ctx.bus.emit(Event(EventType.EXTRACTED, {"url": url, "facts": content[:200]}))
    return extracted


async def _action_search(args: dict[str, Any], ctx: ActionContext) -> ActionOutput:
    queries = [str(q).strip() for q in args.get("queries", []) if str(q).strip()]
    queries = queries[:3]
    if not queries:
        return ActionOutput(type="search_results", data={"results": []})
    ctx.bus.emit(Event(EventType.SEARCH, {"queries": queries}))

    if ctx.mode == "quality":
        results = await _quality_search(queries, ctx)
    else:
        # speed / balanced: per-query embed-rank, then merge and re-dedupe.
        combined: list[dict[str, Any]] = []
        for q in queries:
            try:
                raw = await _run_searxng(q, ctx)
            except Exception as exc:  # noqa: BLE001
                log.warning("search failed for %r: %s", q, exc)
                ctx.bus.emit(
                    Event(EventType.ERROR, {"stage": "search", "query": q, "error": str(exc)})
                )
                continue
            try:
                ranked = await _embed_and_rank(ctx.query, raw, ctx)
            except Exception as exc:  # noqa: BLE001
                log.warning("embedding failed for %r: %s", q, exc)
                ctx.bus.emit(
                    Event(EventType.ERROR, {"stage": "embed", "query": q, "error": str(exc)})
                )
                # Fallback: keep raw snippets with similarity=1.0 so the loop progresses.
                ranked = [
                    {
                        "url": r.get("url"),
                        "title": r.get("title"),
                        "content": r.get("content") or r.get("snippet") or "",
                        "similarity": 1.0,
                    }
                    for r in raw[:20]
                ]
            combined.extend(ranked)
        # Dedupe combined by URL, keep first occurrence (already sorted per-query).
        seen: set[str] = set()
        results: list[dict[str, Any]] = []
        for r in sorted(combined, key=lambda x: x.get("similarity", 0.0), reverse=True):
            url = r.get("url") or ""
            if url in seen:
                continue
            seen.add(url)
            results.append(r)
            if len(results) >= 20:
                break

    ctx.bus.emit(Event(EventType.SEARCH_RESULTS, {"count": len(results), "queries": queries}))
    return ActionOutput(type="search_results", data={"results": results})


# ---------------------------------------------------------------------------
# scrape_url action
# ---------------------------------------------------------------------------

_SCRAPE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "scrape_url",
        "description": (
            "Scrape and extract content from up to 3 URLs the user has "
            "specifically asked about. Do not call this unprompted."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 3,
                    "description": "1-3 URLs to scrape.",
                }
            },
            "required": ["urls"],
        },
    },
}


async def _action_scrape_url(args: dict[str, Any], ctx: ActionContext) -> ActionOutput:
    urls = [str(u).strip() for u in args.get("urls", []) if str(u).strip()][:3]
    if not urls:
        return ActionOutput(type="search_results", data={"results": []})
    ctx.bus.emit(Event(EventType.READING, {"urls": urls}))

    from .. import fetcher

    opts = fetcher.FetchOptions(filter="fit", timeout=30.0, concurrency=3)
    outcome = await asyncio.to_thread(fetcher.fetch_urls, urls, opts)

    results: list[dict[str, Any]] = []
    for r in outcome.results:
        results.append(
            {
                "url": r.url,
                "title": _host(r.url),
                "content": r.markdown or "",
                "similarity": 1.0,
            }
        )
        ctx.bus.emit(Event(EventType.EXTRACTED, {"url": r.url, "bytes": len(r.markdown or "")}))
    for e in outcome.errors:
        ctx.bus.emit(Event(EventType.ERROR, {"stage": "scrape", "url": e.url, "error": e.message}))
    return ActionOutput(type="search_results", data={"results": results})


# ---------------------------------------------------------------------------
# done action
# ---------------------------------------------------------------------------

_DONE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "done",
        "description": (
            "Call this when you have gathered enough information to answer "
            "and want to terminate the research loop."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}


async def _action_done(args: dict[str, Any], ctx: ActionContext) -> ActionOutput:
    return ActionOutput(type="done", data={})


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

ActionFn = Callable[[dict[str, Any], ActionContext], Awaitable[ActionOutput]]

_REGISTRY: dict[str, tuple[ActionFn, dict[str, Any]]] = {
    "plan": (_action_plan, _PLAN_SCHEMA),
    "search": (_action_search, _SEARCH_SCHEMA),
    "scrape_url": (_action_scrape_url, _SCRAPE_SCHEMA),
    "done": (_action_done, _DONE_SCHEMA),
}


def tool_schemas(mode: str) -> list[dict[str, Any]]:
    """OpenAI `tools=[...]` schema list for the given mode.

    In `speed` mode, `plan` is omitted (mirroring Vane's `enabled: mode !== 'speed'`).
    """
    schemas = []
    for name, (_fn, schema) in _REGISTRY.items():
        if name == "plan" and mode == "speed":
            continue
        schemas.append(schema)
    return schemas


def action_descriptions(mode: str) -> str:
    """Build a textual description of available tools for the system prompt."""
    parts = []
    for s in tool_schemas(mode):
        fn = s["function"]
        parts.append(f"- `{fn['name']}`: {fn['description']}")
    return "\n".join(parts)


async def execute_all(
    tool_calls: list[dict[str, Any]], ctx: ActionContext
) -> list[ActionOutput]:
    """Execute a list of OpenAI-shaped tool calls and return their outputs.

    Each `tool_call` is a dict with `id`, `function.name`, and
    `function.arguments` (JSON string or dict).
    """
    outs: list[ActionOutput] = []
    for tc in tool_calls:
        fn = tc.get("function", {}) if isinstance(tc, dict) else {}
        name = fn.get("name", "")
        raw_args = fn.get("arguments", {})
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args or "{}")
            except json.JSONDecodeError:
                args = {}
        else:
            args = raw_args or {}
        entry = _REGISTRY.get(name)
        if not entry:
            outs.append(ActionOutput(type="error", data={"name": name, "error": "unknown action"}))
            continue
        fn_impl, _schema = entry
        try:
            out = await fn_impl(args, ctx)
        except Exception as exc:  # noqa: BLE001
            log.exception("action %s failed", name)
            ctx.bus.emit(Event(EventType.ERROR, {"stage": "action", "name": name, "error": str(exc)}))
            out = ActionOutput(type="error", data={"name": name, "error": str(exc)})
        outs.append(out)
    return outs
