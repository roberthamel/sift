"""Opt-in live smoke: requires `SEARXNG_CLI_LIVE_CRAWL=1` and a working
crawl4ai browser bundle. Skipped in CI by default."""
from __future__ import annotations

import json
import os

import pytest
from typer.testing import CliRunner

from sift.cli import app


@pytest.mark.skipif(
    os.environ.get("SEARXNG_CLI_LIVE_CRAWL") != "1",
    reason="set SEARXNG_CLI_LIVE_CRAWL=1 to run live crawl4ai smoke test",
)
def test_live_fetch_wikipedia():
    r = CliRunner().invoke(
        app, ["fetch", "https://en.wikipedia.org/wiki/Linux", "--timeout", "60"]
    )
    assert r.exit_code == 0, r.stdout
    data = json.loads(r.stdout)
    assert len(data["results"]) == 1
    md = data["results"][0]["markdown"]
    assert md and len(md) > 200
    assert "Linux" in md
