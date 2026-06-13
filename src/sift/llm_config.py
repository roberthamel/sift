"""LLM configuration resolved from CLI flags + SIFT_LLM_* env vars.

A single `LLMConfig` is used by every LLM-touching command. There is no
separate VLM endpoint configuration: `--vlm` / `SIFT_VLM=1` asserts that the
configured model has vision capabilities.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(ValueError):
    """Raised when required LLM config fields are missing."""


@dataclass(frozen=True)
class LLMConfig:
    host: str | None
    api_key: str | None
    model: str | None
    vlm: bool = False
    timeout: float = 3600.0  # 1 hour — local LLMs on slow hardware can take a while

    def for_llm(self) -> "LLMConfig":
        missing = []
        if not self.host:
            missing.append("--llm-host (or SIFT_LLM_HOST)")
        if not self.model:
            missing.append("--llm-model (or SIFT_LLM_MODEL)")
        if missing:
            raise ConfigError(
                "LLM not configured: missing " + ", ".join(missing)
            )
        return self

    def for_vlm(self) -> "LLMConfig":
        self.for_llm()
        if not self.vlm:
            raise ConfigError(
                "VLM mode required: pass --vlm or set SIFT_VLM=1 to assert "
                "the configured model supports vision."
            )
        return self


def _coerce_bool(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "on")


def _coerce_float(v: str, default: float) -> float:
    try:
        return float(v.strip().strip("'\""))
    except ValueError:
        return default


def _resolve_flag(env_name: str, file_key: str) -> bool:
    """Resolve a boolean across env → file → False, env taking precedence."""
    from . import config_file as _cf

    if env_name in os.environ:
        return _coerce_bool(os.environ[env_name] or "")
    fv = _cf.file_get(file_key)
    if fv is not None:
        return _coerce_bool(fv)
    return False


def _resolve_float(env_name: str, file_key: str, default: float) -> float:
    """Resolve a float across env → file → default, env taking precedence."""
    from . import config_file as _cf

    if env_name in os.environ:
        return _coerce_float(os.environ[env_name] or "", default)
    fv = _cf.file_get(file_key)
    if fv is not None:
        return _coerce_float(fv, default)
    return default


def resolve(
    host: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    vlm: bool | None = None,
    timeout: float | None = None,
) -> LLMConfig:
    """Resolve config: flag → SIFT_LLM_* env var → config file → default.

    Explicitly passing ``vlm=False`` disables VLM even when the env var is set.
    """
    from . import config_file as _cf

    return LLMConfig(
        host=host or os.environ.get("SIFT_LLM_HOST") or _cf.file_get("llm.host"),
        api_key=api_key or os.environ.get("SIFT_LLM_APIKEY") or _cf.file_get("llm.api_key"),
        model=model or os.environ.get("SIFT_LLM_MODEL") or _cf.file_get("llm.model"),
        vlm=vlm if vlm is not None else _resolve_flag("SIFT_VLM", "llm.vlm"),
        timeout=(
            timeout
            if timeout is not None
            else _resolve_float("SIFT_LLM_TIMEOUT", "llm.timeout", 3600.0)
        ),
    )
