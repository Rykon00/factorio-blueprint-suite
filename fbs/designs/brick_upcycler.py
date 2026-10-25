"""Brick upcycler: normal stone bricks in, legendary stone bricks out (Vulcanus).

Loop: foundry casts concrete from stone bricks + molten iron + water
(``concrete-from-molten-iron``, bricks are the only item ingredient, 50 %
foundry productivity), a recycler turns concrete back into bricks
(0.125 brick + 0.025 iron ore per concrete). 37.5 % of the bricks come back
per pass with two quality rolls: 0.36 % of the input bricks end up legendary
with rare Q3, 1.0 % with legendary Q3. Every other stone loop keeps at most
25 % per pass (self recycling only one roll: 0.04 %).

Unit (5 x 15 tiles, repeated side by side)::

    active provider (bricks + iron ore)
    recycler (north) <- inserter <- foundry: concrete@q (quality modules) <- inserter <- requester(brick@q)
    molten iron main / water main below the foundries

Bricks travel by logistic robots (requested per tier, results pushed by the
active providers). Molten iron and water enter on the left edge of the cell.
Legendary concrete is recycled as well (``recycle_legendary_concrete``).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ..geometry import Direction
from ..grid import Cell, add_grid, snap_to_grid
from ..loops import LoopSpec, plan_loop
from ..model import Blueprint
from ..power import auto_power
from ..protos import Prototypes
from ..quality import QUALITIES
from .common import PAIR_SIZE, recycler_pair
from .em_upcycler import _module_quality_speed

N, E, S, W = Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST
TIERS = QUALITIES[:4]
LEG = QUALITIES[-1]
UNIT_W, UNIT_H = 5, 15


@dataclass
class Params:
    normal_foundries: int = 12
    foundries: list[int] | None = None
    foundry: str = "foundry"
    recycler: str = "recycler"
    inserter: str = "bulk-inserter"
    foundry_modules: str = "quality-module-3@rare"
    recycler_modules: str = "quality-module-3@rare"
    foundry_productivity: float = 0.5
    recycle_legendary_concrete: bool = True
    iron_ore_pairs: int = 1                  # self-recycling pairs for the iron ore by-product (0 = send it to the network)
    request_amount: int = 50
    buffer_storage: int = 6
    label: str = "Brick upcycler (fbs)"


def spec(protos: Prototypes, p: Params) -> LoopSpec:
    cast = protos.recipe("concrete-from-molten-iron")
    rec = protos.recipe("concrete-recycling")
    fq, fs = _module_quality_speed(protos, p.foundry_modules, protos.module_slots(p.foundry))
    rq, rs = _module_quality_speed(protos, p.recycler_modules, protos.module_slots(p.recycler))
    x_in = next(i["amount"] for i in cast["ingredients"] if i["name"] == "stone-brick")
    out = next(o["amount"] for o in cast["products"] if o["name"] == "concrete")
    brick = sum((o.get("amount") or 0) + (o.get("extra_count_fraction") or 0) for o in rec["products"] if o["name"] == "stone-brick")
    ore = sum((o.get("amount") or 0) + (o.get("extra_count_fraction") or 0) for o in rec["products"] if o["name"] == "iron-ore")
    return LoopSpec(
        x_per_craft=x_in,
        product_per_craft=out,
        productivity=min(cast.get("maximum_productivity") or 3, p.foundry_productivity),
        craft_quality=fq,
        crafts_per_s=protos.crafting_speed(p.foundry) * max(0.2, 1 + fs) / cast["energy"],
        x_per_product=brick,
        recycle_quality=rq,
        products_per_s_recycler=protos.crafting_speed(p.recycler) * max(0.2, 1 + rs) / rec["energy"],
        recycle_legendary_product=p.recycle_legendary_concrete,
        side_outputs={"iron-ore": ore},
    )


def unit(bp: Blueprint, x: int, y: int, tier: str, p: Params) -> None:
    fmods = [p.foundry_modules] * bp.protos.module_slots(p.foundry)
    rmods = [p.recycler_modules] * bp.protos.module_slots(p.recycler)
    bp.place("active-provider-chest", x + 3, y, tag="brick-out")
    bp.place(p.recycler, x + 3, y + 1, N, modules=rmods)                 # drops into the chest above
    bp.place("requester-chest", x + 1, y + 4, requests=[(f"stone-brick@{tier}", p.request_amount)], tag="brick-in")
    bp.place(p.inserter, x + 1, y + 5, N)
    bp.place(p.inserter, x + 3, y + 5, S)                                # concrete -> recycler
    bp.place(p.foundry, x, y + 6, N, recipe="concrete-from-molten-iron", recipe_quality=tier, modules=fmods, tag=f"foundry-{tier}")
    bp.place("pipe", x + 1, y + 11)                                      # molten iron (first fluid ingredient)
    bp.place("pipe-to-ground", x + 3, y + 11, N)                         # water dives under the iron main
    bp.place("pipe-to-ground", x + 3, y + 13, S)


def build(protos: Prototypes, p: Params | None = None) -> tuple[Blueprint, object]:
    p = p or Params()
    sp = spec(protos, p)
    pl = plan_loop(sp, p.normal_foundries, fixed=p.foundries)
    # recyclers: one per foundry is built in; check it is enough
    bp = Blueprint(protos, p.label)
    tiers = [t for t, n in zip(TIERS, pl.machines) for _ in range(n)]
    cells: list[Cell] = []
    rows: list[tuple[Cell, int, int, int]] = []   # (cell, y, x_start, x_end)
    per_row = (44 - 2) // UNIT_W
    i = 0
    ci = 0
    while i < len(tiers):
        cell = Cell(ci, 0)
        cells.append(cell)
        x0, y0, x1, y1 = cell.interior()
        for r in range(2):
            y = y0 + r * (UNIT_H + 1)
            xs = x0 + 1
            n = 0
            while i < len(tiers) and n < per_row:
                unit(bp, xs + n * UNIT_W, y, tiers[i], p)
                n += 1
                i += 1
            if n:
                rows.append((cell, y, x0, xs + n * UNIT_W - 1))
            if i >= len(tiers):
                break
        ci += 1
    for cell, y, xa, xb in rows:
        for xx in range(xa, xb + 1):
            if bp.free(xx, y + 12):
                bp.place("pipe", xx, y + 12)
            if bp.free(xx, y + 14):
                bp.place("pipe", xx, y + 14)
        bp.place("infinity-pipe", xa - 1, y + 12, tag="test", infinity_fluid=("molten-iron", 1500))
        bp.place("infinity-pipe", xa - 1, y + 14, tag="test", infinity_fluid=("water", 15))
    grid = add_grid(bp, cells, tag="grid")
    snap_to_grid(bp)
    # iron ore by-product: self-recycle it (legendary ore comes out, the rest is used up)
    sx0, _, sx1, sy1 = cells[0].interior()
    rmods = [p.recycler_modules] * protos.module_slots(p.recycler)
    for k in range(p.iron_ore_pairs):
        recycler_pair(bp, sx1 - PAIR_SIZE[0] + 1 - k * (PAIR_SIZE[0] + 1), sy1 - PAIR_SIZE[1] - 2, "iron-ore", rmods, p.inserter, tag="ore-pair")
    # storage in the bottom rows of the first cell
    spots = [(x, y) for y in range(sy1, sy1 - 6, -1) for x in range(sx0 + 1, sx1 + 1, 2) if bp.free(x, y)]
    wanted = [f"stone-brick@{LEG}"] * 2 + ([] if p.recycle_legendary_concrete else [f"concrete@{LEG}"]) + \
        ([f"iron-ore@{LEG}"] if p.iron_ore_pairs else [])
    si = 0
    for spec_ in wanted:
        bp.place("storage-chest", *spots[si], storage_filter=spec_, tag="legendary-out")
        si += 1
    for _ in range(p.buffer_storage):
        bp.place("storage-chest", *spots[si], tag="buffer")
        si += 1
    # test-only brick source right of the last cell
    tx = cells[-1].x0 + 53
    for j in range(3):
        bp.place("infinity-chest", tx, 10 + j, tag="test", infinity_items=[("stone-brick", 100)])
        bp.place(p.inserter, tx + 1, 10 + j, W, tag="test")
        bp.place("passive-provider-chest", tx + 2, 10 + j, tag="test")
    poles = [e for e in grid if e.name in ("medium-electric-pole", "big-electric-pole")]
    for c in cells:
        auto_power(bp, c.interior(), connect_to=poles)
    auto_power(bp, (tx - 3, 5, tx + 8, 20), connect_to=poles, tag="test")
    bp.description = (
        f"fbs brick upcycler for the City Block 2.0 grid ({len(cells)} cell(s)). Foundries per tier {pl.machines}. "
        f"Requests ~{pl.x_input_per_s:.1f} normal stone bricks/s from the logistic network; molten iron and water enter on "
        f"the left edge of each foundry row (upper main molten iron, lower main water). Planned: "
        f"{pl.legendary_x_per_h:.0f} legendary stone bricks/h."
    )
    bp.icons = [{"signal": {"name": "stone-brick", "quality": "legendary"}, "index": 1},
                {"signal": {"name": "concrete"}, "index": 2}]
    bp.meta = {"plan": asdict(pl), "params": asdict(p), "grid_cells": [(c.cx, c.cy) for c in cells]}
    return bp, pl
