"""Opt-in live-LLM smoke test.

Gated on `SIFT_LIVE_LLM=1` plus a configured endpoint. Skipped in CI.
"""
from __future__ import annotations

import json
import os

import pytest
from typer.testing import CliRunner

from sift.cli import app


_GATE = (
    os.environ.get("SIFT_LIVE_LLM") == "1"
    and os.environ.get("SIFT_LLM_HOST")
    and os.environ.get("SIFT_LLM_MODEL")
)


@pytest.mark.skipif(not _GATE, reason="set SIFT_LIVE_LLM=1 + SIFT_LLM_HOST/MODEL to run")
def test_live_llm_synthesize_about_linux():
    payload = json.dumps({
        "query": "what is linux",
        "results": [
            {
                "url": "https://en.wikipedia.org/wiki/Linux",
                "title": "Linux",
                "content": "Linux is a family of open-source Unix-like operating systems based on the Linux kernel, an operating system kernel first released on September 17, 1991, by Linus Torvalds.",
                "engine": "wikipedia",
            }
        ],
    })
    r = CliRunner().invoke(app, ["synthesize", "what is linux"], input=payload)
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["llm_error"] is None or "llm_error" not in out, out
    assert out["summary"] and len(out["summary"]) > 50
    assert "linux" in out["summary"].lower()
