from __future__ import annotations

from sift import runner


def test_allow_suffix():
    rs = [
        {"url": "https://en.wikipedia.org/wiki/X"},
        {"url": "https://notwikipedia.org/x"},
        {"url": "https://example.com/x"},
    ]
    out = runner.apply_domain_filters(rs, allow=["wikipedia.org"], block=None)
    assert [r["url"] for r in out] == ["https://en.wikipedia.org/wiki/X"]


def test_block_suffix():
    rs = [
        {"url": "https://en.wikipedia.org/wiki/X"},
        {"url": "https://example.com/x"},
    ]
    out = runner.apply_domain_filters(rs, allow=None, block=["wikipedia.org"])
    assert [r["url"] for r in out] == ["https://example.com/x"]


def test_allow_then_block():
    rs = [
        {"url": "https://en.wikipedia.org/x"},
        {"url": "https://bad.wikipedia.org/x"},
    ]
    out = runner.apply_domain_filters(
        rs, allow=["wikipedia.org"], block=["bad.wikipedia.org"]
    )
    assert [r["url"] for r in out] == ["https://en.wikipedia.org/x"]


def test_empty_filters_passthrough():
    rs = [{"url": "https://x"}]
    assert runner.apply_domain_filters(rs, None, None) == rs


def test_dot_prefix_tolerated():
    rs = [{"url": "https://en.wikipedia.org/x"}]
    out = runner.apply_domain_filters(rs, allow=[".wikipedia.org"], block=None)
    assert len(out) == 1
