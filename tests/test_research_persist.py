from __future__ import annotations

import asyncio

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

# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------

def test_make_frontmatter_scalar_round_trips():
    meta = {"created": "2025-01-01T00:00:00Z", "turns": 3}
    fm = _persist.make_frontmatter(meta)
    assert fm.startswith("---\n")
    assert "turns: 3" in fm
    parsed, body = _persist.strip_frontmatter(fm + "## Heading\n\nBody.")
    assert parsed["turns"] == 3
    assert body == "## Heading\n\nBody."


def test_make_frontmatter_list_round_trips():
    meta = {"queries": ["what is X", "how does X work"]}
    fm = _persist.make_frontmatter(meta)
    assert "queries:" in fm
    assert "  - what is X" in fm
    assert "  - how does X work" in fm
    parsed, _ = _persist.strip_frontmatter(fm + "body")
    assert parsed["queries"] == ["what is X", "how does X work"]


def test_make_frontmatter_quotes_special_chars():
    fm = _persist.make_frontmatter({"queries": ["what is X: a guide"]})
    assert '"what is X: a guide"' in fm


def test_strip_frontmatter_no_frontmatter():
    meta, body = _persist.strip_frontmatter("## Just a doc\n\nContent.")
    assert meta == {}
    assert body == "## Just a doc\n\nContent."


def test_strip_frontmatter_numeric_turns():
    text = "---\nturns: 5\ncreated: 2025-01-01T00:00:00Z\n---\n\n## Doc"
    meta, body = _persist.strip_frontmatter(text)
    assert meta["turns"] == 5
    assert body == "## Doc"


def test_strip_frontmatter_quoted_scalar():
    text = '---\nkey: "value: with colon"\n---\n\nbody'
    meta, body = _persist.strip_frontmatter(text)
    assert meta["key"] == "value: with colon"


def test_strip_frontmatter_legacy_query_scalar():
    """Old documents with query: scalar should still parse."""
    text = '---\nquery: what is DNS\nturns: 1\n---\n\nbody'
    meta, _ = _persist.strip_frontmatter(text)
    assert meta["query"] == "what is DNS"


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


def test_pick_location_raises_on_exception():
    cfg = LLMConfig(host="x", api_key=None, model="m")

    class _BrokenCompletions:
        async def create(self, **kwargs):
            raise RuntimeError("network error")

    class _BrokenClient:
        chat = type("X", (), {"completions": _BrokenCompletions()})()

    with pytest.raises(Exception):
        asyncio.run(_persist.pick_location("What is DNS?", cfg, client=_BrokenClient()))


def test_pick_location_raises_on_bad_json():
    cfg = LLMConfig(host="x", api_key=None, model="m")
    client = _FakeClient("not json at all")
    with pytest.raises(ValueError):
        asyncio.run(_persist.pick_location("test query", cfg, client=client))


def test_pick_location_rejects_path_traversal_in_llm_output():
    cfg = LLMConfig(host="x", api_key=None, model="m")
    client = _FakeClient('{"scope": "../../etc", "filename": "../passwd"}')
    scope, slug = asyncio.run(_persist.pick_location("hack", cfg, client=client))
    assert ".." not in scope
    assert ".." not in slug
    assert "/" not in scope
    assert "/" not in slug


# ---------------------------------------------------------------------------
# Persistence tests: <base>/<scope>/<file>.md layout
# ---------------------------------------------------------------------------


def test_resolve_path_base_dir_layout(tmp_path):
    p = _persist.resolve_path("golang", "viper-config-library", base=tmp_path)
    assert p == tmp_path / "golang" / "viper-config-library.md"


def test_resolve_path_tilde_expansion(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from sift import config_file as _cf
    bd = _cf.resolve_base_dir()
    p = _persist.resolve_path("scope", "file", base=bd)
    assert p == tmp_path / ".sift" / "scope" / "file.md"


def test_resolve_path_parent_creation(tmp_path):
    p = _persist.resolve_path("new-scope", "new-file", base=tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    _persist.save(p, "content")
    assert p.exists()
    assert p.read_text() == "content"


def test_resolve_path_collision_suffix(tmp_path):
    (tmp_path / "scope").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scope" / "doc.md").write_text("first")
    p = _persist.resolve_path("scope", "doc", base=tmp_path)
    assert p == tmp_path / "scope" / "doc-2.md"


def test_resolve_path_continue_in_place(tmp_path):
    existing = tmp_path / "scope" / "doc.md"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("content")
    p = _persist.resolve_path("scope", "doc", base=tmp_path, continuing=existing)
    assert p == existing


# ---------------------------------------------------------------------------
# Sanitization tests
# ---------------------------------------------------------------------------


def test_slugify_scope_traversal_stripped():
    slug = _persist._slugify("../../etc/passwd")
    assert ".." not in slug
    assert "/" not in slug


def test_slugify_file_charset_stripped():
    slug = _persist._slugify("my file (copy).md")
    assert slug == "my-file-copy-md"


def test_slugify_length_capped():
    long_name = "a" * 200
    slug = _persist._slugify(long_name)
    assert len(slug) <= _persist._MAX_SLUG_LEN


# ---------------------------------------------------------------------------
# correct_location — Stage-2 correction
# ---------------------------------------------------------------------------


def test_correct_location_returns_corrected_names():
    cfg = LLMConfig(host="x", api_key=None, model="m")
    client = _FakeClient('{"scope": "jwt-auth", "filename": "jwt-refresh-flow"}')
    result = asyncio.run(
        _persist.correct_location("auth", "tokens", "JWT refresh tokens", cfg, client=client)
    )
    assert result == ("jwt-auth", "jwt-refresh-flow")


def test_correct_location_returns_none_when_unchanged():
    cfg = LLMConfig(host="x", api_key=None, model="m")
    client = _FakeClient('{"scope": "auth", "filename": "tokens"}')
    result = asyncio.run(
        _persist.correct_location("auth", "tokens", "some findings", cfg, client=client)
    )
    assert result is None


def test_correct_location_returns_none_on_bad_json():
    cfg = LLMConfig(host="x", api_key=None, model="m")
    client = _FakeClient("not json")
    result = asyncio.run(
        _persist.correct_location("auth", "tokens", "findings", cfg, client=client)
    )
    assert result is None


def test_correct_location_returns_none_on_exception():
    cfg = LLMConfig(host="x", api_key=None, model="m")

    class _BrokenCompletions:
        async def create(self, **kwargs):
            raise RuntimeError("network error")

    class _BrokenClient:
        chat = type("X", (), {"completions": _BrokenCompletions()})()

    result = asyncio.run(
        _persist.correct_location("auth", "tokens", "findings", cfg, client=_BrokenClient())
    )
    assert result is None


def test_correct_location_slugifies_llm_output():
    cfg = LLMConfig(host="x", api_key=None, model="m")
    client = _FakeClient('{"scope": "JWT Auth!!", "filename": "JWT Refresh Flow"}')
    result = asyncio.run(
        _persist.correct_location("old-scope", "old-file", "findings", cfg, client=client)
    )
    assert result == ("jwt-auth", "jwt-refresh-flow")
