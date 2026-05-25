"""Resolve URL input for `fetch` from positional args and/or stdin.

Three stdin shapes are supported:
- Search-JSON from `sift search` — a top-level object with `results[]`.
- Raw URL list — one URL per line, blank lines and `#`-prefixed comments ignored.
- Empty / TTY — produces no URLs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, TextIO


@dataclass
class ResolvedInput:
    urls: list[str]
    # When stdin was search-JSON, the original document is preserved so the
    # caller can pass through `title`, `engine`, `score`, etc. into the
    # fetch result.
    search_json: dict[str, Any] | None = None


def _parse_url_list(text: str) -> list[str]:
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def _looks_like_json(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("{") or stripped.startswith("[")


def _extract_search_urls(doc: Any) -> list[str] | None:
    """Return URLs if `doc` looks like sift search output, else None."""
    if not isinstance(doc, dict):
        return None
    results = doc.get("results")
    if not isinstance(results, list):
        return None
    urls: list[str] = []
    for r in results:
        if isinstance(r, dict):
            u = r.get("url")
            if isinstance(u, str) and u:
                urls.append(u)
    return urls


def resolve(args: list[str], stdin: TextIO, stdin_is_tty: bool) -> ResolvedInput:
    """Resolve URL input for the `fetch` command.

    Precedence:
    - Positional args win and stdin is ignored.
    - Otherwise, stdin is read; if it parses as a search-JSON object with a
      `results[]` array, URLs are extracted and the full document is returned
      for passthrough. Otherwise the stdin text is treated as a URL list.
    - If stdin is a TTY (no piped input), no URLs are produced.
    """
    if args:
        return ResolvedInput(urls=list(args))

    if stdin_is_tty:
        return ResolvedInput(urls=[])

    text = stdin.read()
    if not text.strip():
        return ResolvedInput(urls=[])

    if _looks_like_json(text):
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            doc = None
        if doc is not None:
            urls = _extract_search_urls(doc)
            if urls is not None:
                return ResolvedInput(urls=urls, search_json=doc)

    return ResolvedInput(urls=_parse_url_list(text))
