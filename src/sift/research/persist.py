"""Automatic persistence for research documents under .ai/research/<scope>/."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..llm_config import LLMConfig

log = logging.getLogger("sift.research")
_MAX_SLUG_LEN = 60


def _slugify(s: str) -> str:
    """Convert an arbitrary string to a safe kebab-case slug.

    Strips path-traversal sequences and non-alphanumeric chars, lowercases,
    collapses runs of separators to a single hyphen, and caps the length.
    """
    s = s.replace("..", "").replace("/", "-").replace("\\", "-")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s[:_MAX_SLUG_LEN].rstrip("-") or "research"


def _fallback_slug(query: str) -> tuple[str, str]:
    words = query.split()
    scope = _slugify(" ".join(words[:3])) or "research"
    slug = _slugify(" ".join(words[:8])) or "research"
    return scope, slug


async def pick_location(
    query: str,
    llm_cfg: "LLMConfig",
    client=None,
) -> tuple[str, str]:
    """Ask the LLM to choose a (scope, slug) pair for the research document.

    Returns (scope, slug) where both are safe kebab-case strings. Falls back
    to a deterministic word-based slug if the LLM call fails.
    """
    import openai

    if client is None:
        client = openai.AsyncOpenAI(
            base_url=llm_cfg.host,
            api_key=llm_cfg.api_key or "-",
            timeout=llm_cfg.timeout,
        )

    prompt = (
        "Given the research question below, choose:\n"
        "  scope: a short topical folder name (1-3 words, kebab-case)\n"
        "  filename: a descriptive file slug (1-5 words, kebab-case, no extension)\n"
        'Return ONLY raw JSON: {"scope": "...", "filename": "..."}\n\n'
        f"Question: {query}"
    )

    try:
        resp = await client.chat.completions.create(
            model=llm_cfg.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=64,
        )
        raw = (resp.choices[0].message.content or "").strip()
        m = re.search(r"\{[^}]+\}", raw, re.DOTALL)
        if m:
            data = json.loads(m.group())
            scope = _slugify(str(data.get("scope", "")))
            slug = _slugify(str(data.get("filename", "")))
            if scope and slug:
                return scope, slug
    except Exception:  # noqa: BLE001
        log.debug("pick_location LLM call failed, using word-based fallback", exc_info=True)

    return _fallback_slug(query)


def resolve_path(
    scope: str,
    slug: str,
    base: Path = Path(".ai/research"),
    continuing: Path | None = None,
) -> Path:
    """Build the save path, appending a numeric suffix if the file already exists.

    If the computed path is the ``continuing`` file (i.e. we are editing an
    existing document in place), it is returned without a suffix even if it
    exists on disk.
    """
    target = base / scope / f"{slug}.md"
    if continuing is not None and target.resolve() == continuing.resolve():
        return target
    if not target.exists():
        return target
    for n in range(2, 1000):
        candidate = base / scope / f"{slug}-{n}.md"
        if continuing is not None and candidate.resolve() == continuing.resolve():
            return candidate
        if not candidate.exists():
            return candidate
    return base / scope / f"{slug}-1000.md"


def save(path: Path, content: str) -> None:
    """Write content to path, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
