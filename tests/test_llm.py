from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import openai
import pytest

from sift import llm
from sift.llm_config import LLMConfig


CFG = LLMConfig(host="http://x", api_key="-", model="m")


def _mk_response(text: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
    )


def _patched_client(return_value=None, side_effect=None):
    fake = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(return_value=return_value, side_effect=side_effect)
            )
        )
    )
    return patch.object(llm, "_client", return_value=fake), fake


def test_synthesize_happy():
    p, fake = _patched_client(return_value=_mk_response("a summary"))
    with p:
        text, err = asyncio.run(
            llm.synthesize_search_results(
                "q", [{"title": "T", "url": "u", "snippet": "s"}], CFG
            )
        )
    assert err is None
    assert text == "a summary"
    # user message includes citation context
    args = fake.chat.completions.create.await_args
    assert "Source 1" in args.kwargs["messages"][1]["content"]


def test_synthesize_empty_results():
    text, err = asyncio.run(llm.synthesize_search_results("q", [], CFG))
    assert err is None
    assert text == ""


def test_synthesize_timeout():
    err_exc = openai.APITimeoutError(request=None)
    p, _ = _patched_client(side_effect=err_exc)
    with p:
        text, err = asyncio.run(
            llm.synthesize_search_results("q", [{"url": "u"}], CFG)
        )
    assert text is None
    assert "timed out" in err


def test_synthesize_generic_failure():
    p, _ = _patched_client(side_effect=RuntimeError("boom"))
    with p:
        text, err = asyncio.run(
            llm.synthesize_search_results("q", [{"url": "u"}], CFG)
        )
    assert text is None
    assert "failed" in err and "boom" in err


def test_process_page_happy():
    p, _ = _patched_client(return_value=_mk_response("processed"))
    with p:
        text, err = asyncio.run(llm.process_page_content("body", CFG, "do thing"))
    assert err is None
    assert text == "processed"


def test_process_image_happy():
    p, fake = _patched_client(return_value=_mk_response("a cat"))
    with p:
        text, err = asyncio.run(llm.process_image_content(b"\x89PNG\r\n\x1a\n", "image/png", CFG))
    assert err is None
    assert text == "a cat"
    msg = fake.chat.completions.create.await_args.kwargs["messages"][1]
    parts = msg["content"]
    assert any(p_.get("type") == "image_url" for p_ in parts)


def test_process_image_failure():
    p, _ = _patched_client(side_effect=RuntimeError("nope"))
    with p:
        text, err = asyncio.run(llm.process_image_content(b"\x89PNG\r\n\x1a\n", "image/png", CFG))
    assert text is None
    assert "VLM processing failed" in err
