from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from sift import cli, synthesize as synth_mod
from sift.llm_config import LLMConfig


def test_build_payload_search_snippet_only():
    doc = {"query": "q", "results": [{"title": "T", "url": "u", "content": "snip"}]}
    p = synth_mod.build_synthesize_payload(doc, "q")
    assert p["snippet_only"] is True
    assert p["source_count"] == 1
    assert p["sources"][0]["snippet"] == "snip"
    assert "content" not in p["sources"][0]


def test_build_payload_fetch_content():
    doc = {"results": [{"url": "u", "markdown": "body", "title": "T"}]}
    p = synth_mod.build_synthesize_payload(doc, "q")
    assert p["snippet_only"] is False
    assert p["sources"][0]["content"] == "body"


def test_build_payload_processed_wins():
    doc = {"results": [{"url": "u", "markdown": "raw", "processed_markdown": "proc"}]}
    p = synth_mod.build_synthesize_payload(doc, "q")
    assert p["sources"][0]["content"] == "proc"


def test_build_payload_errors_carried():
    doc = {
        "results": [],
        "fetch_errors": [{"url": "u", "error_type": "timeout", "message": "t/o"}],
    }
    p = synth_mod.build_synthesize_payload(doc, "q")
    assert p["errors"] == [{"url": "u", "error": "t/o"}]


def _run(stdin: str, env=None):
    runner = CliRunner()
    default = {"SIFT_LLM_HOST": "http://x", "SIFT_LLM_MODEL": "m", "SIFT_LLM_APIKEY": "-"}
    if env:
        default.update(env)
    return runner.invoke(cli.app, ["synthesize", "what is q"], input=stdin, env=default)


def test_cli_synthesize_happy():
    payload = json.dumps({"query": "q", "results": [{"url": "u", "markdown": "hi"}]})
    async def fake_synth(query, results, cfg, **kw):
        return "the answer", None
    with patch("sift.llm.synthesize_search_results", side_effect=fake_synth):
        r = _run(payload)
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["summary"] == "the answer"
    assert out["snippet_only"] is False
    assert out["source_count"] == 1


def test_cli_synthesize_llm_failure_soft():
    payload = json.dumps({"query": "q", "results": [{"url": "u", "markdown": "hi"}]})
    async def fake_synth(query, results, cfg, **kw):
        return None, "LLM processing failed: boom"
    with patch("sift.llm.synthesize_search_results", side_effect=fake_synth):
        r = _run(payload)
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["summary"] is None
    assert "boom" in out["llm_error"]


def test_cli_synthesize_empty_results():
    payload = json.dumps({"query": "q", "results": []})
    r = _run(payload)
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["summary"] == ""
    assert out["source_count"] == 0


def test_cli_synthesize_missing_config():
    runner = CliRunner()
    r = runner.invoke(cli.app, ["synthesize", "q"], input="{}", env={
        "SIFT_LLM_HOST": "", "SIFT_LLM_MODEL": "", "SIFT_LLM_APIKEY": ""
    })
    assert r.exit_code == 2
    assert "LLM not configured" in r.stderr or "LLM not configured" in r.output
