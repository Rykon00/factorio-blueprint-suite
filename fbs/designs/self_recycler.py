"""Self-recycler: legendary coal, stone, sulfur, ores, ... from items that only recycle into themselves.

For raw materials (coal, stone, sulfur, calcite, tungsten / uranium / holmium
ore, ...) Factorio 2.1 has no loop that keeps more than 25 % per pass: they only
recycle into themselves, with one quality roll. Expected legendary output per
input item: 0.04 % with rare Q3, 0.1 % with legendary Q3. Input that is already
better than normal helps a lot (big mining drills with quality modules), so the
requesters take every quality below legendary.

Each item gets recycler pairs (see ``common.recycler_pair``): items bounce
between two recyclers without robots, legendary items are pulled out into
passive providers and land in filtered storage chests.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ..grid import Cell, add_grid, snap_to_grid
from ..model import Blueprint
from ..power import auto_power
from ..protos import Prototypes
from ..quality import QUALITIES, roll
from .common import PAIR_SIZE, recycler_pair
from .em_upcycler import _module_quality_speed

LEG = QUALITIES[-1]


@dataclass
class Params:
    items: str = "coal,stone,sulfur,calcite"
    pairs_per_item: int = 2
    recycler_modules: str = "quality-module-3@rare"
    inserter: str = "bulk-inserter"
    request_amount: int = 100
    label: str = "Self-recycler (fbs)"


def legendary_fraction(q: float, start: int = 0, keep: float = 0.25) -> float:
    L = len(QUALITIES)
    stock = [0.0] * L
    stock[start] = 1.0
    leg = 0.0
    for _ in range(200):
        nxt = [0.0] * L
        for i in range(L - 1):
            if stock[i] <= 0:
                continue
            for k, pk in enumerate(roll(i, q, L)):
                nxt[k] += stock[i] * keep * pk
        leg += nxt[-1]
        nxt[-1] = 0.0
        stock = nxt
    return leg


def plan(protos: Prototypes, p: Params) -> dict:
    q, s = _module_quality_speed(protos, p.recycler_modules, protos.module_slots("recycler"))
    speed = protos.crafting_speed("recycler") * max(0.2, 1 + s)
    frac = legendary_fraction(q)
    out = {}
    for item in [i.strip() for i in p.items.split(",") if i.strip()]:
        rec = protos.recipe(f"{item}-recycling")
        per_recycler = speed / rec["energy"]
        # recycler A sees the input plus the 6.25 % that comes back from B
        max_input = per_recycler / (1 + 0.0625) * p.pairs_per_item
        out[item] = {"max_input_per_s": round(max_input, 2), "legendary_per_h_at_max": round(max_input * frac * 3600, 1)}
    return {"legendary_fraction": frac, "items": out}


def build(protos: Prototypes, p: Params | None = None) -> tuple[Blueprint, dict]:
    p = p or Params()
    pl = plan(protos, p)
    bp = Blueprint(protos, p.label)
    mods = [p.recycler_modules] * protos.module_slots("recycler")
    items = [i.strip() for i in p.items.split(",") if i.strip()]
    jobs = [it for it in items for _ in range(p.pairs_per_item)]
    pw, ph = PAIR_SIZE[0] + 1, PAIR_SIZE[1] + 1
    cells: list[Cell] = []
    ci = 0
    i = 0
    while i < len(jobs):
        cell = Cell(ci, 0)
        cells.append(cell)
        x0, y0, x1, y1 = cell.interior()
        cols = (x1 - x0 + 2) // pw
        rows = (y1 - y0 - 4) // ph          # keep 4 rows for storage
        for r in range(rows):
            for c in range(cols):
                if i >= len(jobs):
                    break
                recycler_pair(bp, x0 + c * pw, y0 + r * ph, jobs[i], mods, p.inserter, p.request_amount, tag=f"pair-{jobs[i]}")
                i += 1
        ci += 1
    grid = add_grid(bp, cells, tag="grid")
    snap_to_grid(bp)
    sx0, _, sx1, sy1 = cells[0].interior()
    spots = [(x, y) for y in range(sy1, sy1 - 4, -1) for x in range(sx0, sx1 + 1, 2) if bp.free(x, y)]
    for k, item in enumerate(items):
        bp.place("storage-chest", *spots[k], storage_filter=f"{item}@{LEG}", tag="legendary-out")
    # test-only sources
    tx = cells[-1].x0 + 53
    for k, item in enumerate(items):
        for j in range(2):
            y = 8 + k * 3 + j
            bp.place("infinity-chest", tx, y, tag="test", infinity_items=[(item, 100)])
            bp.place(p.inserter, tx + 1, y, "west", tag="test")
            bp.place("passive-provider-chest", tx + 2, y, tag="test")
    poles = [e for e in grid if e.name in ("medium-electric-pole", "big-electric-pole")]
    for c in cells:
        auto_power(bp, c.interior(), connect_to=poles)
    auto_power(bp, (tx - 3, 3, tx + 8, 8 + 3 * len(items) + 4), connect_to=poles, tag="test")
    lines = ", ".join(f"{k}: up to {v['max_input_per_s']}/s in -> ~{v['legendary_per_h_at_max']:.0f}/h" for k, v in pl["items"].items())
    bp.description = (f"fbs self-recycler for the City Block 2.0 grid ({len(cells)} cell(s)), {p.pairs_per_item} recycler pair(s) per item. "
                      f"Requests every quality below legendary from the logistic network. {lines}.")
    bp.icons = [{"signal": {"name": items[0], "quality": "legendary"}, "index": 1}, {"signal": {"name": "recycler"}, "index": 2}]
    bp.meta = {"plan": pl, "params": asdict(p), "grid_cells": [(c.cx, c.cy) for c in cells]}
    return bp, pl
