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


MAX_BATCH_SIZE = 100


async def embed_text(texts: list[str], cfg: EmbedConfig) -> list[list[float]]:
    """Return one embedding vector per input text, preserving order.

    Empty input returns an empty list without calling the endpoint.
    Texts are batched into chunks of at most 100 to stay within
    embedding server request limits.
    """
    if not texts:
        return []
    client = _client(cfg)

    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), MAX_BATCH_SIZE):
        batch = texts[i : i + MAX_BATCH_SIZE]
        resp = await client.embeddings.create(model=cfg.model, input=batch)
        items = sorted(resp.data, key=lambda d: getattr(d, "index", 0))
        all_embeddings.extend(list(item.embedding) for item in items)
    return all_embeddings
