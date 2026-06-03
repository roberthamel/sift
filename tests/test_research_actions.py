from __future__ import annotations

import asyncio
import math


from sift.research import actions, embeddings
from sift.research.embed_config import EmbedConfig
from sift.research.events import EventBus, EventType
from sift.llm_config import LLMConfig


def _ctx(monkeypatch, mode="balanced", embed_vectors=None, raw_results=None):
    bus = EventBus()
    cfg_embed = EmbedConfig(host="x", api_key=None, model="m")
    cfg_llm = LLMConfig(host="x", api_key=None, model="m")

    if embed_vectors is not None:
        async def _embed(texts, cfg):
            return [embed_vectors[t] for t in texts]

        monkeypatch.setattr(embeddings, "embed_text", _embed)
        monkeypatch.setattr(actions._embeddings, "embed_text", _embed)

    if raw_results is not None:
        async def _run_searxng(query, ctx):
            return raw_results.get(query, [])

        monkeypatch.setattr(actions, "_run_searxng", _run_searxng)

    return actions.ActionContext(
        mode=mode,
        llm_cfg=cfg_llm,
        embed_cfg=cfg_embed,
        bus=bus,
        query="what is X",
    )


def test_tool_schemas_speed_excludes_plan():
    names = [s["function"]["name"] for s in actions.tool_schemas("speed")]
    assert "plan" not in names
    assert {"search", "scrape_url", "done"}.issubset(names)


def test_tool_schemas_balanced_includes_plan():
    names = [s["function"]["name"] for s in actions.tool_schemas("balanced")]
    assert "plan" in names


def test_plan_emits_event(monkeypatch):
    ctx = _ctx(monkeypatch)
    out = asyncio.run(actions._action_plan({"plan": "go look"}, ctx))
    assert out.type == "plan_reasoning"
    assert out.data["plan"] == "go look"
    # drain bus
    ctx.bus.close()

    async def drain():
        return [e async for e in ctx.bus.iterate()]

    events = asyncio.run(drain())
    assert events[0].type == EventType.PLAN


def test_done_returns_done(monkeypatch):
    ctx = _ctx(monkeypatch)
    out = asyncio.run(actions._action_done({}, ctx))
    assert out.type == "done"


def test_execute_all_unknown_action(monkeypatch):
    ctx = _ctx(monkeypatch)
    tcs = [{"id": "1", "function": {"name": "nope", "arguments": "{}"}}]
    outs = asyncio.run(actions.execute_all(tcs, ctx))
    assert outs[0].type == "error"


def _unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else v


def test_search_filters_and_dedupes(monkeypatch):
    # Query embedding aligned with "a", "b"; "c" is orthogonal (sim 0 — drop).
    # "a2" is near-duplicate of "a" — should be deduped at > 0.75.
    q = _unit([1.0, 0.0, 0.0])
    a = _unit([0.9, 0.1, 0.0])  # sim to q ~ 0.99
    a2 = _unit([0.95, 0.05, 0.0])  # near-dup of a (sim > 0.75)
    b = _unit([0.7, 0.7, 0.0])  # sim ~ 0.70 > 0.5
    c = _unit([0.0, 0.0, 1.0])  # sim ~ 0
    embed_vectors = {
        "what is X": q,
        "snip-a": a,
        "snip-a2": a2,
        "snip-b": b,
        "snip-c": c,
    }
    raw = {
        "q1": [
            {"url": "http://a/", "title": "A", "content": "snip-a"},
            {"url": "http://a2/", "title": "A2", "content": "snip-a2"},
            {"url": "http://b/", "title": "B", "content": "snip-b"},
            {"url": "http://c/", "title": "C", "content": "snip-c"},
        ]
    }
    ctx = _ctx(monkeypatch, mode="balanced", embed_vectors=embed_vectors, raw_results=raw)
    out = asyncio.run(actions._action_search({"queries": ["q1"]}, ctx))
    urls = [r["url"] for r in out.data["results"]]
    # c is filtered (sim <= 0.5); exactly one of (a, a2) survives — the other
    # is deduped at > 0.75.
    assert "http://b/" in urls
    assert "http://c/" not in urls
    kept_a = {"http://a/", "http://a2/"}.intersection(urls)
    assert len(kept_a) == 1


def test_search_top_20(monkeypatch):
    q = _unit([1.0, 0.0])
    embed_vectors = {"what is X": q}
    raw_list = []
    for i in range(30):
        # Vectors slightly off-axis but well above 0.5 and not near-duplicates
        # (vary the second component noticeably).
        v = _unit([1.0, 0.01 * i + 0.01])
        embed_vectors[f"s{i}"] = v
        raw_list.append({"url": f"http://x/{i}", "title": f"T{i}", "content": f"s{i}"})
    raw = {"q1": raw_list}
    ctx = _ctx(monkeypatch, mode="balanced", embed_vectors=embed_vectors, raw_results=raw)
    out = asyncio.run(actions._action_search({"queries": ["q1"]}, ctx))
    # top-20 cap
    assert len(out.data["results"]) <= 20


def test_search_empty_queries(monkeypatch):
    ctx = _ctx(monkeypatch)
    out = asyncio.run(actions._action_search({"queries": []}, ctx))
    assert out.data["results"] == []


def test_search_caps_at_3_queries(monkeypatch):
    captured = []

    async def _run_searxng(query, ctx):
        captured.append(query)
        return []

    monkeypatch.setattr(actions, "_run_searxng", _run_searxng)
    ctx = _ctx(monkeypatch, mode="speed")
    asyncio.run(
        actions._action_search({"queries": ["a", "b", "c", "d", "e"]}, ctx)
    )
    assert captured == ["a", "b", "c"]
