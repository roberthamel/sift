from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import pytest

from sift.research import actions as _actions
from sift.research import loop as _loop
from sift.research.embed_config import EmbedConfig
from sift.research.events import EventBus, EventType
from sift.llm_config import LLMConfig


@dataclass
class _Fn:
    name: str
    arguments: str


@dataclass
class _Tc:
    id: str
    function: _Fn


@dataclass
class _Msg:
    tool_calls: list

    @property
    def content(self):
        return ""


@dataclass
class _Choice:
    message: _Msg


@dataclass
class _Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class _Resp:
    choices: list
    usage: _Usage = None


class _ScriptedCompletions:
    def __init__(self, script: list[list[tuple[str, dict]]]):
        # script[i] = list of (name, args_dict) for iteration i
        self._script = list(script)
        self.calls = []

    async def create(self, *, model, messages, tools, tool_choice="auto"):
        self.calls.append({"messages": list(messages), "tools": tools})
        if not self._script:
            return _Resp([_Choice(_Msg(tool_calls=[]))], usage=_Usage())
        spec = self._script.pop(0)
        tcs = []
        for idx, (name, args) in enumerate(spec):
            tcs.append(_Tc(id=f"c{idx}", function=_Fn(name=name, arguments=json.dumps(args))))
        return _Resp([_Choice(_Msg(tool_calls=tcs))], usage=_Usage(1, 2, 3))


class _Client:
    def __init__(self, completions):
        self.chat = type("X", (), {"completions": completions})()


def test_event_bus_basic():
    """Sanity: EventBus already covered, but ensure loop uses it correctly."""
    from sift.research.events import Event

    async def main():
        bus = EventBus()
        bus.emit(Event(EventType.INIT))
        bus.close()
        return [e async for e in bus.iterate()]

    seen = asyncio.run(main())
    assert seen[0].type == EventType.INIT


def _stub_search(monkeypatch, results):
    async def _fake(args, ctx):
        return _actions.ActionOutput(
            type="search_results", data={"results": list(results)}
        )

    monkeypatch.setitem(
        _actions._REGISTRY, "search", (_fake, _actions._SEARCH_SCHEMA)
    )


def test_loop_terminates_on_done(monkeypatch):
    _stub_search(
        monkeypatch,
        [
            {"url": "http://a/", "title": "A", "content": "ca", "similarity": 0.9},
            {"url": "http://b/", "title": "B", "content": "cb", "similarity": 0.8},
        ],
    )
    completions = _ScriptedCompletions(
        [
            [("plan", {"plan": "do it"}), ("search", {"queries": ["q1", "q2"]})],
            [("done", {})],
        ]
    )
    bus = EventBus()
    res = asyncio.run(
        _loop.run(
            query="what",
            history=None,
            system=None,
            mode="balanced",
            llm_cfg=LLMConfig(host="x", api_key=None, model="m"),
            embed_cfg=EmbedConfig(host="x", api_key=None, model="m"),
            bus=bus,
            client=_Client(completions),
        )
    )
    bus.close()

    async def drain():
        return [e async for e in bus.iterate()]

    events = asyncio.run(drain())
    types = [e.type for e in events]
    assert EventType.INIT in types
    assert EventType.SOURCES in types
    assert EventType.DONE in types
    # Two iterations completed
    assert len(completions.calls) == 2
    # Sources contain a and b
    urls = sorted(s["url"] for s in res.sources)
    assert urls == ["http://a/", "http://b/"]
    # Usage rolled up
    assert res.usage["total"] == 6  # 3 per iteration, 2 iterations


def test_loop_terminates_on_iter_cap(monkeypatch):
    _stub_search(monkeypatch, [])
    # Never emits done — loop should stop at speed cap (2).
    completions = _ScriptedCompletions(
        [
            [("search", {"queries": ["a"]})],
            [("search", {"queries": ["b"]})],
            [("search", {"queries": ["c"]})],  # never reached
        ]
    )
    bus = EventBus()
    asyncio.run(
        _loop.run(
            query="q",
            history=None,
            system=None,
            mode="speed",
            llm_cfg=LLMConfig(host="x", api_key=None, model="m"),
            embed_cfg=EmbedConfig(host="x", api_key=None, model="m"),
            bus=bus,
            client=_Client(completions),
        )
    )
    assert len(completions.calls) == 2


def test_loop_terminates_on_zero_tool_calls(monkeypatch):
    _stub_search(monkeypatch, [])
    completions = _ScriptedCompletions([])  # always returns empty
    bus = EventBus()
    res = asyncio.run(
        _loop.run(
            query="q",
            history=None,
            system=None,
            mode="speed",
            llm_cfg=LLMConfig(host="x", api_key=None, model="m"),
            embed_cfg=EmbedConfig(host="x", api_key=None, model="m"),
            bus=bus,
            client=_Client(completions),
        )
    )
    assert res.actions == []
    assert len(completions.calls) == 1


def test_loop_history_threaded_into_first_message(monkeypatch):
    _stub_search(monkeypatch, [])
    completions = _ScriptedCompletions([[("done", {})]])
    bus = EventBus()
    asyncio.run(
        _loop.run(
            query="follow-up",
            history=[("human", "earlier"), ("assistant", "reply")],
            system="be terse",
            mode="speed",
            llm_cfg=LLMConfig(host="x", api_key=None, model="m"),
            embed_cfg=EmbedConfig(host="x", api_key=None, model="m"),
            bus=bus,
            client=_Client(completions),
        )
    )
    first_call = completions.calls[0]
    sys_msg = first_call["messages"][0]
    user_msg = first_call["messages"][1]
    assert "be terse" in sys_msg["content"]
    assert "earlier" in user_msg["content"]
    assert "follow-up" in user_msg["content"]


def test_loop_sources_dedupe_concatenates_content(monkeypatch):
    _stub_search(
        monkeypatch,
        [
            {"url": "http://a/", "title": "A", "content": "first", "similarity": 0.9},
        ],
    )
    completions = _ScriptedCompletions(
        [
            [("search", {"queries": ["q1"]})],
            [("done", {})],
        ]
    )
    # Now second iteration's search returns the same URL with new content
    iter_count = {"n": 0}

    async def _scripted(args, ctx):
        iter_count["n"] += 1
        if iter_count["n"] == 1:
            return _actions.ActionOutput(
                type="search_results",
                data={"results": [{"url": "http://a/", "title": "A", "content": "first", "similarity": 0.9}]},
            )
        return _actions.ActionOutput(
            type="search_results",
            data={"results": [{"url": "http://a/", "title": "A", "content": "second", "similarity": 0.8}]},
        )

    import sift.research.actions as A

    monkeypatch.setitem(A._REGISTRY, "search", (_scripted, A._SEARCH_SCHEMA))

    completions = _ScriptedCompletions(
        [
            [("search", {"queries": ["q1"]})],
            [("search", {"queries": ["q2"]})],
            [("done", {})],
        ]
    )

    bus = EventBus()
    res = asyncio.run(
        _loop.run(
            query="q",
            history=None,
            system=None,
            mode="balanced",
            llm_cfg=LLMConfig(host="x", api_key=None, model="m"),
            embed_cfg=EmbedConfig(host="x", api_key=None, model="m"),
            bus=bus,
            client=_Client(completions),
        )
    )
    assert len(res.sources) == 1
    assert "first" in res.sources[0]["content"]
    assert "second" in res.sources[0]["content"]
