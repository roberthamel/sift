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
    timeout: float = 60.0

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


def _envflag(name: str) -> bool:
    v = os.environ.get(name)
    if v is None:
        return False
    return v.strip().lower() in ("1", "true", "yes", "on")


def _envfloat(name: str, default: float) -> float:
    v = os.environ.get(name)
    if v is None:
        return default
    try:
        return float(v.strip().strip("'\""))
    except ValueError:
        return default


def resolve(
    host: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    vlm: bool = False,
    timeout: float | None = None,
) -> LLMConfig:
    """Resolve config from flags, falling back to SIFT_LLM_* env vars.

    `vlm=True` from the flag is sticky; the env var only contributes when the
    flag isn't set.
    """
    return LLMConfig(
        host=host or os.environ.get("SIFT_LLM_HOST"),
        api_key=api_key or os.environ.get("SIFT_LLM_APIKEY"),
        model=model or os.environ.get("SIFT_LLM_MODEL"),
        vlm=vlm or _envflag("SIFT_VLM"),
        timeout=timeout if timeout is not None else _envfloat("SIFT_LLM_TIMEOUT", 60.0),
    )
