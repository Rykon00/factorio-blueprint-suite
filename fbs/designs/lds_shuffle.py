"""LDS shuffle: normal plastic in, legendary plastic / copper / steel out.

How it works
------------
* Foundries cast low density structures from molten iron + molten copper + plastic.
  Plastic is the only item ingredient, so the LDS quality starts at the plastic
  quality and quality modules can push it higher.
* Recyclers turn LDS back into 1.25 plastic + 5 copper + 0.5 steel (25 % of the
  LDS recipe), rolling quality again.
* Plastic of quality q goes back into the foundries for quality q, so plastic
  climbs one tier at a time until it is legendary.

Layout
------
Logistic-bot based, so every machine is a self-contained cell and the design
scales by changing counts instead of re-routing belts:

* Foundry row: requester chest (plastic of the row's quality) -> inserter ->
  foundry -> inserter -> passive provider (LDS). Molten iron / copper come in
  on two pipe mains below the row.
* Recycler row: requester (LDS of every quality) -> inserter -> recycler, the
  recycler drops its output straight into an active provider.
* Void row: recyclers that take non-legendary copper and steel and recycle them
  into themselves (75 % loss per pass). With quality modules the survivors keep
  climbing, so these also add legendary copper and steel.
* Storage row: filtered storage for the legendary outputs, unfiltered storage
  as buffer, two plastic input chests at the left edge and the roboports.

Ports (left edge): plastic input chests at (2, 12) and (2, 13) are filled by
inserters picking up from x = 0; molten iron enters at (0, 8), molten copper
at (0, 10). The test variant puts infinity chests / pipes on those tiles.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from ..geometry import Direction
from ..model import Blueprint, parse_item
from ..protos import Prototypes
from ..quality import QUALITIES, roll

N, E, S, W = Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST


@dataclass
class Params:
    normal_foundries: int = 12
    foundry: str = "foundry"
    recycler: str = "recycler"
    inserter: str = "bulk-inserter"
    foundry_modules: str = "quality-module-3@rare"
    recycler_modules: str = "quality-module-3@rare"
    void_modules: str = "quality-module-3@rare"
    lds_productivity_research: int = 1       # researched levels (+10 % each)
    recycle_legendary_lds: bool = True       # False keeps legendary LDS in storage
    keep_legendary: tuple[str, ...] = ("plastic-bar", "copper-plate", "steel-plate")
    headroom: float = 1.15                   # extra machine capacity on top of the plan
    foundries: list[int] | None = None       # override per tier [normal, uncommon, rare, epic]
    lds_recyclers: int | None = None
    void_recyclers: int | None = None
    unfiltered_storage: int = 12
    roboport_spacing: int = 16
    robots_per_roboport: int = 60          # recommendation written into the description
    label: str = "LDS shuffle (fbs)"


@dataclass
class Plan:
    foundries: list[int]
    lds_recyclers: int
    void_recyclers: int
    plastic_input_per_s: float
    legendary_per_hour: dict[str, float]
    flows: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------- planning

def _module_effects(protos: Prototypes, spec: str, slots: int) -> dict[str, float]:
    name, q = parse_item(spec)
    eff = protos.module_effects(name)
    mult = 1.0 + 0.3 * QUALITIES.index(q)  # quality scales positive module effects by +30 % per level
    out: dict[str, float] = {}
    for k, v in eff.items():
        scaled = v * mult if v > 0 else v
        out[k] = out.get(k, 0.0) + scaled * slots
    return out


def _entity_base_prod(protos: Prototypes, name: str) -> float:
    rec = protos.entity(name).get("effect_receiver") or {}
    base = rec.get("base_effect") or {}
    if "productivity" in base:
        return float(base["productivity"])
    return 0.5 if "foundry" in name else 0.0


def plan(protos: Prototypes, p: Params) -> Plan:
    cast = protos.recipe("casting-low-density-structure")
    rec_lds = protos.recipe("low-density-structure-recycling")
    rec_cu = protos.recipe("copper-plate-recycling")
    rec_st = protos.recipe("steel-plate-recycling")

    f_slots = protos.module_slots(p.foundry)
    r_slots = protos.module_slots(p.recycler)
    fe = _module_effects(protos, p.foundry_modules, f_slots)
    re_ = _module_effects(protos, p.recycler_modules, r_slots)
    ve = _module_effects(protos, p.void_modules, r_slots)

    f_speed = protos.crafting_speed(p.foundry) * max(0.2, 1 + fe.get("speed", 0))
    r_speed = protos.crafting_speed(p.recycler) * max(0.2, 1 + re_.get("speed", 0))
    v_speed = protos.crafting_speed(p.recycler) * max(0.2, 1 + ve.get("speed", 0))
    f_prod = min(cast.get("maximum_productivity") or 3.0,
                 _entity_base_prod(protos, p.foundry) + fe.get("productivity", 0) + 0.1 * p.lds_productivity_research)
    fq, rq, vq = max(0.0, fe.get("quality", 0)), max(0.0, re_.get("quality", 0)), max(0.0, ve.get("quality", 0))

    crafts_per_foundry = f_speed / cast["energy"]          # crafts / s
    lds_per_recycler = r_speed / rec_lds["energy"]          # LDS / s
    plastic_per_craft = next(i["amount"] for i in cast["ingredients"] if i["name"] == "plastic-bar")

    # steady state over quality tiers (expected values)
    L = len(QUALITIES)
    crafts = [0.0] * L
    crafts[0] = p.normal_foundries * crafts_per_foundry
    plastic_back = [0.0] * L
    lds = [0.0] * L
    cu = [0.0] * L
    st = [0.0] * L
    for _ in range(200):
        lds = [0.0] * L
        for i in range(L - 1):
            dist = roll(i, fq, L)
            for j in range(L):
                lds[j] += crafts[i] * (1 + f_prod) * dist[j]
        recycled = lds[:] if p.recycle_legendary_lds else lds[:-1] + [0.0]
        plastic_back = [0.0] * L
        cu = [0.0] * L
        st = [0.0] * L
        for j in range(L):
            if recycled[j] <= 0:
                continue
            dist = roll(j, rq, L)
            for k in range(L):
                plastic_back[k] += recycled[j] * 1.25 * dist[k]
                cu[k] += recycled[j] * 5 * dist[k]
                st[k] += recycled[j] * 0.5 * dist[k]
        new = crafts[:]
        for k in range(1, L - 1):
            new[k] = plastic_back[k] / plastic_per_craft
        if max(abs(a - b) for a, b in zip(new, crafts)) < 1e-12:
            break
        crafts = new

    foundries = p.foundries or [p.normal_foundries] + [
        max(1, math.ceil(crafts[k] / crafts_per_foundry * p.headroom)) for k in range(1, L - 1)
    ]
    lds_total = sum(lds) if p.recycle_legendary_lds else sum(lds[:-1])
    lds_recyclers = p.lds_recyclers or max(1, math.ceil(lds_total / lds_per_recycler * p.headroom))

    # void: every pass keeps 25 %, so the work is flow / 0.75
    keep = 0.25
    cu_rate = v_speed / rec_cu["energy"]
    st_rate = v_speed / rec_st["energy"]
    void_load = (sum(cu[:-1]) / cu_rate + sum(st[:-1]) / st_rate) / (1 - keep)
    void_recyclers = p.void_recyclers or max(1, math.ceil(void_load * p.headroom))

    # legendary from the void loop: geometric series of upgrades
    def void_legendary(flows: list[float]) -> float:
        total = 0.0
        stock = flows[:-1] + [0.0]
        for _ in range(60):
            nxt = [0.0] * L
            for j in range(L - 1):
                if stock[j] <= 0:
                    continue
                dist = roll(j, vq, L)
                for k in range(L):
                    nxt[k] += stock[j] * keep * dist[k]
            total += nxt[-1]
            nxt[-1] = 0.0
            stock = nxt
        return total

    plastic_in = crafts[0] * plastic_per_craft - plastic_back[0]
    leg = {
        "plastic-bar": plastic_back[-1] * 3600,
        "copper-plate": (cu[-1] + void_legendary(cu)) * 3600,
        "steel-plate": (st[-1] + void_legendary(st)) * 3600,
    }
    if not p.recycle_legendary_lds:
        leg["low-density-structure"] = lds[-1] * 3600
    return Plan(
        foundries=foundries,
        lds_recyclers=lds_recyclers,
        void_recyclers=void_recyclers,
        plastic_input_per_s=round(plastic_in, 3),
        legendary_per_hour={k: round(v, 1) for k, v in leg.items()},
        flows={
            "crafts_per_s": [round(c, 4) for c in crafts],
            "lds_per_s": [round(x, 4) for x in lds],
            "plastic_back_per_s": [round(x, 4) for x in plastic_back],
            "copper_per_s": [round(x, 4) for x in cu],
            "steel_per_s": [round(x, 4) for x in st],
            "foundry_speed": round(f_speed, 3),
            "foundry_productivity": round(f_prod, 3),
            "foundry_quality": round(fq, 4),
            "recycler_quality": round(rq, 4),
        },
    )


# ---------------------------------------------------------------------- layout

def build(protos: Prototypes, p: Params | None = None) -> tuple[Blueprint, Plan]:
    p = p or Params()
    pl = plan(protos, p)
    bp = Blueprint(protos, p.label)
    fmods = [p.foundry_modules] * protos.module_slots(p.foundry)
    rmods = [p.recycler_modules] * protos.module_slots(p.recycler)
    vmods = [p.void_modules] * protos.module_slots(p.recycler)
    tiers = QUALITIES[:4]
    LEG = QUALITIES[-1]

    X0 = 4                       # first machine column; x 0..3 are ports
    # ---------------- foundry row (y 0..10)
    x = X0
    foundry_x = []
    for tier, count in zip(tiers, pl.foundries):
        for _ in range(count):
            cx = x + 2           # centre tile column of the 5x5 foundry
            bp.place("requester-chest", cx - 1, 0, requests=[(f"plastic-bar@{tier}", 20)], tag="foundry-in")
            bp.place(p.inserter, cx - 1, 1, N)
            bp.place(p.foundry, x, 2, N, recipe="casting-low-density-structure", recipe_quality=tier, modules=fmods, tag=f"foundry-{tier}")
            bp.place(p.inserter, cx + 1, 1, S)
            bp.place("passive-provider-chest", cx + 1, 0, tag="foundry-out")
            # fluids: iron straight down into the main at y=8, copper dives under it to y=10
            bp.place("pipe", cx - 1, 7)
            bp.place("pipe-to-ground", cx + 1, 7, N)
            bp.place("pipe-to-ground", cx + 1, 9, S)
            foundry_x.append(cx)
            x += 5
    row_end = x
    # mains
    for xx in range(1, row_end):
        bp.place("pipe", xx, 8)
        bp.place("pipe", xx, 10)
    bp.place("infinity-pipe", 0, 8, tag="test", infinity_fluid=("molten-iron", 1500))
    bp.place("infinity-pipe", 0, 10, tag="test", infinity_fluid=("molten-copper", 1100))

    # ---------------- recycler rows (output chest y=15, recycler 16..19, inserter 20, requester 21)
    lds_req = [(f"low-density-structure@{q}", 10 if q == "normal" else 2) for q in tiers]
    if p.recycle_legendary_lds:
        lds_req.append((f"low-density-structure@{LEG}", 2))
    void_req = [(f"copper-plate@{q}", 20) for q in tiers] + [(f"steel-plate@{q}", 10) for q in tiers]
    x = X0
    rec_cells = [("lds", lds_req, rmods)] * pl.lds_recyclers + [("void", void_req, vmods)] * pl.void_recyclers
    for kind, req, mods in rec_cells:
        cx = x + 1               # right column of the 2-wide recycler
        bp.place("active-provider-chest", cx - 1, 15, tag=f"{kind}-out")
        bp.place(p.recycler, cx - 1, 16, N, modules=mods, tag=f"recycler-{kind}")
        bp.place(p.inserter, cx, 20, S)
        bp.place("requester-chest", cx, 21, requests=req, tag=f"{kind}-in")
        x += 2
    rec_end = x
    width = max(row_end, rec_end) + 2

    # ---------------- storage / logistics row (y 11..14)
    # inputs on the left edge
    for y in (12, 13):
        bp.place("passive-provider-chest", 2, y, tag="plastic-in")
        bp.place(p.inserter, 1, y, W)
        bp.place("infinity-chest", 0, y, tag="test", infinity_items=[("plastic-bar", 100)])
    # roboports along the row
    roboports = []
    rx = X0 + 2
    while True:
        roboports.append(bp.place("roboport", rx, 11))
        if rx + 4 + 25 >= width:
            break
        rx += p.roboport_spacing
    # substations: top row (y -3) covers foundries, middle row (y 11) covers the rest
    subs_top, subs_mid = [], []
    sx = X0 + 4
    while sx < width + 6:
        subs_top.append(bp.place("substation", sx, -3))
        sx += 14
    sx = X0 + 9
    while sx < width + 6:
        while any(not bp.free(sx + dx, 11 + dy) for dx in range(2) for dy in range(2)):
            sx += 1
        subs_mid.append(bp.place("substation", sx, 11))
        sx += 14
    sub_in = bp.place("substation", 0, 14)       # powers the input inserters on the left edge
    for row in (subs_top, subs_mid):
        for a, b in zip(row, row[1:]):
            bp.copper(a, b)
    bp.copper(subs_top[0], subs_mid[0])
    bp.copper(sub_in, subs_mid[0])
    # storage chests in free tiles of rows 13..14
    wanted = [(f"{item}@{LEG}") for item in p.keep_legendary]
    if not p.recycle_legendary_lds:
        wanted.append(f"low-density-structure@{LEG}")
    spots = [(xx, yy) for yy in (14, 13, 12, 11) for xx in range(X0, width) if bp.free(xx, yy)]
    si = 0
    for spec in wanted:
        for _ in range(2):
            xx, yy = spots[si]
            bp.place("storage-chest", xx, yy, storage_filter=spec, tag="legendary-out")
            si += 2
    for _ in range(p.unfiltered_storage):
        xx, yy = spots[si]
        bp.place("storage-chest", xx, yy, tag="buffer")
        si += 2

    bp.description = (
        f"fbs LDS shuffle. Foundries per tier {pl.foundries}, {pl.lds_recyclers} LDS recyclers, "
        f"{pl.void_recyclers} void recyclers. Needs ~{pl.plastic_input_per_s:.1f} normal plastic/s at the input chests (left edge, x=2), "
        f"molten iron at (0,8) and molten copper at (0,10). Put ~{p.robots_per_roboport} logistic robots into each roboport "
        f"({p.robots_per_roboport * len(roboports)} total). The roboports join any logistic network they touch."
    )
    bp.icons = [{"signal": {"name": "low-density-structure", "quality": "legendary"}, "index": 1},
                {"signal": {"name": "recycler"}, "index": 2}]
    bp.meta = {"plan": asdict(pl), "params": asdict(p)}
    return bp, pl
