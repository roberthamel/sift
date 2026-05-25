from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from sift import cache


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    return tmp_path


def test_make_key_stable():
    k1 = cache.make_key("p", {"q": "x", "n": 1})
    k2 = cache.make_key("p", {"n": 1, "q": "x"})
    assert k1 == k2
    assert cache.make_key("other", {"q": "x", "n": 1}) != k1


def test_hit_and_miss(xdg):
    k = cache.make_key("search", {"q": "x"})
    assert cache.get("search", k, ttl=0) is None
    cache.set("search", k, {"results": [1, 2]})
    assert cache.get("search", k, ttl=0) == {"results": [1, 2]}


def test_ttl_expiry(xdg):
    k = cache.make_key("search", {"q": "x"})
    cache.set("search", k, {"ok": True})
    p = xdg / "sift" / "search" / f"{k}.json"
    # make it stale
    old = time.time() - 100
    os.utime(p, (old, old))
    assert cache.get("search", k, ttl=10) is None
    # but ttl=0 means never expire
    assert cache.get("search", k, ttl=0) == {"ok": True}


def test_search_uses_cache(xdg, monkeypatch):
    """Two `sift search` invocations: the second should hit the cache."""
    from typer.testing import CliRunner
    from sift.cli import app
    from test_search_fetch_flag import _stub_processor

    calls = {"n": 0}
    real_run_search = __import__("sift.runner", fromlist=["run_search"]).run_search

    def counting(*a, **k):
        calls["n"] += 1
        return real_run_search(*a, **k)

    monkeypatch.setattr("sift.runner.run_search", counting)
    _stub_processor(monkeypatch, [
        {"url": "https://r.example", "title": "R", "content": "c", "engine": "wikipedia"},
    ])

    args = ["search", "q", "--engines", "wikipedia"]
    r1 = CliRunner().invoke(app, args)
    assert r1.exit_code == 0, r1.stdout
    r2 = CliRunner().invoke(app, args)
    assert r2.exit_code == 0, r2.stdout
    assert calls["n"] == 1  # second invocation hit cache

    # --no-cache forces a new call
    r3 = CliRunner().invoke(app, args + ["--no-cache"])
    assert r3.exit_code == 0
    assert calls["n"] == 2


def test_clear_and_stats(xdg):
    cache.set("search", cache.make_key("search", {"q": "a"}), {"ok": True})
    cache.set("fetch", cache.make_key("fetch", {"u": "u"}), {"ok": True})
    s = cache.stats()
    assert s.entries == 2
    assert s.bytes > 0
    n = cache.clear()
    assert n == 2
    assert cache.stats().entries == 0


def test_cli_cache_stats_and_clear(xdg):
    import json
    from typer.testing import CliRunner
    from sift.cli import app

    cache.set("search", cache.make_key("search", {"q": "x"}), {"ok": True})
    r = CliRunner().invoke(app, ["cache", "stats"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["entries"] == 1
    assert data["bytes"] > 0

    r2 = CliRunner().invoke(app, ["cache", "clear"])
    assert r2.exit_code == 0
    assert json.loads(r2.stdout) == {"removed": 1}
    assert cache.stats().entries == 0
