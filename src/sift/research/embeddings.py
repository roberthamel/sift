"""OpenAI-compatible embeddings client."""
from __future__ import annotations

from .embed_config import EmbedConfig


def _client(cfg: EmbedConfig):
    import openai

    return openai.AsyncOpenAI(
        base_url=cfg.host,
        api_key=cfg.api_key or "-",
        timeout=cfg.timeout,
    )


async def embed_text(texts: list[str], cfg: EmbedConfig) -> list[list[float]]:
    """Return one embedding vector per input text, preserving order.

    Empty input returns an empty list without calling the endpoint.
    """
    if not texts:
        return []
    client = _client(cfg)
    resp = await client.embeddings.create(model=cfg.model, input=texts)
    # OpenAI guarantees data ordering matches input; sort defensively by index
    # in case a local provider deviates.
    items = sorted(resp.data, key=lambda d: getattr(d, "index", 0))
    return [list(item.embedding) for item in items]
