"""EM upcycler: normal iron + copper plates in, legendary iron + copper plates out.

Why this loop
-------------
Every quality loop loses material when it recycles, so the best loop is the one
that keeps the most per quality roll. Expected legendary output per normal input
plate with an endless loop (rare Q3 / legendary Q3 modules):

* ore self-recycling             0.016 % / 0.04 %
* gears in assembling machines   0.12 %  / 0.32 %
* cables / green circuits in the electromagnetic plant  0.48 % / 1.3 %

The electromagnetic plant wins: 50 % base productivity and 5 module slots. In
Factorio 2.1 asteroid reprocessing no longer takes quality modules, and the LDS
shuffle only yields copper and steel, so this is the loop for iron.

Cells (bot-supplied, placed in Til's City Block 2.0 grid)
-------------------------------------------------------
Iron cell (quality tier q), 9 x 12 tiles::

    requester(Cu@q) -> EM plant: copper-cable@q --(cables@q)--> EM plant: electronic-circuit@q <- requester(Fe@q)
                       (productivity + speed modules,              (quality modules)
                        so every cable has the tier's quality)      | circuits
                                                                    v
                                                                  recycler -> chest -> iron  -> active provider
                                                                                    '-> cables -> recycler -> active provider (Cu)

Copper cell (tier q), 4 x 12 tiles::

    requester(Cu@q) -> EM plant: copper-cable@q -> recycler -> active provider (Cu)


The logistic network carries plates between cells: every requester asks for its
tier's plates, every active provider pushes the mixed-quality results to storage.
Legendary plates end up in filtered storage chests.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from ..geometry import Direction
from ..grid import Cell, add_grid, snap_to_grid
from ..model import Blueprint, parse_item
from ..power import auto_power
from ..protos import Prototypes
from ..quality import QUALITIES, roll

N, E, S, W = Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST
TIERS = QUALITIES[:4]
LEG = QUALITIES[-1]


@dataclass
class Params:
    iron_cells: list[int] | None = None      # per tier [normal, uncommon, rare, epic]; None = planned
    copper_cells: list[int] | None = None
    normal_iron_cells: int = 3               # planner input: size of the normal iron tier
    em_plant: str = "electromagnetic-plant"
    recycler: str = "recycler"
    inserter: str = "bulk-inserter"
    em_modules: str = "quality-module-3@rare"
    cable_modules: str = "productivity-module-3,productivity-module-3,productivity-module-3,productivity-module-3,speed-module-3"
    recycler_modules: str = "quality-module-3@rare"
    em_productivity: float = 0.5             # electromagnetic plant base productivity
    request_amount: int = 40
    grid_cells: int = 0                      # 0 = as many 50x50 grid cells as needed
    buffer_storage: int = 6
    label: str = "EM upcycler (fbs)"


@dataclass
class Plan:
    iron_cells: list[int]
    copper_cells: list[int]
    iron_input_per_s: float
    copper_input_per_s: float
    legendary_per_hour: dict[str, float]
    utilisation: dict[str, list[float]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _module_quality_speed(protos: Prototypes, spec: str, slots: int) -> tuple[float, float]:
    name, q = parse_item(spec)
    eff = protos.module_effects(name)
    mult = 1.0 + 0.3 * QUALITIES.index(q)
    quality = max(0.0, eff.get("quality", 0)) * mult * slots
    speed = eff.get("speed", 0) * (mult if eff.get("speed", 0) > 0 else 1.0) * slots
    return quality, speed


def simulate(protos: Prototypes, p: Params, iron: list[int], copper: list[int]) -> dict[str, Any]:
    """Steady-state expected flows for given cell counts (tier 0 inputs are unlimited)."""
    L = len(QUALITIES)
    qe, se = _module_quality_speed(protos, p.em_modules, protos.module_slots(p.em_plant))
    qr, _ = _module_quality_speed(protos, p.recycler_modules, protos.module_slots(p.recycler))
    speed = protos.crafting_speed(p.em_plant) * max(0.2, 1 + se)
    cap = speed / protos.recipe("copper-cable")["energy"]          # crafts / s per EM plant (cable and circuit are both 0.5 s)
    prod = p.em_productivity
    cables_per_craft = 2 * (1 + prod)
    fe_pool = [0.0] * L
    cu_pool = [0.0] * L
    fe_in = cu_in = 0.0
    util_i, util_c = [0.0] * 4, [0.0] * 4
    leftover_fe = [0.0] * 4
    leftover_cu = [0.0] * 4

    cm = [m for m in p.cable_modules.split(",") if m]
    c_prod = prod + sum(max(0.0, protos.module_effects(parse_item(m)[0]).get("productivity", 0)) * (1 + 0.3 * QUALITIES.index(parse_item(m)[1])) for m in cm)
    c_speed = sum(protos.module_effects(parse_item(m)[0]).get("speed", 0) * ((1 + 0.3 * QUALITIES.index(parse_item(m)[1])) if protos.module_effects(parse_item(m)[0]).get("speed", 0) > 0 else 1) for m in cm)
    cable_cap = protos.crafting_speed(p.em_plant) * max(0.2, 1 + c_speed) / protos.recipe("copper-cable")["energy"]
    cables_per_cu = 2 * (1 + min(3.0, c_prod))
    circuit_cap = min(cap, cable_cap * cables_per_cu / 3)   # circuit crafts/s one iron cell can sustain

    def returns_iron_cell(k: int, C: float):
        """Plates returned (by quality) from an iron cell doing C circuit crafts/s at tier k."""
        fe, cu = [0.0] * L, [0.0] * L
        circuits = C * (1 + prod)
        for j, pj in enumerate(roll(k, qe)):
            nc = circuits * pj
            if nc <= 0:
                continue
            for m, pr in enumerate(roll(j, qr)):
                fe[m] += nc * 0.25 * pr
                cab = nc * 0.75 * pr
                for n_, pr2 in enumerate(roll(m, qr)):
                    cu[n_] += cab * 0.125 * pr2
        return fe, cu, C * 3 / cables_per_cu

    def returns_copper_cell(k: int, D: float):
        cu = [0.0] * L
        for j, pj in enumerate(roll(k, qe)):
            n = D * cables_per_craft * pj
            for m, pr in enumerate(roll(j, qr)):
                cu[m] += n * 0.125 * pr
        return cu

    for k in range(4):
        a = cables_per_cu / 3            # circuit crafts per copper plate
        C_max = iron[k] * circuit_cap
        D_max = copper[k] * cap
        C = D = 0.0
        for _ in range(100):  # fixed point: a tier feeds part of its own input
            fe_r, cu_r, _ = returns_iron_cell(k, C)
            cu_r2 = returns_copper_cell(k, D)
            if k == 0:
                C_new, D_new = C_max, D_max
            else:
                fe_avail = fe_pool[k] + fe_r[k]
                cu_avail = cu_pool[k] + cu_r[k] + cu_r2[k]
                C_new = min(C_max, fe_avail, cu_avail * a)
                D_new = min(D_max, max(0.0, cu_avail - C_new / a))
            if abs(C_new - C) < 1e-12 and abs(D_new - D) < 1e-12:
                break
            C, D = C_new, D_new
        fe_r, cu_r, _ = returns_iron_cell(k, C)
        cu_r2 = returns_copper_cell(k, D)
        if k == 0:
            fe_in = C - fe_r[0]
            cu_in = C / a + D - cu_r[0] - cu_r2[0]
        else:
            leftover_fe[k] = fe_pool[k] + fe_r[k] - C
            leftover_cu[k] = cu_pool[k] + cu_r[k] + cu_r2[k] - C / a - D
        for m in range(k + 1, L):
            fe_pool[m] += fe_r[m]
            cu_pool[m] += cu_r[m] + cu_r2[m]
        util_i[k] = C / C_max if C_max else 0.0
        util_c[k] = D / D_max if D_max else 0.0
    return {
        "legendary_fe": fe_pool[-1],
        "legendary_cu": cu_pool[-1],
        "fe_in": fe_in,
        "cu_in": cu_in,
        "util_iron": util_i,
        "util_copper": util_c,
        "leftover_fe": leftover_fe,
        "leftover_cu": leftover_cu,
        "cap": cap,

        "qe": qe,
        "qr": qr,
    }


def plan(protos: Prototypes, p: Params) -> Plan:
    notes = []
    if p.iron_cells and p.copper_cells:
        iron, copper = list(p.iron_cells), list(p.copper_cells)
    else:
        best = None
        for c0 in range(0, 3 * p.normal_iron_cells + 1):
            iron = [p.normal_iron_cells, 0, 0, 0]
            copper = [c0, 0, 0, 0]
            # grow the upper tiers until nothing piles up
            for k in range(1, 4):
                for _ in range(40):
                    sim = simulate(protos, p, iron, copper)
                    if sim["leftover_fe"][k] > 1e-6 and (iron[k] == 0 or sim["util_iron"][k] >= 0.999):
                        iron[k] += 1
                        continue
                    sim = simulate(protos, p, iron, copper)
                    if sim["leftover_cu"][k] > 1e-6 and (copper[k] == 0 or sim["util_copper"][k] >= 0.999):
                        copper[k] += 1
                        continue
                    break
            sim = simulate(protos, p, iron, copper)
            pile = sum(sim["leftover_fe"]) + sum(sim["leftover_cu"])
            score = (round(pile, 6), -(sim["legendary_fe"] + sim["legendary_cu"]), sum(iron) + sum(copper))
            if best is None or score < best[0]:
                best = (score, iron, copper, sim)
        _, iron, copper, _ = best
    sim = simulate(protos, p, iron, copper)
    if sum(sim["leftover_fe"]) > 1e-6 or sum(sim["leftover_cu"]) > 1e-6:
        notes.append("some upper-tier plates are not consumed and wait in storage")
    return Plan(
        iron_cells=iron,
        copper_cells=copper,
        iron_input_per_s=round(sim["fe_in"], 3),
        copper_input_per_s=round(sim["cu_in"], 3),
        legendary_per_hour={"iron-plate": round(sim["legendary_fe"] * 3600, 1), "copper-plate": round(sim["legendary_cu"] * 3600, 1)},
        utilisation={"iron": [round(x, 3) for x in sim["util_iron"]], "copper": [round(x, 3) for x in sim["util_copper"]]},
        notes=notes,
    )


# ---------------------------------------------------------------------- cells

def iron_cell(bp: Blueprint, x: int, y: int, tier: str, p: Params) -> None:
    em_mods = [p.em_modules] * bp.protos.module_slots(p.em_plant)
    cable_mods = [m for m in p.cable_modules.split(",") if m]
    rc_mods = [p.recycler_modules] * bp.protos.module_slots(p.recycler)
    ins = p.inserter
    bp.place("requester-chest", x + 1, y, requests=[(f"copper-plate@{tier}", p.request_amount)], tag="iron-cell")
    bp.place("requester-chest", x + 6, y, requests=[(f"iron-plate@{tier}", p.request_amount)], tag="iron-cell")
    bp.place(ins, x + 1, y + 1, N)
    bp.place(ins, x + 6, y + 1, N)
    bp.place(p.em_plant, x, y + 2, N, recipe="copper-cable", recipe_quality=tier, modules=cable_mods, tag=f"iron-cables-{tier}")
    bp.place(p.em_plant, x + 5, y + 2, N, recipe="electronic-circuit", recipe_quality=tier, modules=em_mods, tag=f"iron-circuits-{tier}")
    bp.place(ins, x + 4, y + 3, W)                                    # cables -> circuit plant
    bp.place(ins, x + 6, y + 6, N)                                    # circuits -> recycler
    bp.place(p.recycler, x + 5, y + 7, W, modules=rc_mods)           # circuits -> iron + cables, drops at (x+4, y+8)
    bp.place("steel-chest", x + 4, y + 8)
    bp.place(ins, x + 3, y + 8, E, filters=[f"iron-plate@{q}" for q in QUALITIES])     # iron out
    bp.place("active-provider-chest", x + 2, y + 8)
    bp.place(ins, x + 4, y + 9, N, filters=[f"copper-cable@{q}" for q in QUALITIES])   # cables -> recycler
    bp.place(p.recycler, x + 1, y + 10, W, modules=rc_mods)          # cables -> copper, drops at (x, y+11)
    bp.place("active-provider-chest", x, y + 11)


def copper_cell(bp: Blueprint, x: int, y: int, tier: str, p: Params) -> None:
    em_mods = [p.em_modules] * bp.protos.module_slots(p.em_plant)
    rc_mods = [p.recycler_modules] * bp.protos.module_slots(p.recycler)
    bp.place("requester-chest", x + 1, y, requests=[(f"copper-plate@{tier}", p.request_amount)], tag="copper-cell")
    bp.place(p.inserter, x + 1, y + 1, N)
    bp.place(p.em_plant, x, y + 2, N, recipe="copper-cable", recipe_quality=tier, modules=em_mods, tag=f"copper-cables-{tier}")
    bp.place(p.inserter, x + 1, y + 6, N)
    bp.place(p.recycler, x, y + 7, S, modules=rc_mods)
    bp.place("active-provider-chest", x + 1, y + 11)


IRON_SIZE = (9, 12)
COPPER_SIZE = (4, 12)


def build(protos: Prototypes, p: Params | None = None) -> tuple[Blueprint, Plan]:
    p = p or Params()
    pl = plan(protos, p)
    bp = Blueprint(protos, p.label)
    items = [("iron", t) for t, n in zip(TIERS, pl.iron_cells) for _ in range(n)] + \
            [("copper", t) for t, n in zip(TIERS, pl.copper_cells) for _ in range(n)]

    # shelf packing inside grid cells (interior tiles 3..46), cells added left to right
    cells: list[Cell] = []
    placements = []
    shelf_h = 12
    gap_x, gap_y = 1, 2          # 2 free rows between shelves leave room for substations
    ci = 0
    cell = Cell(0, 0)
    cells.append(cell)
    x0, y0, x1, y1 = cell.interior()
    cx, cy = x0, y0
    for kind, tier in items:
        w, h = {"iron": IRON_SIZE, "copper": COPPER_SIZE}[kind]
        if cx + w - 1 > x1:
            cx, cy = x0, cy + shelf_h + gap_y
        if cy + shelf_h - 1 > y1 - 4:     # keep the bottom rows for storage and power
            ci += 1
            cell = Cell(ci, 0)
            cells.append(cell)
            x0, y0, x1, y1 = cell.interior()
            cx, cy = x0, y0
        placements.append((kind, tier, cx, cy))
        cx += w + gap_x
    if p.grid_cells and len(cells) > p.grid_cells:
        raise ValueError(f"design needs {len(cells)} grid cells, limit is {p.grid_cells}")
    for kind, tier, x, y in placements:
        if kind == "iron":
            iron_cell(bp, x, y, tier, p)
        else:
            copper_cell(bp, x, y, tier, p)

    grid = add_grid(bp, cells, tag="grid")
    snap_to_grid(bp)

    # storage along the bottom of the first cell
    sx0, _, sx1, sy1 = cells[0].interior()
    spots = [(x, y) for y in range(sy1, sy1 - 4, -1) for x in range(sx0, sx1 + 1, 2) if bp.free(x, y)]
    si = 0
    for spec in (f"iron-plate@{LEG}", f"iron-plate@{LEG}", f"copper-plate@{LEG}", f"copper-plate@{LEG}"):
        bp.place("storage-chest", *spots[si], storage_filter=spec, tag="legendary-out")
        si += 1
    for _ in range(p.buffer_storage):
        bp.place("storage-chest", *spots[si], tag="buffer")
        si += 1

    # test-only plate sources just right of the last cell (dropped from the production blueprint)
    tx = cells[-1].x0 + 53
    srcs = []
    for i, item in enumerate(("iron-plate", "copper-plate")):
        for j in range(3):
            y = 10 + 4 * i + j
            bp.place("infinity-chest", tx, y, tag="test", infinity_items=[(item, 100)])
            srcs.append(bp.place(p.inserter, tx + 1, y, W, tag="test"))
            bp.place("passive-provider-chest", tx + 2, y, tag="test")

    poles_grid = [e for e in grid if e.name in ("medium-electric-pole", "big-electric-pole")]
    for c in cells:
        auto_power(bp, c.interior(), connect_to=poles_grid)
    auto_power(bp, (tx - 3, 5, tx + 8, 25), connect_to=poles_grid, tag="test")

    bp.description = (
        f"fbs EM upcycler for Til's City Block 2.0 grid ({len(cells)} cell(s)). Iron cells per tier {pl.iron_cells}, "
        f"copper cells {pl.copper_cells}. Requests normal plates from the logistic network: ~{pl.iron_input_per_s:.1f} iron/s and "
        f"~{pl.copper_input_per_s:.1f} copper/s. Planned legendary output: {pl.legendary_per_hour['iron-plate']:.0f} iron/h, "
        f"{pl.legendary_per_hour['copper-plate']:.0f} copper/h (lands in the filtered storage chests)."
    )
    bp.icons = [{"signal": {"name": "iron-plate", "quality": "legendary"}, "index": 1},
                {"signal": {"name": "copper-plate", "quality": "legendary"}, "index": 2}]
    bp.meta = {"plan": asdict(pl), "params": asdict(p), "grid_cells": [(c.cx, c.cy) for c in cells]}
    return bp, pl
