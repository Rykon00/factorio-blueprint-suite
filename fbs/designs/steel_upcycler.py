"""Steel upcycler (LDS shuffle in the City Block 2.0 grid): legendary steel, plastic and copper.

Steel only recycles into itself, and every recipe that keeps more steel per pass
(electric poles in the EM plant) needs iron sticks and cables of the same
quality. The clean single-item loop that yields steel is the LDS shuffle:
casting LDS from plastic + molten iron + molten copper, recycling LDS into
plastic, copper and steel. Plastic climbs the tiers, steel and copper fall out
of every pass.

Units are the brick-upcycler foundry units with ``casting-low-density-structure``.
Non-legendary steel is used up in robot-free recycler pairs (speed modules by
default: steel recycling takes 1 s per plate). Non-legendary copper is left to the logistic network: the
em-upcycler asks for exactly that (copper of every quality), so build it in the
same network, or set ``copper_pairs``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ..geometry import Direction
from ..grid import Cell, add_grid, snap_to_grid
from ..model import Blueprint
from ..power import auto_power
from ..protos import Prototypes
from ..quality import QUALITIES
from . import lds_shuffle
from .common import PAIR_SIZE, recycler_pair

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
    lds_productivity_research: int = 1
    steel_pairs: int = 2
    pair_modules: str = "speed-module-3"      # steel recycles slowly (1 s); speed keeps up, quality would add a little legendary steel
    copper_pairs: int = 0
    request_amount: int = 30
    buffer_storage: int = 6
    label: str = "Steel upcycler / LDS shuffle (fbs)"


def unit(bp: Blueprint, x: int, y: int, tier: str, p: Params) -> None:
    fmods = [p.foundry_modules] * bp.protos.module_slots(p.foundry)
    rmods = [p.recycler_modules] * bp.protos.module_slots(p.recycler)
    bp.place("active-provider-chest", x + 3, y, tag="lds-out")
    bp.place(p.recycler, x + 3, y + 1, N, modules=rmods)
    bp.place("requester-chest", x + 1, y + 4, requests=[(f"plastic-bar@{tier}", p.request_amount)], tag="plastic-in")
    bp.place(p.inserter, x + 1, y + 5, N)
    bp.place(p.inserter, x + 3, y + 5, S)
    bp.place(p.foundry, x, y + 6, N, recipe="casting-low-density-structure", recipe_quality=tier, modules=fmods, tag=f"foundry-{tier}")
    bp.place("pipe", x + 1, y + 11)                      # molten iron
    bp.place("pipe-to-ground", x + 3, y + 11, N)         # molten copper dives under the iron main
    bp.place("pipe-to-ground", x + 3, y + 13, S)


def build(protos: Prototypes, p: Params | None = None) -> tuple[Blueprint, object]:
    p = p or Params()
    lp = lds_shuffle.Params(normal_foundries=p.normal_foundries, foundry=p.foundry, recycler=p.recycler,
                            foundry_modules=p.foundry_modules, recycler_modules=p.recycler_modules,
                            lds_productivity_research=p.lds_productivity_research, foundries=p.foundries)
    pl = lds_shuffle.plan(protos, lp)
    bp = Blueprint(protos, p.label)
    tiers = [t for t, n in zip(TIERS, pl.foundries) for _ in range(n)]
    cells: list[Cell] = []
    rows = []
    per_row = (44 - 2) // UNIT_W
    i = ci = 0
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
                rows.append((y, x0, xs + n * UNIT_W - 1))
            if i >= len(tiers):
                break
        ci += 1
    for y, xa, xb in rows:
        for xx in range(xa, xb + 1):
            if bp.free(xx, y + 12):
                bp.place("pipe", xx, y + 12)
            if bp.free(xx, y + 14):
                bp.place("pipe", xx, y + 14)
        bp.place("infinity-pipe", xa - 1, y + 12, tag="test", infinity_fluid=("molten-iron", 1500))
        bp.place("infinity-pipe", xa - 1, y + 14, tag="test", infinity_fluid=("molten-copper", 1100))
    grid = add_grid(bp, cells, tag="grid")
    snap_to_grid(bp)
    sx0, _, sx1, sy1 = cells[-1].interior()
    rmods = [p.pair_modules] * protos.module_slots(p.recycler)
    pairs = ["steel-plate"] * p.steel_pairs + ["copper-plate"] * p.copper_pairs
    for k, item in enumerate(pairs):
        recycler_pair(bp, sx1 - PAIR_SIZE[0] + 1 - k * (PAIR_SIZE[0] + 1), sy1 - PAIR_SIZE[1] - 2, item, rmods, p.inserter, tag="pair")
    spots = [(x, y) for y in range(sy1, sy1 - 6, -1) for x in range(sx0 + 1, sx1 + 1, 2) if bp.free(x, y)]
    si = 0
    for spec in (f"plastic-bar@{LEG}", f"steel-plate@{LEG}", f"copper-plate@{LEG}", f"copper-plate@{LEG}"):
        bp.place("storage-chest", *spots[si], storage_filter=spec, tag="legendary-out")
        si += 1
    for _ in range(p.buffer_storage):
        bp.place("storage-chest", *spots[si], tag="buffer")
        si += 1
    # test-only: plastic source and a copper consumer (stands in for the em-upcycler)
    tx = cells[-1].x0 + 53
    for j in range(3):
        bp.place("infinity-chest", tx, 10 + j, tag="test", infinity_items=[("plastic-bar", 100)])
        bp.place(p.inserter, tx + 1, 10 + j, W, tag="test")
        bp.place("passive-provider-chest", tx + 2, 10 + j, tag="test")
    if not p.copper_pairs:
        for j in range(3):
            bp.place("requester-chest", tx, 16 + j, tag="test",
                     requests=[(f"copper-plate@{q}", 200 if q == "normal" else 50) for q in TIERS])
            bp.place(p.inserter, tx + 1, 16 + j, W, tag="test")
            bp.place("infinity-chest", tx + 2, 16 + j, tag="test", void=True)
    poles = [e for e in grid if e.name in ("medium-electric-pole", "big-electric-pole")]
    for c in cells:
        auto_power(bp, c.interior(), connect_to=poles)
    auto_power(bp, (tx - 3, 5, tx + 8, 22), connect_to=poles, tag="test")
    copper_txt = ("non-legendary copper is consumed by recycler pairs" if p.copper_pairs else
                  f"~{sum(pl.flows['copper_per_s'][:-1]):.0f} non-legendary copper/s goes to the logistic network (build the em-upcycler there to use it)")
    bp.description = (
        f"fbs steel upcycler / LDS shuffle for the City Block 2.0 grid ({len(cells)} cell(s)). Foundries per tier {pl.foundries}. "
        f"Requests ~{pl.plastic_input_per_s:.1f} normal plastic/s; molten iron (upper main) and molten copper (lower main) enter "
        f"on the left edge of each foundry row. {copper_txt}. Planned legendary/h: "
        + ", ".join(f"{k} {v:.0f}" for k, v in pl.legendary_per_hour.items())
    )
    bp.icons = [{"signal": {"name": "steel-plate", "quality": "legendary"}, "index": 1},
                {"signal": {"name": "low-density-structure"}, "index": 2}]
    bp.meta = {"plan": asdict(pl), "params": asdict(p), "grid_cells": [(c.cx, c.cy) for c in cells]}
    return bp, pl
