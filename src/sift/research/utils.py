"""Math + chunking helpers for the research loop."""
from __future__ import annotations

import math
from collections.abc import Sequence


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity between two equal-length vectors.

    Returns 0.0 if either vector has zero magnitude.
    """
    if len(a) != len(b):
        raise ValueError(f"vector length mismatch: {len(a)} vs {len(b)}")
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def split_text(text: str, size: int = 4000, overlap: int = 500) -> list[str]:
    """Character-window split with overlap.

    Matches Vane's quality-mode chunking call (`splitText(content, 4000, 500)`)
    at the call-site level, but uses a simpler character window instead of
    Vane's tiktoken-based segmenter. Empty input returns [].
    """
    if size <= 0:
        raise ValueError("size must be > 0")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must satisfy 0 <= overlap < size")
    if not text:
        return []
    if len(text) <= size:
        return [text]
    step = size - overlap
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = start + size
        chunks.append(text[start:end])
        if end >= n:
            break
        start += step
    return chunks
