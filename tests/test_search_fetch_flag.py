"""`search --fetch` end-to-end with engine processor stubbed and crawler mocked."""
from __future__ import annotations

import asyncio
import json

import pytest
from typer.testing import CliRunner

from sift.cli import app


class _FakeMarkdown:
    def __init__(self, fit, raw=None):
        self.fit_markdown = fit
        self.raw_markdown = raw or fit


class _FakeResult:
    def __init__(self, success=True, md="# md", error=""):
        self.success = success
        self.error_message = error
        self.markdown = _FakeMarkdown(md)


class FakeCrawler:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def arun(self, url, config=None):
        if "fail" in url:
            return _FakeResult(success=False, error="boom")
        if "timeout" in url:
            await asyncio.sleep(10)
        return _FakeResult(md=f"# md for {url}")


def _stub_processor(monkeypatch, results: list[dict]):
    import searx.search as ss
    from searx.search.models import EngineRef

    class StubProcessor:
        class engine:
            timeout = 1.0

        def get_params(self, sq, category):
            return {}

        def extend_container_if_suspended(self, container):
            return False

        def search(self, query, request_params, container, start_time, timeout):
            container.extend("wikipedia", results)

    import sift.bootstrap as bs
    bs.bootstrap()
    import sift.runner as runner
    runner._initialize_once()

    monkeypatch.setitem(ss.PROCESSORS, "wikipedia", StubProcessor())
    monkeypatch.setattr(
        "sift.engines.resolve_engines",
        lambda names, category: [EngineRef("wikipedia", "general")],
    )


@pytest.fixture
def patch_crawler(monkeypatch):
    import crawl4ai
    monkeypatch.setattr(crawl4ai, "AsyncWebCrawler", FakeCrawler)
    yield


def test_search_without_fetch_keeps_existing_shape(monkeypatch):
    _stub_processor(monkeypatch, [
        {"url": "https://a.example", "title": "A", "content": "snip", "engine": "wikipedia"},
        {"url": "https://b.example", "title": "B", "content": "snip", "engine": "wikipedia"},
    ])
    r = CliRunner().invoke(app, ["search", "q", "--engines", "wikipedia"])
    assert r.exit_code == 0, r.stdout
    data = json.loads(r.stdout)
    assert "fetch_errors" not in data
    assert "markdown" not in data["results"][0]


def test_search_with_fetch_top_2_embeds_markdown(monkeypatch, patch_crawler):
    _stub_processor(monkeypatch, [
        {"url": f"https://r{n}.example", "title": f"R{n}", "content": "", "engine": "wikipedia"}
        for n in range(4)
    ])
    r = CliRunner().invoke(
        app, ["search", "q", "--engines", "wikipedia", "--fetch", "--fetch-top", "2"]
    )
    assert r.exit_code == 0, r.stdout
    data = json.loads(r.stdout)
    assert "fetch_errors" in data
    fetched = [r for r in data["results"] if r.get("markdown")]
    assert len(fetched) == 2
    null_md = [r for r in data["results"] if r.get("markdown") is None]
    assert len(null_md) == 2
    assert fetched[0]["filter"] == "fit"


def test_search_with_fetch_uses_search_query_for_bm25(monkeypatch, patch_crawler):
    _stub_processor(monkeypatch, [
        {"url": "https://r.example", "title": "R", "content": "", "engine": "wikipedia"},
    ])
    # bm25 normally requires --query; --fetch should default it to the search query.
    r = CliRunner().invoke(app, [
        "search", "my-query", "--engines", "wikipedia", "--fetch", "--filter", "bm25"
    ])
    assert r.exit_code == 0, r.stdout
    data = json.loads(r.stdout)
    assert data["results"][0]["markdown"]
    assert data["results"][0]["filter"] == "bm25"


def test_search_fetch_does_not_demote_exit_code_on_fetch_failure(monkeypatch, patch_crawler):
    # All result URLs go to a "fail" endpoint — crawler returns success=False.
    _stub_processor(monkeypatch, [
        {"url": "https://fail.example", "title": "F", "content": "", "engine": "wikipedia"},
    ])
    r = CliRunner().invoke(app, [
        "search", "q", "--engines", "wikipedia", "--fetch", "--fetch-top", "1"
    ])
    assert r.exit_code == 0, r.stdout
    data = json.loads(r.stdout)
    assert data["results"][0]["markdown"] is None
    assert len(data["fetch_errors"]) == 1
