from __future__ import annotations

import os
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[1] / "src" / "sift" / "data" / "settings.yml"


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("SEARXNG_SETTINGS_PATH", raising=False)
    yield


@pytest.fixture
def bundled_settings() -> Path:
    return DATA
