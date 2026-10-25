"""Steady-state planner for single-item quality loops.

A loop crafts item X (the only item ingredient) into a product with quality
modules, recycles the product back into X with quality modules, and feeds X of
quality q back into the machines for tier q. Fluids are free inputs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .quality import QUALITIES, roll


@dataclass
class LoopSpec:
    x_per_craft: float            # X consumed per craft
    product_per_craft: float      # products per craft before productivity
    productivity: float           # total productivity bonus (capped by caller)
    craft_quality: float          # quality chance of the crafting machine
    crafts_per_s: float           # per crafting machine
    x_per_product: float          # X returned per recycled product (before quality)
    recycle_quality: float
    products_per_s_recycler: float
    recycle_legendary_product: bool = True
    side_outputs: dict[str, float] = field(default_factory=dict)  # other recycling outputs per product


@dataclass
class LoopPlan:
    machines: list[int]           # crafting machines per tier normal..epic
    recyclers: int
    x_input_per_s: float
    legendary_x_per_h: float
    legendary_product_per_h: float
    crafts_per_s: list[float]
    side_per_h: dict[str, list[float]] = field(default_factory=dict)


def plan_loop(spec: LoopSpec, normal_machines: int, headroom: float = 1.15, fixed: list[int] | None = None) -> LoopPlan:
    L = len(QUALITIES)
    crafts = [0.0] * L
    crafts[0] = normal_machines * spec.crafts_per_s
    prod_q = [0.0] * L
    back = [0.0] * L
    for _ in range(300):
        prod_q = [0.0] * L
        for i in range(L - 1):
            d = roll(i, spec.craft_quality, L)
            for j in range(L):
                prod_q[j] += crafts[i] * spec.product_per_craft * (1 + spec.productivity) * d[j]
        recycled = prod_q[:] if spec.recycle_legendary_product else prod_q[:-1] + [0.0]
        back = [0.0] * L
        for j in range(L):
            if recycled[j] <= 0:
                continue
            for k, pk in enumerate(roll(j, spec.recycle_quality, L)):
                back[k] += recycled[j] * spec.x_per_product * pk
        new = crafts[:]
        for k in range(1, L - 1):
            new[k] = back[k] / spec.x_per_craft
        if max(abs(a - b) for a, b in zip(new, crafts)) < 1e-12:
            break
        crafts = new
    machines = fixed or [normal_machines] + [max(1, math.ceil(crafts[k] / spec.crafts_per_s * headroom)) for k in range(1, L - 1)]
    total_products = sum(prod_q) if spec.recycle_legendary_product else sum(prod_q[:-1])
    recyclers = max(1, math.ceil(total_products / spec.products_per_s_recycler * headroom))
    side = {}
    for name, per in spec.side_outputs.items():
        side[name] = [0.0] * L
        recycled = prod_q[:] if spec.recycle_legendary_product else prod_q[:-1] + [0.0]
        for j in range(L):
            for k, pk in enumerate(roll(j, spec.recycle_quality, L)):
                side[name][k] += recycled[j] * per * pk * 3600
    return LoopPlan(
        machines=machines,
        recyclers=recyclers,
        x_input_per_s=round(crafts[0] * spec.x_per_craft - back[0], 3),
        legendary_x_per_h=round(back[-1] * 3600, 1),
        legendary_product_per_h=round(0.0 if spec.recycle_legendary_product else prod_q[-1] * 3600, 1),
        crafts_per_s=[round(c, 4) for c in crafts],
        side_per_h={k: [round(v, 1) for v in vals] for k, vals in side.items()},
    )
