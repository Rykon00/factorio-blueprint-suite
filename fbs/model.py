"""Blueprint builder.

Designs place entities by their top-left tile; the builder converts that to
the centre position Factorio expects, tracks occupied tiles (so overlapping
entities are caught while generating instead of when importing) and writes the
2.x blueprint JSON (modules as insert plans, logistic sections, filters,
circuit conditions, wires).

All field layouts were taken from blueprints exported by Factorio 2.1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import codec
from .geometry import Direction
from .protos import Prototypes

# Inventory ids used by blueprint insert plans for module slots.
MODULE_INVENTORY = {
    "assembling-machine": 4,
    "furnace": 4,
    "rocket-silo": 4,
    "beacon": 1,
    "mining-drill": 2,
    "lab": 3,
}

# Wire connector ids.
RED = 1
GREEN = 2
COMBINATOR_OUT_RED = 3
COMBINATOR_OUT_GREEN = 4
COPPER = 5


class OverlapError(ValueError):
    pass


def parse_item(spec: str | tuple[str, str]) -> tuple[str, str]:
    """``"quality-module-3@rare"`` -> ``("quality-module-3", "rare")``."""
    if isinstance(spec, tuple):
        return spec
    if "@" in spec:
        name, q = spec.split("@", 1)
        return name, q
    return spec, "normal"


def signal(name: str, kind: str = "item", quality: str | None = None) -> dict[str, Any]:
    s: dict[str, Any] = {"type": kind, "name": name}
    if quality:
        s["quality"] = quality
    return s


ANYTHING = {"type": "virtual", "name": "signal-anything"}
EVERYTHING = {"type": "virtual", "name": "signal-everything"}
EACH = {"type": "virtual", "name": "signal-each"}


@dataclass
class Entity:
    number: int
    name: str
    position: tuple[float, float]
    direction: int = Direction.NORTH
    data: dict[str, Any] = field(default_factory=dict)
    tiles: list[tuple[int, int]] = field(default_factory=list)
    tag: str | None = None

    def to_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {"entity_number": self.number, "name": self.name, "position": {"x": self.position[0], "y": self.position[1]}}
        if self.direction:
            d["direction"] = self.direction
        d.update(self.data)
        return d


class Blueprint:
    def __init__(self, protos: Prototypes, label: str = "fbs blueprint", description: str = ""):
        self.protos = protos
        self.label = label
        self.description = description
        self.entities: list[Entity] = []
        self.wires: list[list[int]] = []
        self.occupied: dict[tuple[int, int], int] = {}
        self.icons: list[dict[str, Any]] = []
        self.tiles: list[dict[str, Any]] = []
        self.meta: dict[str, Any] = {}

    # -- placement --------------------------------------------------------
    def place(self, name: str, x: int, y: int, direction: int | str = Direction.NORTH, *, tag: str | None = None,
              allow_overlap: bool = False, **settings: Any) -> Entity:
        """Place ``name`` with its top-left tile at (x, y)."""
        direction = Direction.parse(direction)
        w, h = self.protos.size(name, direction)
        cx, cy = x + w / 2, y + h / 2
        return self._add(name, (cx, cy), direction, w, h, tag, allow_overlap, settings)

    def place_center(self, name: str, cx: float, cy: float, direction: int | str = Direction.NORTH, *, tag: str | None = None,
                     allow_overlap: bool = False, **settings: Any) -> Entity:
        direction = Direction.parse(direction)
        w, h = self.protos.size(name, direction)
        return self._add(name, (cx, cy), direction, w, h, tag, allow_overlap, settings)

    def _add(self, name, pos, direction, w, h, tag, allow_overlap, settings) -> Entity:
        x0 = math.floor(pos[0] - w / 2 + 1e-6)
        y0 = math.floor(pos[1] - h / 2 + 1e-6)
        tiles = [(x0 + i, y0 + j) for i in range(w) for j in range(h)]
        if not allow_overlap:
            for t in tiles:
                if t in self.occupied:
                    other = self.entities[self.occupied[t] - 1]
                    raise OverlapError(f"{name} at {pos} overlaps {other.name} at {other.position} on tile {t}")
        ent = Entity(len(self.entities) + 1, name, pos, direction, {}, tiles, tag)
        self.entities.append(ent)
        for t in tiles:
            self.occupied[t] = ent.number
        self._apply(ent, settings)
        return ent

    def free(self, x: int, y: int) -> bool:
        return (x, y) not in self.occupied

    # -- settings ---------------------------------------------------------
    def _apply(self, ent: Entity, s: dict[str, Any]) -> None:
        d = ent.data
        etype = self.protos.entity(ent.name)["type"]
        if "quality" in s and s["quality"] not in (None, "normal"):
            d["quality"] = s.pop("quality")
        else:
            s.pop("quality", None)
        if "recipe" in s:
            d["recipe"] = s.pop("recipe")
            d["recipe_quality"] = s.pop("recipe_quality", "normal")
        if "modules" in s:
            mods = s.pop("modules")
            if mods:
                self.set_modules(ent, mods, etype)
        if "filters" in s:
            f = s.pop("filters")
            if f:
                d["filters"] = [self._filter(i, spec) for i, spec in enumerate(f, start=1)]
                d["use_filters"] = True
                d["filter_mode"] = s.pop("filter_mode", "whitelist")
        if "requests" in s:
            reqs = s.pop("requests")
            if reqs:
                filters = []
                for i, (spec, count) in enumerate(reqs, start=1):
                    n, q = parse_item(spec)
                    filters.append({"index": i, "name": n, "quality": q, "comparator": "=", "count": int(count)})
                d["request_filters"] = {"sections": [{"index": 1, "filters": filters}]}
        if "storage_filter" in s:
            spec = s.pop("storage_filter")
            if spec:
                n, q = parse_item(spec)
                d["request_filters"] = {"sections": [{"index": 1, "filters": [{"index": 1, "name": n, "quality": q, "comparator": "=", "count": 0}]}]}
        if "splitter_filter" in s:
            spec = s.pop("splitter_filter")
            if spec is not None:
                d["filter"] = self._splitter_filter(spec)
        for k in ("input_priority", "output_priority"):
            if k in s:
                d[k] = s.pop(k)
        if "circuit_condition" in s:
            cond = s.pop("circuit_condition")
            cb = d.setdefault("control_behavior", {})
            cb["circuit_enabled"] = True
            cb["circuit_condition"] = cond
        if "io_type" in s:  # underground belts / loaders
            d["type"] = s.pop("io_type")
        if "infinity_items" in s:
            items = s.pop("infinity_items")
            d["infinity_settings"] = {
                "remove_unfiltered_items": bool(s.pop("remove_unfiltered", False)),
                "filters": [
                    {"name": parse_item(spec)[0], **({"quality": parse_item(spec)[1]} if parse_item(spec)[1] != "normal" else {}),
                     "count": int(count), "mode": "at-least", "index": i}
                    for i, (spec, count) in enumerate(items, start=1)
                ],
            }
        elif s.pop("void", False):
            d["infinity_settings"] = {"remove_unfiltered_items": True, "filters": []}
        if "infinity_fluid" in s:
            name, temp = s.pop("infinity_fluid")
            d["infinity_settings"] = {"name": name, "percentage": 1, "temperature": temp, "mode": "at-least"}
        if "bar" in s:
            d["bar"] = int(s.pop("bar"))
        d.update(s)  # anything else is passed through verbatim

    @staticmethod
    def _filter(index: int, spec: str | dict) -> dict[str, Any]:
        if isinstance(spec, dict):
            return {"index": index, **spec}
        n, q = parse_item(spec)
        return {"index": index, "name": n, "quality": q, "comparator": "="}

    @staticmethod
    def _splitter_filter(spec: str | dict) -> dict[str, Any]:
        if isinstance(spec, dict):
            return spec
        if spec.startswith("@"):
            return {"quality": spec[1:], "comparator": "="}
        n, q = (spec.split("@", 1) + [None])[:2] if "@" in spec else (spec, None)
        out: dict[str, Any] = {"name": n}
        if q:
            out["quality"] = q
            out["comparator"] = "="
        return out

    def set_modules(self, ent: Entity, mods: Iterable[str | tuple[str, str]], etype: str | None = None) -> None:
        etype = etype or self.protos.entity(ent.name)["type"]
        inv = MODULE_INVENTORY.get(etype)
        if inv is None:
            raise ValueError(f"{ent.name} ({etype}) has no module inventory")
        slots = self.protos.module_slots(ent.name)
        mods = [parse_item(m) for m in mods]
        if len(mods) > slots:
            raise ValueError(f"{ent.name} has {slots} module slots, got {len(mods)} modules")
        grouped: dict[tuple[str, str], list[int]] = {}
        for i, m in enumerate(mods):
            grouped.setdefault(m, []).append(i)
        plans = []
        for (n, q), stacks in grouped.items():
            ident: dict[str, Any] = {"name": n}
            if q != "normal":
                ident["quality"] = q
            plans.append({"id": ident, "items": {"in_inventory": [{"inventory": inv, "stack": st} for st in stacks]}})
        ent.data["items"] = plans

    # -- wires ------------------------------------------------------------
    def wire(self, a: Entity, b: Entity, color: int = RED, a_connector: int | None = None, b_connector: int | None = None) -> None:
        self.wires.append([a.number, a_connector or color, b.number, b_connector or color])

    def copper(self, a: Entity, b: Entity) -> None:
        self.wires.append([a.number, COPPER, b.number, COPPER])

    # -- output -----------------------------------------------------------
    def bbox(self) -> tuple[int, int, int, int]:
        xs = [t[0] for t in self.occupied]
        ys = [t[1] for t in self.occupied]
        return min(xs), min(ys), max(xs) + 1, max(ys) + 1

    def to_dict(self, version: int | None = None) -> dict[str, Any]:
        bp: dict[str, Any] = {
            "item": "blueprint",
            "label": self.label,
            "entities": [e.to_json() for e in self.entities],
            "version": version or codec.version_to_int(2, 1, 0, 0),
        }
        if self.description:
            bp["description"] = self.description
        if self.wires:
            bp["wires"] = self.wires
        if self.tiles:
            bp["tiles"] = self.tiles
        bp["icons"] = self.icons or [{"signal": {"name": self.entities[0].name}, "index": 1}] if self.entities else []
        return {"blueprint": bp}

    def to_string(self, version: int | None = None) -> str:
        return codec.encode(self.to_dict(version))

    def count(self) -> dict[str, int]:
        c: dict[str, int] = {}
        for e in self.entities:
            c[e.name] = c.get(e.name, 0) + 1
        return dict(sorted(c.items(), key=lambda kv: -kv[1]))

    def tagged(self, tag: str) -> list[Entity]:
        return [e for e in self.entities if e.tag == tag]

    def without_tags(self, *tags: str) -> "Blueprint":
        """Copy of this blueprint without entities carrying one of ``tags`` (e.g. drop test sources)."""
        out = Blueprint(self.protos, self.label, self.description)
        mapping: dict[int, int] = {}
        for e in self.entities:
            if e.tag in tags:
                continue
            ne = Entity(len(out.entities) + 1, e.name, e.position, e.direction, dict(e.data), list(e.tiles), e.tag)
            out.entities.append(ne)
            for t in ne.tiles:
                out.occupied[t] = ne.number
            mapping[e.number] = ne.number
        for w in self.wires:
            if w[0] in mapping and w[2] in mapping:
                out.wires.append([mapping[w[0]], w[1], mapping[w[2]], w[3]])
        out.icons = list(self.icons)
        out.meta = dict(self.meta)
        return out
