from __future__ import annotations

import io

from sift import inputs


def _stdin(text: str) -> io.StringIO:
    return io.StringIO(text)


def test_positional_args_win_over_stdin():
    r = inputs.resolve(
        ["https://a.example", "https://b.example"],
        _stdin("https://stdin.example\n"),
        stdin_is_tty=False,
    )
    assert r.urls == ["https://a.example", "https://b.example"]
    assert r.search_json is None


def test_tty_with_no_args_returns_empty():
    r = inputs.resolve([], _stdin(""), stdin_is_tty=True)
    assert r.urls == []
    assert r.search_json is None


def test_url_list_on_stdin_with_blanks_and_comments():
    text = """
# this is a comment
https://example.com/a

  https://example.com/b
# another comment
https://example.com/c
"""
    r = inputs.resolve([], _stdin(text), stdin_is_tty=False)
    assert r.urls == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]
    assert r.search_json is None


def test_search_json_on_stdin_extracts_urls_and_passthrough():
    doc = (
        '{"query": "q", "results": ['
        '{"url": "https://x.example", "title": "X"},'
        '{"url": "https://y.example", "title": "Y"}'
        '], "answers": [], "infoboxes": []}'
    )
    r = inputs.resolve([], _stdin(doc), stdin_is_tty=False)
    assert r.urls == ["https://x.example", "https://y.example"]
    assert r.search_json is not None
    assert r.search_json["query"] == "q"


def test_unparseable_json_falls_back_to_url_list():
    # Starts with `{` but invalid — treat as plaintext, which yields one
    # "URL" line; later URL validation in fetcher rejects it as invalid.
    r = inputs.resolve([], _stdin("{not json"), stdin_is_tty=False)
    assert r.urls == ["{not json"]
    assert r.search_json is None


def test_empty_stdin_returns_empty():
    r = inputs.resolve([], _stdin("\n\n\n"), stdin_is_tty=False)
    assert r.urls == []
