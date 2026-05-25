"""Normalize stdin JSON for `sift synthesize` and dispatch to the LLM.

Two stdin shapes are accepted:
- Search JSON: `{"query": ..., "results": [{title,url,content,engine,...}]}`
  Each result may carry `markdown` (from `--fetch`) or `processed_markdown`
  (from `--prompt`). Content precedence: processed_markdown > markdown > content.
  When only `content` (snippet) is present the payload is flagged
  `snippet_only: true` so the model knows to weigh accordingly.
- Fetch JSON: `{"results": [{url, markdown, ...}], "fetch_errors": [...]}`.

The function returns the source list the LLM will see plus a metadata dict
that's emitted alongside the summary.
"""
from __future__ import annotations

import asyncio
from typing import Any

from . import llm
from .llm_config import LLMConfig


def build_synthesize_payload(stdin_doc: Any, query: str) -> dict[str, Any]:
    """Return a normalized payload: {query, sources, snippet_only, source_count, errors}."""
    sources: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    snippet_only = True  # flip to False once any source has fetched content

    if isinstance(stdin_doc, dict):
        results = stdin_doc.get("results") or []
        for r in results:
            if not isinstance(r, dict):
                continue
            entry: dict[str, Any] = {
                "title": r.get("title") or "",
                "url": r.get("url") or "",
            }
            processed = r.get("processed_markdown")
            md = r.get("markdown")
            snippet = r.get("content") or r.get("snippet")
            if processed:
                entry["content"] = processed
                snippet_only = False
            elif md:
                entry["content"] = md
                snippet_only = False
            elif snippet:
                entry["snippet"] = snippet
            sources.append(entry)
        for e in stdin_doc.get("fetch_errors") or []:
            if isinstance(e, dict):
                errors.append({"url": e.get("url"), "error": e.get("message") or e.get("error_type")})
    return {
        "query": query,
        "sources": sources,
        "snippet_only": snippet_only if sources else False,
        "source_count": len(sources),
        "errors": errors,
    }


def synthesize(payload: dict[str, Any], cfg: LLMConfig) -> tuple[dict[str, Any], str | None]:
    """Run the LLM synthesis pass. Always returns a result dict; LLM errors
    are surfaced via `llm_error` (caller exits 0)."""
    summary, err = asyncio.run(
        llm.synthesize_search_results(payload["query"], payload["sources"], cfg)
    )
    out: dict[str, Any] = {
        "query": payload["query"],
        "summary": summary,
        "source_count": payload["source_count"],
        "snippet_only": payload["snippet_only"],
        "model": cfg.model,
    }
    if payload["errors"]:
        out["source_errors"] = payload["errors"]
    if err:
        out["llm_error"] = err
    return out, err
