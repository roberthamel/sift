"""Image source resolution for `sift describe`.

Supports four input shapes:
1. Data URLs (`data:image/png;base64,...`)
2. HTTP(S) URLs
3. File paths
4. Raw base64 string

Format validation is via magic bytes, not the file extension — anything that
doesn't sniff as PNG/JPEG/GIF/WebP is rejected.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB

_MAGIC = {
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/gif": [b"GIF87a", b"GIF89a"],
    "image/webp": [],  # checked separately (RIFF....WEBP)
}


class ImageError(ValueError):
    """Raised when an image source cannot be resolved or has bad format."""


def detect_mime(data: bytes) -> str | None:
    for mime, sigs in _MAGIC.items():
        for sig in sigs:
            if data.startswith(sig):
                return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _check_size(data: bytes, max_bytes: int) -> None:
    if len(data) > max_bytes:
        raise ImageError(
            f"image exceeds max size: {len(data)} > {max_bytes} bytes"
        )


def _validate(data: bytes, max_bytes: int) -> tuple[bytes, str]:
    _check_size(data, max_bytes)
    mime = detect_mime(data)
    if mime is None:
        raise ImageError(
            "unrecognized image format (expected PNG/JPEG/GIF/WebP)"
        )
    return data, mime


_DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;]+);base64,(?P<b64>.+)$", re.DOTALL)


def _from_data_url(s: str, max_bytes: int) -> tuple[bytes, str]:
    m = _DATA_URL_RE.match(s)
    if not m:
        raise ImageError("malformed data URL")
    try:
        data = base64.b64decode(m.group("b64"), validate=True)
    except Exception as exc:
        raise ImageError(f"invalid base64 in data URL: {exc}") from exc
    return _validate(data, max_bytes)


def _from_http(s: str, max_bytes: int) -> tuple[bytes, str]:
    import urllib.request

    req = urllib.request.Request(s, headers={"User-Agent": "sift"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read(max_bytes + 1)
    except Exception as exc:
        raise ImageError(f"image fetch failed: {exc}") from exc
    return _validate(data, max_bytes)


def _from_file(s: str, max_bytes: int) -> tuple[bytes, str]:
    p = Path(s)
    if not p.is_file():
        raise ImageError(f"file not found: {s}")
    try:
        data = p.read_bytes()
    except Exception as exc:
        raise ImageError(f"could not read file: {exc}") from exc
    return _validate(data, max_bytes)


def _from_raw_base64(s: str, max_bytes: int) -> tuple[bytes, str]:
    # Strip whitespace and trailing junk
    cleaned = "".join(s.split())
    try:
        data = base64.b64decode(cleaned, validate=True)
    except Exception as exc:
        raise ImageError(f"could not decode base64: {exc}") from exc
    return _validate(data, max_bytes)


def resolve_image(source: str, max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[bytes, str]:
    """Return (image_bytes, mime_type) for any of the four input shapes."""
    if not source:
        raise ImageError("empty image source")
    if source.startswith("data:"):
        return _from_data_url(source, max_bytes)
    parsed = urlparse(source)
    if parsed.scheme in ("http", "https"):
        return _from_http(source, max_bytes)
    # Path vs raw base64: a path that exists wins; otherwise treat as base64.
    if Path(source).is_file():
        return _from_file(source, max_bytes)
    return _from_raw_base64(source, max_bytes)
