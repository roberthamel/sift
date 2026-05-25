from __future__ import annotations

import base64
import io
from pathlib import Path
from unittest.mock import patch

import pytest

from sift import images


# 1x1 PNG (red pixel)
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108020000"
    "00907753de0000000c4944415478da6364f80f0000010001005bba"
    "13050000000049454e44ae426082"
)


def test_detect_mime_png():
    assert images.detect_mime(TINY_PNG) == "image/png"


def test_detect_mime_jpeg():
    assert images.detect_mime(b"\xff\xd8\xff\xe0rest") == "image/jpeg"


def test_detect_mime_unknown():
    assert images.detect_mime(b"<html>not an image") is None


def test_resolve_data_url():
    b64 = base64.b64encode(TINY_PNG).decode()
    src = f"data:image/png;base64,{b64}"
    data, mime = images.resolve_image(src)
    assert data == TINY_PNG
    assert mime == "image/png"


def test_resolve_file(tmp_path: Path):
    p = tmp_path / "x.png"
    p.write_bytes(TINY_PNG)
    data, mime = images.resolve_image(str(p))
    assert data == TINY_PNG
    assert mime == "image/png"


def test_resolve_raw_base64():
    b64 = base64.b64encode(TINY_PNG).decode()
    data, mime = images.resolve_image(b64)
    assert data == TINY_PNG
    assert mime == "image/png"


def test_resolve_http():
    class FakeResp:
        def __init__(self, payload: bytes):
            self._buf = io.BytesIO(payload)

        def read(self, n: int) -> bytes:
            return self._buf.read(n)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch("urllib.request.urlopen", return_value=FakeResp(TINY_PNG)):
        data, mime = images.resolve_image("http://example/x.png")
    assert data == TINY_PNG
    assert mime == "image/png"


def test_magic_byte_rejection(tmp_path: Path):
    p = tmp_path / "x.png"
    p.write_bytes(b"<html>not an image")
    with pytest.raises(images.ImageError):
        images.resolve_image(str(p))


def test_max_bytes(tmp_path: Path):
    p = tmp_path / "x.png"
    p.write_bytes(TINY_PNG)
    with pytest.raises(images.ImageError) as ei:
        images.resolve_image(str(p), max_bytes=10)
    assert "exceeds max size" in str(ei.value)
