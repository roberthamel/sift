"""`search --summary` and `--allow/--block` flag wiring."""
from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from sift.cli import app

from test_search_fetch_flag import _stub_processor, patch_crawler  # noqa: F401


def test_search_allow_filter(monkeypatch):
    _stub_processor(monkeypatch, [
        {"url": "https://en.wikipedia.org/wiki/X", "title": "W", "content": "", "engine": "wikipedia"},
        {"url": "https://example.com/x", "title": "E", "content": "", "engine": "wikipedia"},
    ])
    r = CliRunner().invoke(app, [
        "search", "q", "--engines", "wikipedia", "--allow", "wikipedia.org"
    ])
    assert r.exit_code == 0, r.stdout
    data = json.loads(r.stdout)
    assert len(data["results"]) == 1
    assert "wikipedia.org" in data["results"][0]["url"]


def test_search_summary_chains_through_llm(monkeypatch, patch_crawler):
    _stub_processor(monkeypatch, [
        {"url": "https://r.example", "title": "R", "content": "snip", "engine": "wikipedia"},
    ])
    async def fake_synth(query, results, cfg, **kw):
        assert results, "synthesize must receive sources"
        return "the summary", None
    env = {"SIFT_LLM_HOST": "http://x", "SIFT_LLM_MODEL": "m", "SIFT_LLM_APIKEY": "-"}
    with patch("sift.llm.synthesize_search_results", side_effect=fake_synth):
        r = CliRunner().invoke(app, [
            "search", "q", "--engines", "wikipedia", "--summary",
        ], env=env)
    assert r.exit_code == 0, r.stdout
    data = json.loads(r.stdout)
    assert data["summary"] == "the summary"


def test_search_summary_soft_fails_on_missing_config(monkeypatch, patch_crawler):
    _stub_processor(monkeypatch, [
        {"url": "https://r.example", "title": "R", "content": "snip", "engine": "wikipedia"},
    ])
    env = {"SIFT_LLM_HOST": "", "SIFT_LLM_MODEL": "", "SIFT_LLM_APIKEY": ""}
    r = CliRunner().invoke(app, [
        "search", "q", "--engines", "wikipedia", "--summary",
    ], env=env)
    # Missing LLM config — search still returns OK with summary=null + llm_error.
    assert r.exit_code == 0, r.stdout
    data = json.loads(r.stdout)
    assert data["summary"] is None
    assert "LLM not configured" in data["llm_error"]
