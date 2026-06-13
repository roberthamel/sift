from __future__ import annotations

import pytest

from sift import config_file as cf
from sift import llm_config
from sift.research import embed_config

# SIFT_* env vars from the developer's shell would mask file values; clear them
# so file-fallback behaviour is what's actually under test.
_ENV_VARS = [s.env for s in cf.KEYS.values()]


@pytest.fixture(autouse=True)
def _clear_sift_env(monkeypatch):
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    yield


def test_config_path_uses_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert cf.config_path() == tmp_path / "cfg" / "sift" / "config.yaml"


def test_config_path_defaults_to_home(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(cf.Path, "home", staticmethod(lambda: tmp_path))
    assert cf.config_path() == tmp_path / ".config" / "sift" / "config.yaml"


def test_load_missing_returns_empty():
    assert cf.load() == {}


def test_set_creates_file_and_get_reads_it():
    saved = cf.set("llm.model", "gpt-x")
    assert saved.exists()
    assert cf.file_get("llm.model") == "gpt-x"


def test_set_preserves_other_keys():
    cf.set("llm.model", "m1")
    cf.set("llm.host", "http://h")
    assert cf.file_get("llm.model") == "m1"
    assert cf.file_get("llm.host") == "http://h"


def test_set_rejects_unknown_key():
    with pytest.raises(KeyError):
        cf.set("bogus.key", "x")


def test_load_malformed_raises():
    path = cf.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("llm: : : not valid\n  - broken")
    with pytest.raises(cf.ConfigFileError):
        cf.load()


def test_load_warns_on_unknown_section(caplog):
    path = cf.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("mystery:\n  foo: bar\n")
    cf.load()
    assert any("unknown config section" in r.message for r in caplog.records)


def test_mask_hides_all_but_last_four():
    assert cf.mask("supersecretkey") == "**********tkey"
    assert cf.mask("ab") == "****"
    assert cf.mask(None) == "(unset)"


def test_template_lists_all_keys():
    text = cf.template_text()
    for key in cf.KEYS:
        section, _, leaf = key.partition(".")
        assert f"{leaf}:" in text
    assert "Precedence" in text


# --- resolution precedence (task 4.2) ---


def test_resolve_value_env_over_file(monkeypatch):
    cf.set("llm.model", "file-model")
    monkeypatch.setenv("SIFT_LLM_MODEL", "env-model")
    value, source = cf.resolve_value("llm.model")
    assert value == "env-model"
    assert source == "env"


def test_resolve_value_file_when_no_env():
    cf.set("llm.model", "file-model")
    value, source = cf.resolve_value("llm.model")
    assert value == "file-model"
    assert source == "file"


def test_resolve_value_default():
    value, source = cf.resolve_value("llm.timeout")
    assert value == "3600.0"
    assert source == "default"


def test_resolve_value_unset():
    value, source = cf.resolve_value("llm.host")
    assert value is None
    assert source == "unset"


def test_llm_resolve_flag_over_env_over_file(monkeypatch):
    cf.set("llm.model", "file-model")
    cf.set("llm.host", "http://file")
    monkeypatch.setenv("SIFT_LLM_MODEL", "env-model")
    # model: flag wins; host: env absent so file wins
    cfg = llm_config.resolve(model="flag-model")
    assert cfg.model == "flag-model"
    assert cfg.host == "http://file"


def test_llm_resolve_file_fallback_for_vlm_and_timeout():
    cf.set("llm.vlm", "true")
    cf.set("llm.timeout", "12.5")
    cfg = llm_config.resolve()
    assert cfg.vlm is True
    assert cfg.timeout == 12.5


def test_llm_env_vlm_beats_file(monkeypatch):
    cf.set("llm.vlm", "true")
    monkeypatch.setenv("SIFT_VLM", "0")
    cfg = llm_config.resolve()
    assert cfg.vlm is False  # env explicitly disables, beating the file


def test_embed_resolve_file_fallback():
    cf.set("embed.base_url", "http://efile")
    cf.set("embed.model", "emodel")
    cf.set("embed.timeout", "42")
    cfg = embed_config.resolve()
    assert cfg.host == "http://efile"
    assert cfg.model == "emodel"
    assert cfg.timeout == 42.0
