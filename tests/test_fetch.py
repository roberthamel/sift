"""fetcher module tests with crawl4ai mocked."""
from __future__ import annotations

import asyncio

import pytest

from sift import fetcher


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
