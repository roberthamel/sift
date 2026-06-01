"""Automatic persistence for research documents under .ai/research/<scope>/."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..llm_config import LLMConfig

log = logging.getLogger("sift.research")
_MAX_SLUG_LEN = 60


def _slugify(s: str) -> str:
    """Convert an arbitrary string to a safe kebab-case slug.

    Strips path-traversal sequences and non-alphanumeric chars, lowercases,
    collapses runs of separators to a single hyphen, and caps the length.
    """
    s = s.replace("..", "").replace("/", "-").replace("\\", "-")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s[:_MAX_SLUG_LEN].rstrip("-") or "research"


# Common question-framing words that carry no topical information.
_FILLER = frozenset({
    "a", "an", "the", "i", "me", "my", "our", "your",
    "give", "get", "show", "tell", "help", "explain", "describe",
    "please", "can", "could", "would", "should", "will",
    "do", "does", "did", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had",
    "how", "what", "when", "where", "who", "which", "why",
    "intro", "introduction", "overview", "guide", "tutorial", "summary",
    "about", "on", "in", "of", "to", "for", "with", "by", "from",
    "into", "up", "out", "some", "any", "and", "or", "but", "so",
})


def _content_words(query: str) -> list[str]:
    """Return the substantive words from a query, filtering out filler."""
    words = re.findall(r"[a-zA-Z0-9]+", query.lower())
    meaningful = [w for w in words if w not in _FILLER]
    return meaningful if meaningful else words


def _fallback_slug(query: str) -> tuple[str, str]:
    words = _content_words(query)
    scope = _slugify(" ".join(words[:2])) or "research"
    slug = _slugify(" ".join(words[:6])) or "research"
    return scope, slug


_PICK_SYSTEM = """\
You organise research notes into folders and files. Given a research question, \
decide on a concise topical scope (the subject area) and a descriptive filename \
(the specific topic). Think carefully: don't just copy words from the question — \
reflect the underlying subject matter.

Rules:
- scope: 1-3 words, the broad subject area (e.g. "golang", "auth", "react", "networking")
- filename: 2-5 words, the specific topic of this research (e.g. "viper-config-library", \
"jwt-refresh-flow", "react-hooks-patterns")
- Both in kebab-case, all lowercase.
- Return ONLY raw JSON, no markdown fences: {"scope": "...", "filename": "..."}
"""

_PICK_EXAMPLES = [
    ("Give me an introduction on how to use Viper in a Golang CLI",
     '{"scope": "golang", "filename": "viper-config-library"}'),
    ("What are best practices for JWT refresh tokens?",
     '{"scope": "auth", "filename": "jwt-refresh-best-practices"}'),
    ("Explain React hooks and when to use useEffect",
     '{"scope": "react", "filename": "hooks-and-useeffect"}'),
]


async def pick_location(
    query: str,
    llm_cfg: "LLMConfig",
    client=None,
) -> tuple[str, str]:
    """Ask the LLM to choose a (scope, slug) pair for the research document.

    Returns (scope, slug) where both are safe kebab-case strings. Falls back
    to a content-word-based slug (filtering question filler) if the LLM call
    fails.
    """
    import openai

    if client is None:
        client = openai.AsyncOpenAI(
            base_url=llm_cfg.host,
            api_key=llm_cfg.api_key or "-",
            timeout=llm_cfg.timeout,
        )

    messages: list[dict] = [{"role": "system", "content": _PICK_SYSTEM}]
    for q, a in _PICK_EXAMPLES:
        messages.append({"role": "user", "content": q})
        messages.append({"role": "assistant", "content": a})
    messages.append({"role": "user", "content": query})

    try:
        resp = await client.chat.completions.create(
            model=llm_cfg.model,
            messages=messages,
            max_tokens=80,
        )
        raw = (resp.choices[0].message.content or "").strip()
        m = re.search(r"\{[^}]+\}", raw, re.DOTALL)
        if m:
            data = json.loads(m.group())
            scope = _slugify(str(data.get("scope", "")))
            slug = _slugify(str(data.get("filename", "")))
            if scope and slug:
                return scope, slug
    except Exception:  # noqa: BLE001
        log.debug("pick_location LLM call failed, using content-word fallback", exc_info=True)

    return _fallback_slug(query)


def resolve_path(
    scope: str,
    slug: str,
    base: Path = Path(".ai/research"),
    continuing: Path | None = None,
) -> Path:
    """Build the save path, appending a numeric suffix if the file already exists.

    If the computed path is the ``continuing`` file (i.e. we are editing an
    existing document in place), it is returned without a suffix even if it
    exists on disk.
    """
    target = base / scope / f"{slug}.md"
    if continuing is not None and target.resolve() == continuing.resolve():
        return target
    if not target.exists():
        return target
    for n in range(2, 1000):
        candidate = base / scope / f"{slug}-{n}.md"
        if continuing is not None and candidate.resolve() == continuing.resolve():
            return candidate
        if not candidate.exists():
            return candidate
    return base / scope / f"{slug}-1000.md"


def save(path: Path, content: str) -> None:
    """Write content to path, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------

_FM_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _quote_yaml_scalar(s: str) -> str:
    if any(c in s for c in '"\':#{}[]|>') or not s:
        return f'"{s}"'
    return s


def strip_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML-like frontmatter from the top of text.

    Returns ``(meta_dict, body)`` where body has leading blank lines stripped.
    Handles scalar values and simple sequence values (``- item`` blocks).
    If no frontmatter block is present, returns ``({}, text)`` unchanged.
    """
    if not text.startswith("---\n"):
        return {}, text
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    meta: dict = {}
    lines = m.group(1).splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if not v:
                # Possibly a sequence — collect following "  - item" lines.
                items = []
                while i + 1 < len(lines) and lines[i + 1].startswith("  - "):
                    i += 1
                    items.append(lines[i][4:].strip().strip('"').strip("'"))
                meta[k] = items if items else v
            else:
                try:
                    meta[k] = int(v) if "." not in v else float(v)
                except ValueError:
                    meta[k] = v
        i += 1
    return meta, text[m.end():].lstrip("\n")


def make_frontmatter(meta: dict) -> str:
    """Serialise a flat dict to a YAML frontmatter block (``---\\n...\\n---\\n\\n``).

    Values that are lists are emitted as YAML sequences.
    """
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {_quote_yaml_scalar(str(item))}")
        else:
            lines.append(f"{k}: {_quote_yaml_scalar(str(v))}")
    lines.append("---")
    lines.append("")  # blank line between frontmatter and body
    return "\n".join(lines) + "\n"
