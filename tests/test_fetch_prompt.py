from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from sift.cli import app

from test_search_fetch_flag import patch_crawler  # noqa: F401


def test_fetch_prompt_attaches_processed(patch_crawler):
    async def fake_process(content, cfg, prompt):
        assert prompt == "summarize"
        return f"PROC[{content[:5]}]", None
    env = {"SIFT_LLM_HOST": "http://x", "SIFT_LLM_MODEL": "m", "SIFT_LLM_APIKEY": "-"}
    with patch("sift.llm.process_page_content", side_effect=fake_process):
        r = CliRunner().invoke(app, [
            "fetch", "https://r.example", "--prompt", "summarize"
        ], env=env)
    assert r.exit_code == 0, r.stdout
    data = json.loads(r.stdout)
    res = data["results"][0]
    assert res["markdown"].startswith("# md")
    assert res["processed_markdown"].startswith("PROC[")
    assert "llm_error" not in res


def test_fetch_prompt_llm_error_leaves_markdown_intact(patch_crawler):
    async def fake_process(content, cfg, prompt):
        return None, "LLM processing failed: boom"
    env = {"SIFT_LLM_HOST": "http://x", "SIFT_LLM_MODEL": "m", "SIFT_LLM_APIKEY": "-"}
    with patch("sift.llm.process_page_content", side_effect=fake_process):
        r = CliRunner().invoke(app, [
            "fetch", "https://r.example", "--prompt", "summarize"
        ], env=env)
    assert r.exit_code == 0, r.stdout
    data = json.loads(r.stdout)
    res = data["results"][0]
    assert res["markdown"]
    assert res.get("processed_markdown") is None
    assert "boom" in res["llm_error"]


def test_fetch_prompt_requires_llm_config(patch_crawler):
    env = {"SIFT_LLM_HOST": "", "SIFT_LLM_MODEL": "", "SIFT_LLM_APIKEY": ""}
    r = CliRunner().invoke(app, [
        "fetch", "https://r.example", "--prompt", "summarize"
    ], env=env)
    assert r.exit_code == 2
    assert "LLM not configured" in (r.stderr or r.output)
