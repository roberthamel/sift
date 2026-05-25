"""Convert a SearXNG `ResultContainer` to a stable JSON-friendly dict."""
from __future__ import annotations

from typing import Any


def _result_dict(r: Any) -> dict[str, Any]:
    def g(name: str, default: Any = "") -> Any:
        if hasattr(r, name):
            v = getattr(r, name)
            return v if v is not None else default
        if isinstance(r, dict):
            v = r.get(name, default)
            return v if v is not None else default
        return default

    return {
        "title": str(g("title", "")),
        "url": str(g("url", "")),
        "content": str(g("content", "")),
        "engine": str(g("engine", "")),
        "score": float(g("score", 0.0) or 0.0),
        "category": str(g("category", "general")),
    }


def _answer_dict(a: Any) -> dict[str, Any]:
    # Best effort across answer subclasses.
    if hasattr(a, "answer"):
        return {"type": "answer", "answer": getattr(a, "answer", ""), "url": getattr(a, "url", "") or ""}
    return {"type": type(a).__name__, "repr": str(a)}


def _infobox_dict(b: Any) -> dict[str, Any]:
    if isinstance(b, dict):
        return dict(b)
    out: dict[str, Any] = {}
    for k in ("infobox", "id", "content", "img_src", "urls", "attributes", "engine"):
        if hasattr(b, k):
            out[k] = getattr(b, k)
    return out


def to_dict(container, *, query: str, engines_used: list[str], elapsed: float) -> dict:
    results = [_result_dict(r) for r in container.main_results_map.values()]
    answers = [_answer_dict(a) for a in container.answers]
    infoboxes = [_infobox_dict(b) for b in container.infoboxes]
    suggestions = sorted(container.suggestions)
    corrections = sorted(container.corrections)
    unresponsive = [
        {"engine": u.engine, "error_type": u.error_type}
        for u in container.unresponsive_engines
    ]
    return {
        "query": query,
        "engines_used": list(engines_used),
        "results": results,
        "answers": answers,
        "infoboxes": infoboxes,
        "suggestions": suggestions,
        "corrections": corrections,
        "unresponsive_engines": unresponsive,
        "number_of_results": len(results),
        "elapsed_seconds": round(elapsed, 4),
    }


def fetched_to_dict(outcome, *, search_json: dict | None = None) -> dict:
    """Serialize a fetcher.FetchOutcome to the JSON output shape.

    When `search_json` is provided (caller piped `search` output into `fetch`),
    each fetched URL is merged with the matching result entry so the original
    `title`, `engine`, `score`, `category`, `content` flow through alongside
    the new `markdown` and `filter` fields.
    """
    by_url = {}
    if isinstance(search_json, dict):
        for r in search_json.get("results", []) or []:
            if isinstance(r, dict) and isinstance(r.get("url"), str):
                by_url[r["url"]] = r

    results = []
    for fr in outcome.results:
        merged = dict(by_url.get(fr.url, {}))
        merged["url"] = fr.url
        merged["markdown"] = fr.markdown
        merged["filter"] = fr.filter
        if fr.processed_markdown is not None:
            merged["processed_markdown"] = fr.processed_markdown
        if fr.llm_error:
            merged["llm_error"] = fr.llm_error
        results.append(merged)

    errors = [
        {"url": e.url, "error_type": e.error_type, "message": e.message}
        for e in outcome.errors
    ]
    return {
        "results": results,
        "fetch_errors": errors,
        "elapsed_seconds": round(outcome.elapsed_seconds, 4),
    }


def embed_fetch_into_search(search_dict: dict, outcome) -> dict:
    """Mutate `search_dict` by adding `markdown`/`filter` to fetched results
    and a top-level `fetch_errors[]`. Unfetched results get `markdown: null`.
    """
    fetched_by_url = {fr.url: fr for fr in outcome.results}
    for r in search_dict.get("results", []) or []:
        if not isinstance(r, dict):
            continue
        url = r.get("url")
        if isinstance(url, str) and url in fetched_by_url:
            fr = fetched_by_url[url]
            r["markdown"] = fr.markdown
            r["filter"] = fr.filter
            if fr.processed_markdown is not None:
                r["processed_markdown"] = fr.processed_markdown
            if fr.llm_error:
                r["llm_error"] = fr.llm_error
        else:
            r.setdefault("markdown", None)
            r.setdefault("filter", None)
    search_dict["fetch_errors"] = [
        {"url": e.url, "error_type": e.error_type, "message": e.message}
        for e in outcome.errors
    ]
    return search_dict
