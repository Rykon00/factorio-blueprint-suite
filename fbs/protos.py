"""Prototype data (entity sizes, fluid connections, recipes, qualities, modules).

The data comes from the real game: ``fbs protos`` loads the configured mod set
in a headless instance and dumps every prototype to JSON. Designs and the
renderer read sizes and connections from there instead of hard-coding them,
so modded entities (for example ``easier-space-age-foundry-normal``) just work.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .geometry import Direction, rotate_vec

DEFAULT_CACHE = Path(os.environ.get("FBS_PROTOTYPES", Path.home() / ".cache" / "fbs" / "prototypes.json"))
BUNDLED = Path(__file__).parent / "data" / "prototypes-vanilla.json"  # Factorio 2.1.23 + Space Age, no other mods


@dataclass
class Prototypes:
    data: dict[str, Any]

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "Prototypes":
        p = Path(path) if path else DEFAULT_CACHE
        if not p.exists():
            if path and Path(path) != DEFAULT_CACHE:
                raise FileNotFoundError(f"prototype dump {p} not found")
            # fall back to the bundled vanilla + Space Age dump
            p = BUNDLED
        return cls(json.loads(p.read_text(encoding="utf-8")))

    # -- entities -----------------------------------------------------------
    def entity(self, name: str) -> dict[str, Any]:
        try:
            return self.data["entities"][name]
        except KeyError:
            raise KeyError(f"unknown entity prototype {name!r}") from None

    def has_entity(self, name: str) -> bool:
        return name in self.data["entities"]

    def size(self, name: str, direction: int = Direction.NORTH) -> tuple[int, int]:
        e = self.entity(name)
        w, h = e["tile_width"], e["tile_height"]
        if direction in (Direction.EAST, Direction.WEST):
            return h, w
        return w, h

    def collision_box(self, name: str, direction: int = Direction.NORTH) -> tuple[float, float, float, float]:
        b = self.entity(name).get("collision_box") or [-0.4, -0.4, 0.4, 0.4]
        x1, y1 = rotate_vec((b[0], b[1]), direction)
        x2, y2 = rotate_vec((b[2], b[3]), direction)
        return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)

    def fluid_connections(self, name: str, direction: int = Direction.NORTH) -> list[dict[str, Any]]:
        """Fluid box connections rotated for ``direction``.

        Each entry has ``fluidbox`` (1-based), ``production_type``, ``position``
        (relative to the entity centre, the tile inside the entity),
        ``target`` (the tile outside the entity where a pipe has to be) and
        ``direction`` of the connection.
        """
        e = self.entity(name)
        out = []
        for i, fb in enumerate(e.get("fluidboxes") or [], start=1):
            for c in fb.get("connections") or []:
                if c.get("position") is None:
                    continue
                pos = rotate_vec(tuple(c["position"]), direction)
                d = (int(c["direction"]) + direction) % 16
                dx, dy = Direction.vector(d)
                out.append({
                    "fluidbox": i,
                    "production_type": fb.get("production_type"),
                    "position": pos,
                    "target": (pos[0] + dx, pos[1] + dy),
                    "direction": d,
                    "type": c.get("type"),
                    "flow": c.get("flow"),
                })
        return out

    def vector_to_place_result(self, name: str, direction: int = Direction.NORTH) -> tuple[float, float] | None:
        v = self.entity(name).get("vector_to_place_result")
        if not v:
            return None
        return rotate_vec(tuple(v), direction)

    def module_slots(self, name: str) -> int:
        return int(self.entity(name).get("module_slots") or 0)

    def crafting_speed(self, name: str) -> float:
        return float(self.entity(name).get("crafting_speed") or 1.0)

    # -- recipes / items ----------------------------------------------------
    def recipe(self, name: str) -> dict[str, Any]:
        return self.data["recipes"][name]

    def item(self, name: str) -> dict[str, Any]:
        return self.data["items"][name]

    def module_effects(self, name: str) -> dict[str, float]:
        return dict(self.item(name).get("module_effects") or {})

    def quality_chain(self) -> list[str]:
        q = self.data["qualities"]
        chain = ["normal"]
        while q.get(chain[-1], {}).get("next"):
            chain.append(q[chain[-1]]["next"])
        return chain

    def quality_level(self, name: str) -> int:
        return int(self.data["qualities"][name]["level"])

    def next_probability(self, name: str) -> float:
        return float(self.data["qualities"][name].get("next_probability") or 0.0)


@lru_cache(maxsize=4)
def load_cached(path: str | None = None) -> Prototypes:
    return Prototypes.load(path)
