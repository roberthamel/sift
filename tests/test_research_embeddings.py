from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from sift.research import embed_config, embeddings
from sift.llm_config import ConfigError


def test_flag_wins_over_env(monkeypatch):
    monkeypatch.setenv("SIFT_EMBED_BASE_URL", "http://env")
    monkeypatch.setenv("SIFT_EMBED_MODEL", "env-model")
    cfg = embed_config.resolve(host="http://flag", model="flag-model")
    assert cfg.host == "http://flag"
    assert cfg.model == "flag-model"


def test_env_fallback(monkeypatch):
    monkeypatch.setenv("SIFT_EMBED_BASE_URL", "http://env")
    monkeypatch.setenv("SIFT_EMBED_API_KEY", "envkey")
    monkeypatch.setenv("SIFT_EMBED_MODEL", "envmodel")
    cfg = embed_config.resolve()
    assert cfg.host == "http://env"
    assert cfg.api_key == "envkey"
    assert cfg.model == "envmodel"


def test_for_embed_missing(monkeypatch):
    monkeypatch.delenv("SIFT_EMBED_BASE_URL", raising=False)
    monkeypatch.delenv("SIFT_EMBED_MODEL", raising=False)
    cfg = embed_config.resolve()
    with pytest.raises(ConfigError) as ei:
        cfg.for_embed()
    assert "--embed-base-url" in str(ei.value)
    assert "--embed-model" in str(ei.value)


@dataclass
class _Datum:
    embedding: list[float]
    index: int


class _Resp:
    def __init__(self, data):
        self.data = data


class _FakeEmbeddings:
    def __init__(self, vectors):
        self._vectors = vectors
        self.calls = []

    async def create(self, *, model, input):
        self.calls.append({"model": model, "input": list(input)})
        return _Resp([_Datum(v, i) for i, v in enumerate(self._vectors[: len(input)])])


class _FakeClient:
    def __init__(self, vectors):
        self.embeddings = _FakeEmbeddings(vectors)


def test_embed_text_preserves_order(monkeypatch):
    vectors = [[1.0, 0.0], [0.0, 1.0], [0.7, 0.7]]
    client = _FakeClient(vectors)
    monkeypatch.setattr(embeddings, "_client", lambda cfg: client)
    cfg = embed_config.EmbedConfig(host="x", api_key=None, model="m")
    out = asyncio.run(embeddings.embed_text(["a", "b", "c"], cfg))
    assert out == vectors
    assert client.embeddings.calls[0]["model"] == "m"


def test_embed_text_empty():
    cfg = embed_config.EmbedConfig(host="x", api_key=None, model="m")
    assert asyncio.run(embeddings.embed_text([], cfg)) == []


def test_embed_text_sorts_out_of_order(monkeypatch):
    # Simulate a provider returning embeddings in wrong order; index field
    # restores input order.
    @dataclass
    class _D:
        embedding: list[float]
        index: int

    class _E:
        async def create(self, *, model, input):
            return _Resp([_D([0.0, 1.0], 1), _D([1.0, 0.0], 0)])

    class _C:
        embeddings = _E()

    monkeypatch.setattr(embeddings, "_client", lambda cfg: _C())
    cfg = embed_config.EmbedConfig(host="x", api_key=None, model="m")
    out = asyncio.run(embeddings.embed_text(["a", "b"], cfg))
    assert out == [[1.0, 0.0], [0.0, 1.0]]
