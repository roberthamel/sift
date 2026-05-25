"""Fetch subcommand tests with crawl4ai mocked."""
from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from sift import fetcher
from sift.cli import app


class FakeMarkdown:
    def __init__(self, fit: str, raw: str | None = None):
        self.fit_markdown = fit
        self.raw_markdown = raw if raw is not None else fit


class FakeResult:
    def __init__(self, success=True, md="# hello\nbody", error=""):
        self.success = success
        self.error_message = error
        self.markdown = FakeMarkdown(md)


class FakeCrawler:
    """Stand-in for AsyncWebCrawler. Async context manager + arun()."""

    def __init__(self, *args, **kwargs):
        self.calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def arun(self, url: str, config=None):
        self.calls.append(url)
        if "fail" in url:
            return FakeResult(success=False, error="boom")
        if "timeout" in url:
            await asyncio.sleep(10)
        if "raise" in url:
            raise ConnectionError("network down")
        return FakeResult(md=f"# md for {url}")


@pytest.fixture
def patch_crawler(monkeypatch):
    """Replace AsyncWebCrawler on the real crawl4ai module so no browser
    is launched. All other crawl4ai submodules (content filters, markdown
    generators, AsyncLogger) keep their real implementations."""
    import crawl4ai

    monkeypatch.setattr(crawl4ai, "AsyncWebCrawler", FakeCrawler)
    yield


def test_fetcher_basic(patch_crawler):
    out = fetcher.fetch_urls(
        ["https://a.example", "https://b.example"],
        fetcher.FetchOptions(),
    )
    assert len(out.results) == 2
    assert out.errors == []
    assert out.results[0].filter == "fit"
    assert out.results[0].markdown.startswith("# md for")


def test_fetcher_invalid_url_classified(patch_crawler):
    out = fetcher.fetch_urls(
        ["not-a-url", "https://ok.example"],
        fetcher.FetchOptions(),
    )
    assert len(out.results) == 1
    assert len(out.errors) == 1
    assert out.errors[0].error_type == "invalid_url"


def test_fetcher_timeout(patch_crawler):
    out = fetcher.fetch_urls(
        ["https://timeout.example"],
        fetcher.FetchOptions(timeout=0.05),
    )
    assert out.results == []
    assert out.errors[0].error_type == "timeout"


def test_fetcher_crawl_unsuccessful(patch_crawler):
    out = fetcher.fetch_urls(
        ["https://fail.example"],
        fetcher.FetchOptions(),
    )
    assert out.errors[0].error_type == "http_error"


def test_fetcher_network_exception(patch_crawler):
    out = fetcher.fetch_urls(
        ["https://raise.example"],
        fetcher.FetchOptions(),
    )
    assert out.errors[0].error_type == "network"


def test_fetcher_bm25_requires_query(patch_crawler):
    with pytest.raises(ValueError, match="bm25 requires --query"):
        fetcher.fetch_urls(
            ["https://ok.example"],
            fetcher.FetchOptions(filter="bm25"),
        )


def test_cli_fetch_positional(patch_crawler):
    r = CliRunner().invoke(app, ["fetch", "https://a.example", "https://b.example"])
    assert r.exit_code == 0, r.stdout
    data = json.loads(r.stdout)
    assert isinstance(data["results"], list)
    assert isinstance(data["fetch_errors"], list)
    assert isinstance(data["elapsed_seconds"], float)
    assert {r["url"] for r in data["results"]} == {
        "https://a.example",
        "https://b.example",
    }
    assert data["results"][0]["filter"] == "fit"


def test_cli_fetch_no_urls_exits_nonzero(patch_crawler):
    # No args + no stdin pipe (CliRunner makes stdin a tty-less StringIO; we
    # pass empty input which the isatty check treats as a TTY-equivalent
    # producing no URLs). We expect exit 2 with usage error.
    r = CliRunner().invoke(app, ["fetch"], input="")
    assert r.exit_code == 2


def test_cli_fetch_stdin_url_list(patch_crawler):
    r = CliRunner().invoke(
        app, ["fetch"], input="https://a.example\nhttps://b.example\n"
    )
    assert r.exit_code == 0, r.stdout
    data = json.loads(r.stdout)
    assert len(data["results"]) == 2


def test_cli_fetch_stdin_search_json_passthrough(patch_crawler):
    search_doc = {
        "query": "linux",
        "results": [
            {
                "url": "https://x.example",
                "title": "X title",
                "engine": "wikipedia",
                "score": 1.0,
                "category": "general",
                "content": "snippet",
            }
        ],
        "answers": [],
    }
    r = CliRunner().invoke(app, ["fetch"], input=json.dumps(search_doc))
    assert r.exit_code == 0, r.stdout
    data = json.loads(r.stdout)
    row = data["results"][0]
    assert row["title"] == "X title"
    assert row["engine"] == "wikipedia"
    assert row["markdown"].startswith("# md for")
    assert row["filter"] == "fit"


def test_cli_fetch_hard_cap(patch_crawler):
    urls = [f"https://h{n}.example" for n in range(51)]
    r = CliRunner().invoke(app, ["fetch", *urls])
    assert r.exit_code == 2
    assert "hard cap" in (r.stderr or r.stdout)


def test_cli_fetch_all_failed_nonzero(patch_crawler):
    r = CliRunner().invoke(
        app, ["fetch", "https://fail.example", "https://raise.example"]
    )
    assert r.exit_code == 1
    data = json.loads(r.stdout)
    assert data["results"] == []
    assert len(data["fetch_errors"]) == 2


def test_cli_fetch_bm25_without_query_errors(patch_crawler):
    r = CliRunner().invoke(
        app, ["fetch", "https://ok.example", "--filter", "bm25"]
    )
    assert r.exit_code == 2
    assert "bm25" in (r.stderr or r.stdout)
