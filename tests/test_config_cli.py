from __future__ import annotations

import pytest
from typer.testing import CliRunner

from sift import cli
from sift import config_file as cf

runner = CliRunner()

_ENV_VARS = [s.env for s in cf.KEYS.values()]


@pytest.fixture(autouse=True)
def _clear_sift_env(monkeypatch):
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    yield


@pytest.fixture
def fake_editor(monkeypatch):
    """Record paths handed to the editor instead of launching one."""
    opened: list = []

    def _fake(path):
        opened.append(path)
        return True

    monkeypatch.setattr(cli, "_open_in_editor", _fake)
    return opened


# --- show (task 4.3) ---


def test_config_show_sources_and_mask(monkeypatch):
    monkeypatch.setenv("SIFT_LLM_MODEL", "env-model")
    cf.set("llm.host", "http://file")
    cf.set("llm.api_key", "supersecretkey")
    res = runner.invoke(cli.app, ["--config"])
    assert res.exit_code == 0, res.output
    assert "env-model" in res.output and "[env]" in res.output
    assert "http://file" in res.output and "[file]" in res.output
    assert "supersecretkey" not in res.output  # masked
    assert "tkey" in res.output


# --- init (task 4.4) ---


def test_config_init_writes_template_and_opens_editor(fake_editor):
    res = runner.invoke(cli.app, ["--config", "--init"])
    assert res.exit_code == 0, res.output
    path = cf.config_path()
    assert path.exists()
    assert "Precedence" in path.read_text()
    assert fake_editor == [path]


def test_config_init_refuses_existing(fake_editor):
    cf.set("llm.model", "m")  # creates file
    res = runner.invoke(cli.app, ["--config", "--init"])
    assert res.exit_code == 1
    assert "--force" in res.output
    assert fake_editor == []  # never opened


def test_config_init_force_overwrites(fake_editor):
    cf.set("llm.model", "m")
    res = runner.invoke(cli.app, ["--config", "--init", "--force"])
    assert res.exit_code == 0, res.output
    assert "Precedence" in cf.config_path().read_text()
    assert fake_editor == [cf.config_path()]


def test_config_init_no_editor(monkeypatch):
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    res = runner.invoke(cli.app, ["--config", "--init"])
    assert res.exit_code == 0, res.output
    assert "$EDITOR not set" in res.output


# --- edit / get / set (task 4.5) ---


def test_config_edit_opens_existing(fake_editor):
    cf.set("llm.model", "m")
    res = runner.invoke(cli.app, ["--config", "--edit"])
    assert res.exit_code == 0, res.output
    assert fake_editor == [cf.config_path()]


def test_config_edit_missing_file(fake_editor):
    res = runner.invoke(cli.app, ["--config", "--edit"])
    assert res.exit_code == 1
    assert "--init" in res.output
    assert fake_editor == []


def test_config_get_resolved():
    cf.set("llm.model", "file-model")
    res = runner.invoke(cli.app, ["--config", "llm.model"])
    assert res.exit_code == 0, res.output
    assert res.output.strip() == "file-model"


def test_config_get_unknown_key():
    res = runner.invoke(cli.app, ["--config", "bogus.key"])
    assert res.exit_code == 2
    assert "unknown config key" in res.output


def test_config_set_updates_file():
    res = runner.invoke(cli.app, ["--config", "llm.model=gpt-x"])
    assert res.exit_code == 0, res.output
    assert cf.file_get("llm.model") == "gpt-x"


def test_config_set_unknown_key_does_not_write():
    res = runner.invoke(cli.app, ["--config", "bogus.key=val"])
    assert res.exit_code == 2
    assert not cf.config_path().exists()


def test_init_requires_config_flag():
    res = runner.invoke(cli.app, ["--init"])
    assert res.exit_code == 2
    assert "--config" in res.output
