from __future__ import annotations

import math

import pytest

from sift.research import utils


def test_cosine_parallel():
    assert utils.cosine_similarity([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)


def test_cosine_orthogonal():
    assert utils.cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)


def test_cosine_opposite():
    assert utils.cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)


def test_cosine_zero_vector():
    assert utils.cosine_similarity([0, 0], [1, 1]) == 0.0


def test_cosine_length_mismatch():
    with pytest.raises(ValueError):
        utils.cosine_similarity([1, 2], [1, 2, 3])


def test_split_empty():
    assert utils.split_text("") == []


def test_split_short():
    assert utils.split_text("hello", size=100, overlap=10) == ["hello"]


def test_split_9000_default():
    text = "x" * 9000
    chunks = utils.split_text(text, size=4000, overlap=500)
    assert len(chunks) == 3
    assert chunks[0] == text[0:4000]
    assert chunks[1] == text[3500:7500]
    assert chunks[2] == text[7000:9000]
    assert len(chunks[2]) == 2000


def test_split_exact_boundary():
    text = "x" * 4000
    assert utils.split_text(text, size=4000, overlap=500) == [text]


def test_split_invalid():
    with pytest.raises(ValueError):
        utils.split_text("abc", size=0)
    with pytest.raises(ValueError):
        utils.split_text("abc", size=10, overlap=10)
