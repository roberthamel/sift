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
