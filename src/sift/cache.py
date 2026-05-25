"""On-disk cache for sift commands.

Layout: `$XDG_CACHE_HOME/sift/<prefix>/<sha256>.json` (defaults to
`~/.cache/sift/`). File mtime serves as the timestamp; TTL is compared in
seconds against `now - mtime`. `ttl=0` disables expiration.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def cache_root() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "sift"


def _prefix_dir(prefix: str) -> Path:
    d = cache_root() / prefix
    d.mkdir(parents=True, exist_ok=True)
    return d


def make_key(prefix: str, payload: Any) -> str:
    """Stable sha256 hex of a JSON-encoded payload.

    Callers should pass only fields that materially affect output. The prefix
    is included so the same payload under different commands hashes apart.
    """
    blob = json.dumps(
        {"prefix": prefix, "payload": payload},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _path(prefix: str, key: str) -> Path:
    return _prefix_dir(prefix) / f"{key}.json"


def get(prefix: str, key: str, ttl: float) -> Any | None:
    p = _path(prefix, key)
    if not p.exists():
        return None
    if ttl > 0:
        age = time.time() - p.stat().st_mtime
        if age > ttl:
            return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def set(prefix: str, key: str, value: Any) -> None:  # noqa: A001
    p = _path(prefix, key)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(p)


@dataclass
class Stats:
    entries: int
    bytes: int
    root: str


def stats() -> Stats:
    root = cache_root()
    if not root.exists():
        return Stats(entries=0, bytes=0, root=str(root))
    entries = 0
    total = 0
    for f in root.rglob("*.json"):
        try:
            total += f.stat().st_size
            entries += 1
        except OSError:
            pass
    return Stats(entries=entries, bytes=total, root=str(root))


def clear() -> int:
    """Delete all cache entries. Returns count removed."""
    root = cache_root()
    if not root.exists():
        return 0
    removed = 0
    for f in root.rglob("*.json"):
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass
    # Cleanup empty subdirs
    for d in sorted(
        (p for p in root.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        try:
            d.rmdir()
        except OSError:
            pass
    return removed
