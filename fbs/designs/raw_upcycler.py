"""Raw-material upcycler: legendary stone, coal (+ iron), sulfur, calcite in one grid cell.

Best loops found by searching every recipe (rare Q3, legendary per input item):

* stone  -> stone furnace (assembler) -> recycler      0.12 %   (self-recycling 0.016 %)
* coal   -> grenade with iron (assembler) -> recycler   0.12 %   (gives legendary iron too)
* sulfur, calcite, ores: they only recycle into themselves  0.016 %

The assembler loops use one unit per machine (3 x 11)::

    requester(ingredients@q) -> assembler: recipe@q (quality modules) -> recycler -> active provider

Grenade recycling returns coal and iron in the recipe ratio with the same
quality, so the co-ingredient iron keeps up on every tier by itself. Items
that only self-recycle use robot-free recycler pairs (``common.recycler_pair``).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from ..geometry import Direction
from ..grid import Cell, add_grid, snap_to_grid
from ..loops import LoopSpec, plan_loop
from ..model import Blueprint
from ..power import auto_power
from ..protos import Prototypes
from ..quality import QUALITIES
from .common import PAIR_SIZE, input_station, recycler_pair
from .em_upcycler import _module_quality_speed
from .self_recycler import legendary_fraction

N, E, S, W = Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST
TIERS = QUALITIES[:4]
LEG = QUALITIES[-1]
UNIT_W, UNIT_H = 3, 11


@dataclass
class Params:
    stone_machines: int = 4                  # normal-tier assemblers for the stone-furnace loop
    coal_machines: int = 8                   # normal-tier assemblers for the grenade loop
    self_items: str = "sulfur,calcite"
    pairs_per_item: int = 1
    assembler: str = "assembling-machine-3"
    recycler: str = "recycler"
    inserter: str = "bulk-inserter"
    assembler_modules: str = "quality-module-3@rare"
    recycler_modules: str = "quality-module-3@rare"
    label: str = "Raw upcycler (fbs)"


LOOPS = {
    # name: (recipe, main item, products recycled back per product)
    "stone": ("stone-furnace", "stone"),
    "coal": ("grenade", "coal"),
}


def _recycle_amount(protos: Prototypes, product: str, item: str) -> float:
    rec = protos.recipe(f"{product}-recycling")
    return sum((o.get("amount") or 0) + (o.get("extra_count_fraction") or 0) for o in rec["products"] if o["name"] == item)


def loop_spec(protos: Prototypes, p: Params, recipe: str, item: str) -> tuple[LoopSpec, dict[str, float]]:
    r = protos.recipe(recipe)
    aq, as_ = _module_quality_speed(protos, p.assembler_modules, protos.module_slots(p.assembler))
    rq, rs = _module_quality_speed(protos, p.recycler_modules, protos.module_slots(p.recycler))
    x_in = next(i["amount"] for i in r["ingredients"] if i["name"] == item)
    co = {i["name"]: i["amount"] / x_in for i in r["ingredients"] if i["type"] == "item" and i["name"] != item}
    product = r["products"][0]["name"]
    spec = LoopSpec(
        x_per_craft=x_in,
        product_per_craft=r["products"][0]["amount"],
        productivity=0.0,
        craft_quality=aq,
        crafts_per_s=protos.crafting_speed(p.assembler) * max(0.2, 1 + as_) / r["energy"],
        x_per_product=_recycle_amount(protos, product, item),
        recycle_quality=rq,
        products_per_s_recycler=protos.crafting_speed(p.recycler) * max(0.2, 1 + rs) / protos.recipe(f"{product}-recycling")["energy"],
    )
    return spec, co


def plan(protos: Prototypes, p: Params) -> dict:
    out = {}
    for name, (recipe, item) in LOOPS.items():
        n = p.stone_machines if name == "stone" else p.coal_machines
        if n <= 0:
            continue
        spec, co = loop_spec(protos, p, recipe, item)
        lp = plan_loop(spec, n)
        entry = {"recipe": recipe, "machines": lp.machines, f"{item}_input_per_s": lp.x_input_per_s,
                 f"legendary_{item}_per_h": lp.legendary_x_per_h}
        for c, ratio in co.items():
            entry[f"{c}_input_per_s"] = round(lp.x_input_per_s * ratio, 3)
            entry[f"legendary_{c}_per_h"] = round(lp.legendary_x_per_h * ratio, 1)
        out[name] = entry
    q, s = _module_quality_speed(protos, p.recycler_modules, protos.module_slots(p.recycler))
    frac = legendary_fraction(q)
    speed = protos.crafting_speed(p.recycler) * max(0.2, 1 + s)
    for item in [i.strip() for i in p.self_items.split(",") if i.strip()]:
        per = speed / protos.recipe(f"{item}-recycling")["energy"] / 1.0625 * p.pairs_per_item
        out[item] = {"pairs": p.pairs_per_item, f"{item}_input_per_s_max": round(per, 2), f"legendary_{item}_per_h_at_max": round(per * frac * 3600, 1)}
    return out


def request_amounts(protos: Prototypes, p: Params, recipe: str, buffer_s: float = 30.0) -> dict[str, int]:
    """Requests cap how many items robots carry at once, so size them to ~30 s of consumption."""
    r = protos.recipe(recipe)
    _, as_ = _module_quality_speed(protos, p.assembler_modules, protos.module_slots(p.assembler))
    crafts = protos.crafting_speed(p.assembler) * max(0.2, 1 + as_) / r["energy"]
    return {i["name"]: max(20, int(math.ceil(i["amount"] * crafts * buffer_s / 10.0) * 10)) for i in r["ingredients"] if i["type"] == "item"}


def unit(bp: Blueprint, x: int, y: int, recipe: str, tier: str, ingredients: list[str], p: Params, belt_fed: bool = False) -> None:
    """Assembler + recycler. ``belt_fed`` units take their input from the belt in row ``y``."""
    amods = [p.assembler_modules] * bp.protos.module_slots(p.assembler)
    rmods = [p.recycler_modules] * bp.protos.module_slots(p.recycler)
    if belt_fed:
        # main item from the belt; returned items and co-ingredients by robot through the side requester
        bp.place(p.inserter, x + 1, y + 1, N, filters=[f"{ingredients[0]}@{tier}"])
        amounts = request_amounts(bp.protos, p, recipe)
        reqs = [(f"{i}@{tier}", max(20, amounts[i] // (4 if k == 0 else 1))) for k, i in enumerate(ingredients)]
        bp.place("requester-chest", x, y + 6, requests=reqs, tag="raw-returns")
        bp.place(p.inserter, x, y + 5, S)
    else:
        amounts = request_amounts(bp.protos, p, recipe)
        reqs = [(f"{i}@{tier}", max(20, amounts[i] // 4)) for i in ingredients]
        bp.place("requester-chest", x + 1, y, requests=reqs, tag="raw-in")
        bp.place(p.inserter, x + 1, y + 1, N)
    bp.place(p.assembler, x, y + 2, N, recipe=recipe, recipe_quality=tier, modules=amods, tag=f"{recipe}-{tier}")
    bp.place(p.inserter, x + 1, y + 5, N)
    bp.place(p.recycler, x + 1, y + 6, S, modules=rmods)               # drops at (x+2, y+10)
    bp.place("active-provider-chest", x + 2, y + 10, tag="raw-out")


def build(protos: Prototypes, p: Params | None = None) -> tuple[Blueprint, dict]:
    p = p or Params()
    pl = plan(protos, p)
    bp = Blueprint(protos, p.label)
    cell = Cell(0, 0)
    x0, y0, x1, y1 = cell.interior()
    x1 -= 1                     # right column holds the belt-fed input chests
    y = y0
    belts = []
    legendary_items = []
    for name, (recipe, item) in LOOPS.items():
        if name not in pl:
            continue
        ingredients = [i["name"] for i in protos.recipe(recipe)["ingredients"] if i["type"] == "item"]
        legendary_items += [i for i in ingredients if i not in legendary_items]
        units = [t for t, n in zip(TIERS, pl[name]["machines"]) for _ in range(n)]
        per_row = (x1 - x0 + 1) // UNIT_W
        if len(units) > per_row:
            raise ValueError(f"{name}: {len(units)} assemblers do not fit one row ({per_row}); lower the machine count")
        # normal-tier units sit on the right, fed by a belt in row y that enters at the cell edge
        xs = []
        for k, tier in enumerate(units):
            ux = x1 - (k + 1) * UNIT_W + 1
            unit(bp, ux, y, recipe, tier, ingredients, p, belt_fed=(tier == "normal"))
            if tier == "normal":
                xs.append(ux)
        for bx in range(min(xs), x1 + 2):
            bp.place("turbo-transport-belt", bx, y, W, tag="belt")
        bp.place("turbo-loader", x1 + 2, y, W, io_type="output", tag="test")
        bp.place("infinity-chest", x1 + 4, y, tag="test", infinity_items=[(ingredients[0], 100)])
        belts.append((name, y, ingredients))
        y += UNIT_H + 1
    rmods = [p.recycler_modules] * protos.module_slots(p.recycler)
    selfs = [i.strip() for i in p.self_items.split(",") if i.strip()]
    jobs = [it for it in selfs for _ in range(p.pairs_per_item)]
    pw = PAIR_SIZE[0] + 1
    for k, item in enumerate(jobs):
        col = k % ((x1 - x0 + 2) // pw)
        row = k // ((x1 - x0 + 2) // pw)
        recycler_pair(bp, x0 + col * pw, y + row * (PAIR_SIZE[1] + 1), item, rmods, p.inserter, tag=f"pair-{item}")
    legendary_items += selfs
    grid = add_grid(bp, [cell], tag="grid")
    snap_to_grid(bp)
    spots = [(xx, yy) for yy in range(y1, y1 - 6, -1) for xx in range(x0, x1 + 1, 2) if bp.free(xx, yy)]
    si = 0
    for item in legendary_items:
        bp.place("storage-chest", *spots[si], storage_filter=f"{item}@{LEG}", tag="legendary-out")
        si += 1
    for _ in range(6):
        bp.place("storage-chest", *spots[si], tag="buffer")
        si += 1
    # belt-fed input chests: about one chest per 10 items/s of demand
    demand = {}
    for name, v in pl.items():
        if name in LOOPS:
            main = LOOPS[name][1]
            for k, val in v.items():
                if k.endswith("_input_per_s") and not k.startswith(main):
                    item = k.replace("_input_per_s", "")
                    demand[item] = demand.get(item, 0) + val
            continue               # the main item of assembler loops is belt-fed
        for k, val in v.items():
            if k.endswith("_input_per_s") or k.endswith("_input_per_s_max"):
                item = k.replace("_input_per_s_max", "").replace("_input_per_s", "")
                demand[item] = demand.get(item, 0) + val
    if demand:
        input_station(bp, cell, {item: max(1, math.ceil(d / 10)) for item, d in demand.items()}, p.inserter, from_bottom=True)
    poles = [e for e in grid if e.name in ("medium-electric-pole", "big-electric-pole")]
    x0_, y0_, x1_, y1_ = cell.interior()
    auto_power(bp, (x0_, y0_, x1_ + 1, y1_), connect_to=poles)
    belt_txt = "; ".join(f"{n} belt: feed {ing[0]} at cell tile (47, {yy - cell.y0}), heading west" for n, yy, ing in belts)
    bp.description = "fbs raw upcycler (City Block 2.0, 1 cell). " + belt_txt + ". " + "; ".join(
        f"{k}: " + ", ".join(f"{kk} {vv}" for kk, vv in v.items()) for k, v in pl.items())
    bp.icons = [{"signal": {"name": "stone", "quality": "legendary"}, "index": 1}, {"signal": {"name": "coal", "quality": "legendary"}, "index": 2}]
    bp.meta = {"plan": pl, "params": asdict(p), "grid_cells": [(0, 0)]}
    return bp, pl
