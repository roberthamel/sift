from __future__ import annotations

import pytest

from sift import llm_config


def test_flag_wins_over_env(monkeypatch):
    monkeypatch.setenv("SIFT_LLM_HOST", "http://env")
    monkeypatch.setenv("SIFT_LLM_MODEL", "env-model")
    cfg = llm_config.resolve(host="http://flag", model="flag-model")
    assert cfg.host == "http://flag"
    assert cfg.model == "flag-model"


def test_env_fallback(monkeypatch):
    monkeypatch.setenv("SIFT_LLM_HOST", "http://env")
    monkeypatch.setenv("SIFT_LLM_APIKEY", "envkey")
    monkeypatch.setenv("SIFT_LLM_MODEL", "envmodel")
    cfg = llm_config.resolve()
    assert cfg.host == "http://env"
    assert cfg.api_key == "envkey"
    assert cfg.model == "envmodel"


def test_for_llm_missing(monkeypatch):
    monkeypatch.delenv("SIFT_LLM_HOST", raising=False)
    monkeypatch.delenv("SIFT_LLM_MODEL", raising=False)
    cfg = llm_config.resolve()
    with pytest.raises(llm_config.ConfigError) as ei:
        cfg.for_llm()
    assert "--llm-host" in str(ei.value)
    assert "--llm-model" in str(ei.value)


def test_for_vlm_requires_flag(monkeypatch):
    cfg = llm_config.resolve(host="h", model="m", vlm=False)
    monkeypatch.delenv("SIFT_VLM", raising=False)
    with pytest.raises(llm_config.ConfigError) as ei:
        cfg.for_vlm()
    assert "--vlm" in str(ei.value)


def test_for_vlm_env(monkeypatch):
    monkeypatch.setenv("SIFT_VLM", "1")
    cfg = llm_config.resolve(host="h", model="m")
    cfg.for_vlm()  # does not raise


def test_for_vlm_flag(monkeypatch):
    monkeypatch.delenv("SIFT_VLM", raising=False)
    cfg = llm_config.resolve(host="h", model="m", vlm=True)
    cfg.for_vlm()
