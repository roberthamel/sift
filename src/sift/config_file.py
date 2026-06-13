"""Persistent user configuration at ``$XDG_CONFIG_HOME/sift/config.yaml``.

This module owns everything file-related: locating the config file, parsing it,
updating a single key, and rendering the commented template written by
``sift config init``. It is intentionally independent of ``llm_config`` /
``embed_config`` (which import *this* module) to avoid a circular dependency.

Resolution precedence across the app is: CLI flag → environment variable →
config file → built-in default. This module only supplies the *file* layer plus
a ``resolve_value`` helper that folds env/file/default together for display.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger("sift")


class ConfigFileError(ValueError):
    """Raised when the config file exists but cannot be parsed."""


@dataclass(frozen=True)
class KeySpec:
    """A supported config key and how it maps to the rest of the app."""

    env: str  # the SIFT_* environment variable it mirrors
    desc: str  # short human description, used in the template and `config`
    default: str | None = None  # built-in default shown when nothing is set
    secret: bool = False  # mask the value when displaying


# Canonical registry of supported dotted keys. Single source of truth for
# validation (get/set), template generation, and the show command.
KEYS: dict[str, KeySpec] = {
    "llm.host": KeySpec("SIFT_LLM_HOST", "LLM endpoint base URL"),
    "llm.api_key": KeySpec("SIFT_LLM_APIKEY", "API key for the LLM endpoint", secret=True),
    "llm.model": KeySpec("SIFT_LLM_MODEL", "LLM model identifier"),
    "llm.vlm": KeySpec(
        "SIFT_VLM", "Assert the model supports vision (true/false)", default="false"
    ),
    "llm.timeout": KeySpec(
        "SIFT_LLM_TIMEOUT", "LLM request timeout in seconds", default="3600.0"
    ),
    "embed.base_url": KeySpec("SIFT_EMBED_BASE_URL", "Embeddings endpoint base URL"),
    "embed.api_key": KeySpec(
        "SIFT_EMBED_API_KEY", "API key for the embeddings endpoint", secret=True
    ),
    "embed.model": KeySpec("SIFT_EMBED_MODEL", "Embeddings model identifier"),
    "embed.timeout": KeySpec(
        "SIFT_EMBED_TIMEOUT", "Embeddings request timeout in seconds", default="600.0"
    ),
    "storage.base_dir": KeySpec(
        "SIFT_STORAGE_BASE_DIR", "Base directory for research documents", default="~/.sift"
    ),
}


def config_path() -> Path:
    """Resolve ``$XDG_CONFIG_HOME/sift/config.yaml`` (default ``~/.config``)."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "sift" / "config.yaml"


# Cache keyed by path -> (mtime_ns, parsed dict). Auto-invalidates when the
# file changes on disk, so a long-running process picks up out-of-band edits
# and tests with distinct tmp files never see each other's data.
_cache: dict[str, tuple[int, dict]] = {}


def _parse(path: Path) -> dict:
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return {}
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigFileError(f"invalid YAML in {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigFileError(f"{path}: expected a mapping at the top level")
    known_sections = {k.split(".", 1)[0] for k in KEYS}
    for section in data:
        if section not in known_sections:
            log.warning("ignoring unknown config section %r in %s", section, path)
    return data


def load() -> dict:
    """Return the parsed config file, or ``{}`` when it does not exist.

    Raises :class:`ConfigFileError` when the file is present but malformed.
    """
    path = config_path()
    try:
        mtime = path.stat().st_mtime_ns
    except FileNotFoundError:
        return {}
    cached = _cache.get(str(path))
    if cached is not None and cached[0] == mtime:
        return cached[1]
    data = _parse(path)
    _cache[str(path)] = (mtime, data)
    return data


def file_get(dotted_key: str) -> str | None:
    """Return the file-level value for ``section.key``, or ``None``.

    Used by ``llm_config`` / ``embed_config`` as the file fallback layer.
    """
    section, _, leaf = dotted_key.partition(".")
    data = load()
    sub = data.get(section)
    if not isinstance(sub, dict):
        return None
    val = sub.get(leaf)
    if val is None:
        return None
    return str(val)


# Backwards-friendly alias matching the task wording.
def get(dotted_key: str) -> str | None:
    """File-level value for ``dotted_key`` (see :func:`file_get`)."""
    return file_get(dotted_key)


def set(dotted_key: str, value: str) -> Path:  # noqa: A001 - mirrors the CLI verb
    """Update a single key in the config file, preserving other values.

    Creates the file (and parent directory) when absent. Raises ``KeyError``
    for keys not present in :data:`KEYS`.
    """
    if dotted_key not in KEYS:
        raise KeyError(dotted_key)
    path = config_path()
    data = _parse(path)  # fresh read, not the cache, so we never lose edits
    section, _, leaf = dotted_key.partition(".")
    sub = data.get(section)
    if not isinstance(sub, dict):
        sub = {}
        data[section] = sub
    sub[leaf] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, default_flow_style=False, sort_keys=True))
    _cache.pop(str(path), None)
    return path


def unset(dotted_key: str) -> Path:
    """Remove a single key from the config file, pruning emptied sections.

    A no-op (still returns the path) when the key, section, or file is absent,
    so ``sift --config llm.model=`` is idempotent. Raises ``KeyError`` for keys
    not present in :data:`KEYS`.
    """
    if dotted_key not in KEYS:
        raise KeyError(dotted_key)
    path = config_path()
    data = _parse(path)  # fresh read, not the cache, so we never lose edits
    section, _, leaf = dotted_key.partition(".")
    sub = data.get(section)
    if isinstance(sub, dict) and leaf in sub:
        del sub[leaf]
        if not sub:  # last key in the section → drop the now-empty section
            del data[section]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(data, default_flow_style=False, sort_keys=True)
            if data
            else ""
        )
        _cache.pop(str(path), None)
    return path


def resolve_value(dotted_key: str) -> tuple[str | None, str]:
    """Resolve ``dotted_key`` across env → file → default.

    Returns ``(value, source)`` where source is ``"env"``, ``"file"``,
    ``"default"``, or ``"unset"``. CLI flags are not visible here; the show /
    get commands have no flags of their own.
    """
    spec = KEYS[dotted_key]
    env = os.environ.get(spec.env)
    if env not in (None, ""):
        return env, "env"
    fv = file_get(dotted_key)
    if fv not in (None, ""):
        return fv, "file"
    if spec.default is not None:
        return spec.default, "default"
    return None, "unset"


def resolve_base_dir() -> Path:
    """Return the effective research base directory, with ``~`` expanded.

    Resolution follows the standard precedence: CLI flag (not visible here) →
    environment variable → config file → built-in default (``~/.sift``).
    """
    value, _ = resolve_value("storage.base_dir")
    if value is None:
        value = "~/.sift"
    return Path(value).expanduser()


def mask(value: str | None) -> str:
    """Mask a secret for display, keeping only the last 4 characters."""
    if not value:
        return "(unset)"
    if len(value) <= 4:
        return "****"
    return "*" * (len(value) - 4) + value[-4:]


def template_text() -> str:
    """Render the commented YAML template written by ``sift config init``."""
    lines = [
        "# sift configuration",
        "#",
        "# Precedence (highest first): CLI flag > environment variable >",
        "# this file > built-in default. Values set via SIFT_* env vars will",
        "# override anything written here.",
        "#",
        "# Uncomment and edit the keys you want to persist.",
        "",
    ]
    last_section = None
    for key, spec in KEYS.items():
        section, _, leaf = key.partition(".")
        if section != last_section:
            if last_section is not None:
                lines.append("")
            lines.append(f"{section}:")
            last_section = section
        suffix = f" (env: {spec.env})"
        lines.append(f"  # {spec.desc}{suffix}")
        placeholder = spec.default if spec.default is not None else ""
        lines.append(f"  # {leaf}: {placeholder}")
    return "\n".join(lines) + "\n"
