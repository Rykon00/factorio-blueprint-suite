"""Parametric designs. Each module exposes ``Params``, ``build(protos, params)``."""

from __future__ import annotations

import dataclasses
from typing import Any

from . import lds_shuffle

DESIGNS = {
    "lds-shuffle": lds_shuffle,
}


def coerce_params(module: Any, overrides: dict[str, str]) -> Any:
    """Turn ``key=value`` strings into the design's ``Params`` dataclass."""
    params = module.Params()
    fields = {f.name: f for f in dataclasses.fields(params)}
    for key, raw in overrides.items():
        key = key.replace("-", "_")
        if key not in fields:
            raise SystemExit(f"unknown parameter {key!r}; known: {', '.join(sorted(fields))}")
        current = getattr(params, key)
        if isinstance(current, bool):
            value: Any = raw.lower() in ("1", "true", "yes", "on")
        elif isinstance(current, int):
            value = int(raw)
        elif isinstance(current, float):
            value = float(raw)
        elif isinstance(current, tuple) or key in ("keep_legendary",):
            value = tuple(x for x in raw.split(",") if x)
        elif key in ("foundries",) or current is None and "," in raw:
            value = [int(x) for x in raw.split(",")]
        elif current is None:
            value = int(raw) if raw.isdigit() else raw
        else:
            value = raw
        setattr(params, key, value)
    return params
