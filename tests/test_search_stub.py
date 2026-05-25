"""Drive run_search end-to-end with a stubbed engine processor."""
from __future__ import annotations

from typer.testing import CliRunner

from sift.cli import app


def _stub_processors(monkeypatch, captured: dict):
    """Replace PROCESSORS to short-circuit network and add a synthetic result."""
    import searx.search as ss
    from searx.results import ResultContainer

    class StubProcessor:
        class engine:
            timeout = 1.0

        def get_params(self, sq, category):
            captured["sq"] = sq
            captured["category"] = category
            return {}

        def extend_container_if_suspended(self, container):
            return False

        def search(self, query, request_params, container, start_time, timeout):
            container.extend("wikipedia", [{
                "url": "https://example.org/x",
                "title": "Hello",
                "content": "world",
                "engine": "wikipedia",
            }])

    monkeypatch.setitem(ss.PROCESSORS, "wikipedia", StubProcessor())


def test_search_stub_returns_schema(monkeypatch):
    # Force bootstrap to complete before we patch.
    import sift.bootstrap as bs
    bs.bootstrap()
    import sift.runner as runner
    runner._initialize_once()

    captured: dict = {}
    _stub_processors(monkeypatch, captured)

    # Force resolve_engines to only return wikipedia, regardless of categories.
    from searx.search.models import EngineRef
    monkeypatch.setattr(
        "sift.engines.resolve_engines",
        lambda names, category: [EngineRef("wikipedia", "general")],
    )

    r = CliRunner().invoke(app, ["search", "linux", "--engines", "wikipedia"])
    assert r.exit_code == 0, r.stdout
    import json
    data = json.loads(r.stdout)
    for k in (
        "query", "engines_used", "results", "answers", "infoboxes",
        "suggestions", "corrections", "unresponsive_engines",
        "number_of_results", "elapsed_seconds",
    ):
        assert k in data, k
    assert data["results"][0]["title"] == "Hello"
    # SearchQuery forwarded correctly
    sq = captured["sq"]
    assert sq.pageno == 1
    assert sq.lang == "all"
    assert sq.safesearch == 0
