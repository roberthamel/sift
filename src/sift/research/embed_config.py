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


def resolve(
    host: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float | None = None,
) -> EmbedConfig:
    """Resolve config: flag → SIFT_EMBED_* env var → config file → default."""
    from .. import config_file as _cf
    from ..llm_config import _resolve_float

    return EmbedConfig(
        host=host or os.environ.get("SIFT_EMBED_BASE_URL") or _cf.file_get("embed.base_url"),
        api_key=api_key
        or os.environ.get("SIFT_EMBED_API_KEY")
        or _cf.file_get("embed.api_key"),
        model=model or os.environ.get("SIFT_EMBED_MODEL") or _cf.file_get("embed.model"),
        timeout=(
            timeout
            if timeout is not None
            else _resolve_float("SIFT_EMBED_TIMEOUT", "embed.timeout", 600.0)
        ),
    )
