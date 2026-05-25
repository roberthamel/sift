"""LLM/VLM operations parameterized on LLMConfig.

Ported from ~/workspace/websearch-mcp/src/websearch_mcp/llm.py. All functions
return (value, error) and never raise — exceptions are mapped to error strings
so callers can soft-fail (return JSON with `summary: null` and continue).

`openai` is imported lazily inside each function so that sift's non-LLM paths
do not pay the import cost.
"""
from __future__ import annotations

import base64
from typing import Any

from .llm_config import LLMConfig

DEFAULT_MAX_CONTENT_SIZE = 5 * 1024 * 1024  # 5 MB


def _truncate(content: str, max_bytes: int = DEFAULT_MAX_CONTENT_SIZE) -> tuple[str, bool]:
    encoded = content.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return content, False
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


def _client(cfg: LLMConfig):
    import openai

    return openai.AsyncOpenAI(base_url=cfg.host, api_key=cfg.api_key or "-")


def _classify(exc: BaseException, kind: str) -> str:
    import openai

    if isinstance(exc, openai.APITimeoutError):
        return f"{kind} processing timed out"
    if isinstance(exc, openai.RateLimitError):
        return f"{kind} rate limit exceeded"
    return f"{kind} processing failed: {exc}"


async def synthesize_search_results(
    query: str,
    results: list[dict[str, Any]],
    cfg: LLMConfig,
    *,
    per_source_max_bytes: int = DEFAULT_MAX_CONTENT_SIZE,
) -> tuple[str | None, str | None]:
    """Synthesize a list of search/fetch results into a cited summary.

    Each result is a dict with optional keys: title, url, snippet, content,
    error. Empty `results` returns ("", None).
    """
    if not results:
        return "", None

    system_prompt = (
        "You are a research assistant. Synthesize the following search results "
        "into a structured, comprehensive summary. Use inline source citations "
        "referencing the source URLs. Focus on answering the user's query with "
        "the most relevant and accurate information from the provided sources."
    )

    parts = [f"Query: {query}\n\nSearch Results:\n"]
    for i, r in enumerate(results, 1):
        parts.append(f"--- Source {i} ---")
        parts.append(f"Title: {r.get('title', 'N/A')}")
        parts.append(f"URL: {r.get('url', 'N/A')}")
        if r.get("snippet"):
            parts.append(f"Snippet: {r['snippet']}")
        content = r.get("content")
        if content:
            content, _ = _truncate(content, per_source_max_bytes)
            parts.append(f"Content:\n{content}")
        elif r.get("error"):
            parts.append(f"[Could not fetch: {r['error']}]")
        parts.append("")
    user_message = "\n".join(parts)

    try:
        client = _client(cfg)
        resp = await client.chat.completions.create(
            model=cfg.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            timeout=cfg.timeout,
        )
        return resp.choices[0].message.content, None
    except Exception as exc:  # noqa: BLE001 — intentional soft-fail boundary
        return None, _classify(exc, "LLM")


async def process_page_content(
    content: str,
    cfg: LLMConfig,
    prompt: str | None = None,
) -> tuple[str | None, str | None]:
    """Run an LLM pass over already-extracted page markdown."""
    system_prompt = (
        "You are a content analyst. Process the following web page content "
        "according to the user's instructions. Be thorough and accurate."
    )

    content, _ = _truncate(content)
    user_instruction = prompt or "Summarize the main content of this page."
    user_message = f"Instruction: {user_instruction}\n\nPage Content:\n{content}"

    try:
        client = _client(cfg)
        resp = await client.chat.completions.create(
            model=cfg.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            timeout=cfg.timeout,
        )
        return resp.choices[0].message.content, None
    except Exception as exc:  # noqa: BLE001
        return None, _classify(exc, "LLM")


def _encode_image(image_data: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(image_data).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


async def process_image_content(
    image_data: bytes,
    mime_type: str,
    cfg: LLMConfig,
    prompt: str | None = None,
) -> tuple[str | None, str | None]:
    """Describe an image via the VLM-asserted model."""
    system_prompt = (
        "You are a vision assistant. Describe the provided image in detail, "
        "focusing on key visual elements, context, and content."
    )
    user_prompt = prompt or "Describe this image in detail."

    try:
        client = _client(cfg)
        resp = await client.chat.completions.create(
            model=cfg.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": _encode_image(image_data, mime_type)},
                        },
                    ],
                },
            ],
            timeout=cfg.timeout,
        )
        return resp.choices[0].message.content, None
    except Exception as exc:  # noqa: BLE001
        return None, _classify(exc, "VLM")
