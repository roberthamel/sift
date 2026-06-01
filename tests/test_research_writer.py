from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sift.research import writer
from sift.research.events import EventBus, EventType
from sift.llm_config import LLMConfig


@dataclass
class _Delta:
    content: str


@dataclass
class _Choice:
    delta: _Delta


@dataclass
class _Chunk:
    choices: list


class _AsyncStream:
    def __init__(self, pieces):
        self._pieces = list(pieces)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._pieces:
            raise StopAsyncIteration
        p = self._pieces.pop(0)
        return _Chunk([_Choice(_Delta(p))])


class _Completions:
    def __init__(self, pieces):
        self._pieces = pieces
        self.last_messages = None

    async def create(self, *, model, messages, stream=False):
        self.last_messages = messages
        return _AsyncStream(self._pieces)


class _Client:
    def __init__(self, comp):
        self.chat = type("X", (), {"completions": comp})()


def test_writer_revision_prompt_receives_existing_doc_and_query():
    sources = [{"url": "http://a/", "title": "A", "content": "new facts"}]
    comp = _Completions(["Merged content."])
    bus = EventBus()
    asyncio.run(
        writer.write(
            query="are there alternatives?",
            history=[("human", "tell me about X"), ("assistant", "X is...")],
            system=None,
            sources=sources,
            mode="balanced",
            llm_cfg=LLMConfig(host="x", api_key=None, model="m"),
            bus=bus,
            client=_Client(comp),
            existing_doc="## Old heading\n\nOld content.",
        )
    )
    bus.close()
    sys_msg = comp.last_messages[0]["content"]
    # Existing doc is in the system prompt
    assert "Old heading" in sys_msg
    assert "Old content" in sys_msg
    assert "existing_document" in sys_msg
    # Query is embedded in the system prompt too
    assert "are there alternatives" in sys_msg
    # History must NOT appear — revision mode strips it
    messages = comp.last_messages
    roles = [m["role"] for m in messages]
    assert "assistant" not in roles, "history should not be passed in revision mode"
    # Only system + one user message
    assert len(messages) == 2


def test_writer_first_turn_passes_history():
    sources = [{"url": "http://a/", "title": "A", "content": "facts"}]
    comp = _Completions(["Fresh answer."])
    bus = EventBus()
    asyncio.run(
        writer.write(
            query="what is X",
            history=[("human", "prior q"), ("assistant", "prior a")],
            system=None,
            sources=sources,
            mode="balanced",
            llm_cfg=LLMConfig(host="x", api_key=None, model="m"),
            bus=bus,
            client=_Client(comp),
        )
    )
    bus.close()
    sys_msg = comp.last_messages[0]["content"]
    # Standard writer prompt, not revision prompt
    assert "existing_document" not in sys_msg
    # History IS present in first-turn mode
    roles = [m["role"] for m in comp.last_messages]
    assert "assistant" in roles


def test_writer_streams_deltas_and_emits_sources():
    sources = [
        {"url": "http://a/", "title": "A", "content": "alpha facts"},
        {"url": "http://b/", "title": "B", "content": "beta facts"},
    ]
    comp = _Completions(["Hello ", "[1] world", " [2]."])
    bus = EventBus()
    out = asyncio.run(
        writer.write(
            query="q",
            history=None,
            system=None,
            sources=sources,
            mode="balanced",
            llm_cfg=LLMConfig(host="x", api_key=None, model="m"),
            bus=bus,
            client=_Client(comp),
        )
    )
    bus.close()

    async def drain():
        return [e async for e in bus.iterate()]

    events = asyncio.run(drain())
    deltas = [e.data["delta"] for e in events if e.type == EventType.RESPONSE]
    assert deltas == ["Hello ", "[1] world", " [2]."]
    assert out == "Hello [1] world [2]."
    src_evt = [e for e in events if e.type == EventType.SOURCES]
    assert len(src_evt) == 1
    assert src_evt[0].data["sources"] == sources
    # System prompt includes context block
    sys_msg = comp.last_messages[0]["content"]
    assert "[1]" in sys_msg and "[2]" in sys_msg
    assert "alpha facts" in sys_msg
