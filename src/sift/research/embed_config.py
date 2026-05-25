"""Embeddings configuration resolved from CLI flags + SIFT_EMBED_* env vars.

Parallel to `llm_config.LLMConfig` but for an OpenAI-compatible
`/v1/embeddings` endpoint. Required by `sift research` — the loop cannot
operate without embeddings for snippet ranking.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from ..llm_config import ConfigError


@dataclass(frozen=True)
class EmbedConfig:
    host: str | None
    api_key: str | None
    model: str | None
    timeout: float = 600.0

    def for_embed(self) -> "EmbedConfig":
        missing = []
        if not self.host:
            missing.append("--embed-base-url (or SIFT_EMBED_BASE_URL)")
        if not self.model:
            missing.append("--embed-model (or SIFT_EMBED_MODEL)")
        if missing:
            raise ConfigError(
                "Embeddings not configured: missing " + ", ".join(missing)
            )
        return self


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
    timeout: float | None = None,
) -> EmbedConfig:
    return EmbedConfig(
        host=host or os.environ.get("SIFT_EMBED_BASE_URL"),
        api_key=api_key or os.environ.get("SIFT_EMBED_API_KEY"),
        model=model or os.environ.get("SIFT_EMBED_MODEL"),
        timeout=timeout if timeout is not None else _envfloat("SIFT_EMBED_TIMEOUT", 600.0),
    )
