"""Configure environment + logging before any `import searx`.

`searx/__init__.py` runs `init_settings()` at import time, which also calls
`logging.basicConfig()`. To keep stdout clean and route everything to a file,
the file handler must be attached to the root logger *before* searx is imported.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from importlib import resources
from pathlib import Path

DEFAULT_SETTINGS = resources.files("sift") / "data" / "settings.yml"

RESOLVED_LOG_FILE: Path | None = None


def _default_log_file() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "sift" / "sift.log"


def _resolve_settings(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    env = os.environ.get("SEARXNG_SETTINGS_PATH")
    if env:
        return Path(env).expanduser().resolve()
    return Path(str(DEFAULT_SETTINGS)).resolve()


def bootstrap(
    settings_path: Path | None = None,
    log_file: Path | None = None,
    verbose: bool = False,
) -> Path:
    """Prepare env + logging, return the resolved log-file path.

    Must be called before any `import searx` (directly or transitively).
    """
    resolved_settings = _resolve_settings(settings_path)
    if not resolved_settings.is_file():
        raise FileNotFoundError(f"settings.yml not found: {resolved_settings}")

    if "searx" not in sys.modules:
        # Only meaningful before searx is imported: init_settings() reads it once.
        os.environ["SEARXNG_SETTINGS_PATH"] = str(resolved_settings)

    resolved_log = (log_file.expanduser().resolve() if log_file else _default_log_file())
    resolved_log.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    # Wipe any prior handlers so `basicConfig` becomes a no-op and nothing
    # writes to stderr.
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.handlers.RotatingFileHandler(
        resolved_log, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root.addHandler(handler)

    level = logging.DEBUG if verbose else logging.WARNING
    root.setLevel(level)
    logging.getLogger("searx").setLevel(level)
    logging.getLogger("sift").setLevel(level)
    logging.getLogger("crawl4ai").setLevel(level)

    global RESOLVED_LOG_FILE
    RESOLVED_LOG_FILE = resolved_log
    return resolved_log
