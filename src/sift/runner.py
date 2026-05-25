"""Run a single in-process SearXNG search and return a serialisable dict."""
from __future__ import annotations

import logging
import threading
from timeit import default_timer

import flask

from . import engines as _engines
from . import serialize

logger = logging.getLogger("sift")
_init_lock = threading.Lock()
_initialised = False


class InitError(RuntimeError):
    pass


def _initialize_once() -> None:
    global _initialised
    with _init_lock:
        if _initialised:
            return
        from searx import search as searx_search

        try:
            searx_search.initialize()
        except Exception as exc:  # pragma: no cover - rewrapped for exit code
            raise InitError(str(exc)) from exc
        _initialised = True


_flask_app = flask.Flask("sift")


def run_search(
    query: str,
    *,
    engine_names: list[str] | None,
    category: str,
    page: int,
    lang: str,
    safesearch: int,
    timeout: float | None,
) -> dict:
    _initialize_once()

    engineref_list = _engines.resolve_engines(engine_names, category)

    from searx.search import Search
    from searx.search.models import SearchQuery

    sq = SearchQuery(
        query=query,
        engineref_list=engineref_list,
        lang=lang,
        safesearch=safesearch,  # type: ignore[arg-type]
        pageno=page,
        timeout_limit=timeout,
    )

    start = default_timer()
    with _flask_app.test_request_context():
        container = Search(sq).search()
    elapsed = default_timer() - start

    return serialize.to_dict(
        container,
        query=query,
        engines_used=[ref.name for ref in engineref_list],
        elapsed=elapsed,
    )


def _host_of(url: str) -> str:
    from urllib.parse import urlsplit

    try:
        return (urlsplit(url).hostname or "").lower()
    except Exception:
        return ""


def _matches_suffix(host: str, suffix: str) -> bool:
    """Suffix match: `wikipedia.org` matches `en.wikipedia.org` and itself,
    but not `notwikipedia.org`."""
    s = suffix.lower().lstrip(".")
    if not s:
        return False
    return host == s or host.endswith("." + s)


def apply_domain_filters(
    results: list[dict],
    allow: list[str] | None,
    block: list[str] | None,
) -> list[dict]:
    """Filter result dicts by URL host suffix. allow wins by inclusion;
    block excludes after allow. Both are case-insensitive."""
    out = []
    allow = [a for a in (allow or []) if a]
    block = [b for b in (block or []) if b]
    for r in results:
        host = _host_of(r.get("url", ""))
        if allow and not any(_matches_suffix(host, a) for a in allow):
            continue
        if block and any(_matches_suffix(host, b) for b in block):
            continue
        out.append(r)
    return out
