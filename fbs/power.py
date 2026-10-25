"""Automatic power poles: greedy set cover over free spots, then wiring."""

from __future__ import annotations

import math

from .model import Blueprint, Entity

POWERED_TYPES = {"assembling-machine", "furnace", "inserter", "roboport", "lab", "mining-drill", "beacon",
                 "pump", "radar", "rocket-silo", "agricultural-tower", "asteroid-collector"}


def _covers(cx: float, cy: float, dist: float, ent: Entity) -> bool:
    xs = [t[0] for t in ent.tiles]
    ys = [t[1] for t in ent.tiles]
    # supply area in tile units: centre +- dist; entity tiles [x, x+1)
    return not (max(xs) + 1 <= cx - dist or min(xs) >= cx + dist or max(ys) + 1 <= cy - dist or min(ys) >= cy + dist)


def auto_power(bp: Blueprint, region: tuple[int, int, int, int], pole: str = "substation",
               connect_to: list[Entity] | None = None, tag: str | None = None) -> list[Entity]:
    """Place ``pole`` entities inside ``region`` (x0, y0, x1, y1 inclusive) until every powered
    entity in the region is covered, then wire them (and to the nearest pole in ``connect_to``)."""
    protos = bp.protos
    w, h = protos.size(pole)
    dist = float(protos.entity(pole).get("supply_area_distance") or 9)
    reach = float(protos.entity(pole).get("max_wire_distance") or 18)
    x0, y0, x1, y1 = region
    targets = [e for e in bp.entities
               if protos.entity(e.name)["type"] in POWERED_TYPES
               and any(x0 <= t[0] <= x1 and y0 <= t[1] <= y1 for t in e.tiles)]
    existing = [e for e in bp.entities if protos.entity(e.name)["type"] == "electric-pole"]
    uncovered = set()
    for e in targets:
        covered = False
        for p in existing:
            d = float(protos.entity(p.name).get("supply_area_distance") or 0)
            if d and _covers(p.position[0], p.position[1], d, e):
                covered = True
                break
        if not covered:
            uncovered.add(e.number)
    candidates = []
    for x in range(x0, x1 - w + 2):
        for y in range(y0, y1 - h + 2):
            if all(bp.free(x + i, y + j) for i in range(w) for j in range(h)):
                candidates.append((x, y))
    placed: list[Entity] = []
    by_num = {e.number: e for e in targets}
    while uncovered:
        best, best_set = None, set()
        for (x, y) in candidates:
            if not all(bp.free(x + i, y + j) for i in range(w) for j in range(h)):
                continue
            cx, cy = x + w / 2, y + h / 2
            s = {n for n in uncovered if _covers(cx, cy, dist, by_num[n])}
            if len(s) > len(best_set):
                best, best_set = (x, y), s
        if not best:
            raise RuntimeError(f"auto_power: {len(uncovered)} entities cannot be powered (no free spot for {pole})")
        placed.append(bp.place(pole, best[0], best[1], tag=tag))
        uncovered -= best_set
    # wiring: grow a tree from the anchors (existing poles / connect_to); bridge long gaps with extra poles
    anchors = list(connect_to or existing)
    nodes = list(placed)
    connected: list[Entity] = list(anchors)
    if not connected and nodes:
        connected.append(nodes.pop(0))

    def reach_of(e: Entity) -> float:
        return float(protos.entity(e.name).get("max_wire_distance") or reach)

    def link(a: Entity, b: Entity) -> float:
        return min(reach_of(a), reach_of(b))

    def free_spot_near(a: Entity, target: Entity):
        best_pos, best_d = None, None
        ax, ay = a.position
        r = int(reach)
        for x in range(int(ax) - r, int(ax) + r + 1):
            for y in range(int(ay) - r, int(ay) + r + 1):
                if not all(bp.free(x + i, y + j) for i in range(w) for j in range(h)):
                    continue
                c = (x + w / 2, y + h / 2)
                if math.dist(c, a.position) > min(reach, reach_of(a)):
                    continue
                d = math.dist(c, target.position)
                if best_d is None or d < best_d:
                    best_pos, best_d = (x, y), d
        return best_pos

    while nodes:
        a, n = min(((a, n) for a in connected for n in nodes), key=lambda an: math.dist(an[0].position, an[1].position))
        if math.dist(a.position, n.position) <= link(a, n):
            bp.copper(a, n)
            connected.append(n)
            nodes.remove(n)
            continue
        spot = free_spot_near(a, n)
        if spot is None:
            raise RuntimeError("auto_power: cannot bridge the gap between poles")
        bridge = bp.place(pole, spot[0], spot[1], tag=tag)
        placed.append(bridge)
        bp.copper(a, bridge)
        connected.append(bridge)
    return placed
