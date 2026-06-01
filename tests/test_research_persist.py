from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sift.research import persist as _persist
from sift.llm_config import LLMConfig


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------

def test_slugify_basic():
    assert _persist._slugify("Hello World") == "hello-world"


def test_slugify_path_traversal_stripped():
    slug = _persist._slugify("../../etc/passwd")
    assert ".." not in slug
    assert "/" not in slug


def test_slugify_backslash_stripped():
    slug = _persist._slugify("foo\\bar")
    assert "\\" not in slug


def test_slugify_caps_at_max_len():
    long_str = "a" * 200
    assert len(_persist._slugify(long_str)) <= _persist._MAX_SLUG_LEN


def test_slugify_empty_returns_research():
    assert _persist._slugify("") == "research"


def test_slugify_only_dots_returns_research():
    assert _persist._slugify("....") == "research"


# ---------------------------------------------------------------------------
# resolve_path — collision suffixing
# ---------------------------------------------------------------------------

def test_resolve_path_new_file(tmp_path):
    p = _persist.resolve_path("topic", "my-doc", base=tmp_path)
    assert p == tmp_path / "topic" / "my-doc.md"


def test_resolve_path_collision_appends_suffix(tmp_path):
    existing = tmp_path / "topic" / "my-doc.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("old")
    p = _persist.resolve_path("topic", "my-doc", base=tmp_path)
    assert p == tmp_path / "topic" / "my-doc-2.md"


def test_resolve_path_multiple_collisions(tmp_path):
    base = tmp_path
    for name in ("my-doc.md", "my-doc-2.md", "my-doc-3.md"):
        f = base / "t" / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    p = _persist.resolve_path("t", "my-doc", base=base)
    assert p == base / "t" / "my-doc-4.md"


def test_resolve_path_continuing_rewrites_in_place(tmp_path):
    existing = tmp_path / "topic" / "my-doc.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("old content")
    p = _persist.resolve_path("topic", "my-doc", base=tmp_path, continuing=existing)
    assert p == existing


def test_resolve_path_continuing_with_resolved_path(tmp_path):
    existing = tmp_path / "topic" / "my-doc.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("old")
    # Pass a non-normalised path (same file, different representation)
    other = tmp_path / "topic" / "." / "my-doc.md"
    p = _persist.resolve_path("topic", "my-doc", base=tmp_path, continuing=other)
    assert p.resolve() == existing.resolve()


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------

def test_save_creates_dirs_and_file(tmp_path):
    path = tmp_path / "a" / "b" / "c.md"
    _persist.save(path, "hello")
    assert path.read_text() == "hello"


def test_save_overwrites_existing(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text("old")
    _persist.save(path, "new")
    assert path.read_text() == "new"


# ---------------------------------------------------------------------------
# pick_location — LLM call + fallback
# ---------------------------------------------------------------------------

class _FakeCompletions:
    def __init__(self, content):
        self._content = content

    async def create(self, *, model, messages, max_tokens=None):
        class _Msg:
            content = self._content

        class _Choice:
            message = _Msg()

        class _Resp:
            choices = [_Choice()]

        return _Resp()


class _FakeClient:
    def __init__(self, content):
        self.chat = type("X", (), {"completions": _FakeCompletions(content)})()


def test_pick_location_parses_llm_json():
    cfg = LLMConfig(host="x", api_key=None, model="m")
    client = _FakeClient('{"scope": "jwt-auth", "filename": "jwt-refresh-flow"}')
    scope, slug = asyncio.run(_persist.pick_location("How does JWT refresh work?", cfg, client=client))
    assert scope == "jwt-auth"
    assert slug == "jwt-refresh-flow"


def test_pick_location_slugifies_llm_output():
    cfg = LLMConfig(host="x", api_key=None, model="m")
    client = _FakeClient('{"scope": "JWT Auth!!", "filename": "JWT Refresh Flow"}')
    scope, slug = asyncio.run(_persist.pick_location("JWT refresh", cfg, client=client))
    assert scope == "jwt-auth"
    assert slug == "jwt-refresh-flow"


def test_pick_location_fallback_on_exception():
    cfg = LLMConfig(host="x", api_key=None, model="m")

    class _BrokenCompletions:
        async def create(self, **kwargs):
            raise RuntimeError("network error")

    class _BrokenClient:
        chat = type("X", (), {"completions": _BrokenCompletions()})()

    scope, slug = asyncio.run(_persist.pick_location("What is DNS?", cfg, client=_BrokenClient()))
    assert scope != ""
    assert slug != ""
    assert ".." not in scope and ".." not in slug


def test_pick_location_fallback_on_bad_json():
    cfg = LLMConfig(host="x", api_key=None, model="m")
    client = _FakeClient("not json at all")
    scope, slug = asyncio.run(_persist.pick_location("test query", cfg, client=client))
    assert scope and slug


def test_pick_location_rejects_path_traversal_in_llm_output():
    cfg = LLMConfig(host="x", api_key=None, model="m")
    client = _FakeClient('{"scope": "../../etc", "filename": "../passwd"}')
    scope, slug = asyncio.run(_persist.pick_location("hack", cfg, client=client))
    assert ".." not in scope
    assert ".." not in slug
    assert "/" not in scope
    assert "/" not in slug
