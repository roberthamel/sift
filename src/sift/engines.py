"""Resolve user `--engines` and `--category` into a list of EngineRef.

All imports of `searx.*` happen lazily so callers can ensure `bootstrap()`
ran first.
"""
from __future__ import annotations


class UnknownEngineError(ValueError):
    pass


def resolve_engines(names: list[str] | None, category: str):
    from searx.engines import engines as engine_map
    from searx.search.models import EngineRef
    from searx import settings

    settings_by_name = {e["name"]: e for e in settings.get("engines", [])}

    if names:
        refs: list[EngineRef] = []
        for name in names:
            engine = engine_map.get(name)
            if engine is None:
                raise UnknownEngineError(name)
            cats = list(engine.categories) if hasattr(engine, "categories") else []
            chosen = category if category in cats else (cats[0] if cats else category)
            refs.append(EngineRef(name, chosen))
        return refs

    refs = []
    for name, engine in engine_map.items():
        cfg = settings_by_name.get(name, {})
        if cfg.get("disabled"):
            continue
        cats = list(getattr(engine, "categories", []))
        if category not in cats:
            continue
        refs.append(EngineRef(name, category))
    return refs
