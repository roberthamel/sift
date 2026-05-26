"""Synthesis pass: streams a cited markdown answer over the researcher's
sources. Emits one `response` event per delta and a final `sources` event.
"""
from __future__ import annotations

import json
import logging
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


def format_references(sources: list[dict[str, Any]]) -> str:
    """Build a '## References' section from a source list."""
    if not sources:
        return ""
    lines = ["\n\n## References\n"]
    for i, s in enumerate(sources, start=1):
        title = s.get("title") or s.get("url") or f"Source {i}"
        url = s.get("url") or ""
        lines.append(f"{i}. [{title}]({url})")
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
) -> str:
    """Stream a markdown synthesis. Returns the full text, also emitting events."""
    context = _format_context(sources)
    sys_prompt = _prompts.get_writer_prompt(context, system or "", mode)

    convo: list[dict[str, Any]] = [{"role": "system", "content": sys_prompt}]
    if history:
        for role, text in history[-10:]:
            convo.append({"role": "user" if role == "human" else "assistant", "content": text})
    convo.append({"role": "user", "content": query})

    if client is None:
        client = _client(llm_cfg)

    accumulated = ""
    try:
        stream = await client.chat.completions.create(
            model=llm_cfg.model, messages=convo, stream=True
        )
        async for chunk in stream:
            try:
                delta = chunk.choices[0].delta
                piece = getattr(delta, "content", None) or ""
            except (AttributeError, IndexError):
                piece = ""
            if piece:
                accumulated += piece
                bus.emit(Event(EventType.RESPONSE, {"delta": piece}))
    except Exception as exc:  # noqa: BLE001
        log.exception("writer streaming failed; falling back to non-stream")
        bus.emit(Event(EventType.ERROR, {"stage": "writer_stream", "error": str(exc)}))
        try:
            resp = await client.chat.completions.create(model=llm_cfg.model, messages=convo)
            accumulated = resp.choices[0].message.content or ""
            bus.emit(Event(EventType.RESPONSE, {"delta": accumulated}))
        except Exception as exc2:  # noqa: BLE001
            log.exception("writer non-stream also failed")
            bus.emit(Event(EventType.ERROR, {"stage": "writer", "error": str(exc2)}))

    bus.emit(Event(EventType.SOURCES, {"sources": sources}))
    return accumulated
