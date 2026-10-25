"""Top-down PNG preview of a blueprint (no game graphics, just footprints)."""

from __future__ import annotations

import math
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .geometry import Direction
from .protos import Prototypes

TYPE_COLORS = {
    "assembling-machine": (70, 110, 160),
    "furnace": (150, 90, 60),
    "transport-belt": (200, 170, 40),
    "underground-belt": (170, 140, 30),
    "splitter": (220, 120, 30),
    "loader": (200, 150, 60),
    "inserter": (120, 170, 80),
    "container": (130, 100, 70),
    "logistic-container": (150, 120, 90),
    "infinity-container": (200, 60, 200),
    "infinity-pipe": (200, 60, 200),
    "pipe": (90, 120, 130),
    "pipe-to-ground": (70, 100, 110),
    "pump": (80, 140, 150),
    "storage-tank": (80, 120, 140),
    "electric-pole": (110, 110, 110),
    "roboport": (90, 90, 140),
    "beacon": (120, 80, 150),
    "constant-combinator": (60, 60, 60),
    "decider-combinator": (60, 60, 60),
    "arithmetic-combinator": (60, 60, 60),
}
LOGISTIC_COLORS = {
    "passive-provider-chest": (200, 60, 60),
    "active-provider-chest": (170, 60, 170),
    "requester-chest": (60, 110, 200),
    "storage-chest": (200, 180, 60),
    "buffer-chest": (60, 170, 60),
}
QUALITY_COLORS = {
    "normal": None,
    "uncommon": (90, 200, 90),
    "rare": (60, 130, 230),
    "epic": (180, 70, 220),
    "legendary": (240, 150, 30),
}


def _abbrev(text: str, n: int) -> str:
    parts = text.replace("casting-", "c-").replace("-recycling", "-rec").split("-")
    if len(text) <= n:
        return text
    return "".join(p[:2] for p in parts)[:n]


def render(bp: dict[str, Any], protos: Prototypes, path: str, scale: int = 16, margin: int = 2) -> str:
    ents = bp["blueprint"]["entities"]
    boxes = []
    for e in ents:
        d = e.get("direction", 0)
        try:
            w, h = protos.size(e["name"], d)
        except KeyError:
            w, h = 1, 1
        cx, cy = e["position"]["x"], e["position"]["y"]
        boxes.append((e, cx - w / 2, cy - h / 2, w, h, d))
    minx = math.floor(min(b[1] for b in boxes)) - margin
    miny = math.floor(min(b[2] for b in boxes)) - margin
    maxx = math.ceil(max(b[1] + b[3] for b in boxes)) + margin
    maxy = math.ceil(max(b[2] + b[4] for b in boxes)) + margin
    W, H = (maxx - minx) * scale, (maxy - miny) * scale
    img = Image.new("RGB", (W, H), (28, 28, 30))
    dr = ImageDraw.Draw(img)
    for x in range(0, W, scale):
        dr.line([(x, 0), (x, H)], fill=(38, 38, 40))
    for y in range(0, H, scale):
        dr.line([(0, y), (W, y)], fill=(38, 38, 40))
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", max(8, scale // 2))
    except OSError:
        font = ImageFont.load_default()

    # big entities first so small ones stay visible
    for e, x0, y0, w, h, d in sorted(boxes, key=lambda b: -(b[3] * b[4])):
        try:
            etype = protos.entity(e["name"])["type"]
        except KeyError:
            etype = "?"
        color = LOGISTIC_COLORS.get(e["name"]) or TYPE_COLORS.get(etype, (100, 100, 100))
        px0, py0 = (x0 - minx) * scale, (y0 - miny) * scale
        px1, py1 = px0 + w * scale - 1, py0 + h * scale - 1
        dr.rectangle([px0 + 1, py0 + 1, px1 - 1, py1 - 1], fill=color, outline=(15, 15, 15))
        q = QUALITY_COLORS.get(e.get("quality", "normal"))
        if q:
            dr.rectangle([px0 + 1, py0 + 1, px1 - 1, py1 - 1], outline=q, width=2)
        cx, cy = (px0 + px1) / 2, (py0 + py1) / 2
        if etype in ("transport-belt", "underground-belt", "inserter", "splitter", "loader", "pump"):
            vx, vy = Direction.vector(d)
            if etype == "inserter":  # direction points at the pickup side; draw the item flow
                vx, vy = -vx, -vy
            r = scale * 0.35
            tip = (cx + vx * r, cy + vy * r)
            left = (cx - vx * r * 0.6 - vy * r * 0.6, cy - vy * r * 0.6 + vx * r * 0.6)
            right = (cx - vx * r * 0.6 + vy * r * 0.6, cy - vy * r * 0.6 - vx * r * 0.6)
            dr.polygon([tip, left, right], fill=(20, 20, 20))
            if etype == "underground-belt":
                dr.text((px0 + 2, py0), "U" if e.get("type") == "input" else "u", fill=(255, 255, 255), font=font)
        if w * h >= 4:
            label = e.get("recipe") or e["name"]
            rq = e.get("recipe_quality")
            text = _abbrev(label, max(3, int(w * 2.2)))
            dr.text((px0 + 3, py0 + 2), text, fill=(255, 255, 255), font=font)
            if rq and rq != "normal":
                dr.text((px0 + 3, py0 + 2 + scale // 2 + 2), rq[:4], fill=QUALITY_COLORS.get(rq) or (255, 255, 255), font=font)
            if e.get("items"):
                mods = sum(len(p["items"]["in_inventory"]) for p in e["items"])
                mq = e["items"][0]["id"].get("quality", "normal")
                dr.text((px0 + 3, py1 - scale // 2 - 3), f"{mods}M", fill=QUALITY_COLORS.get(mq) or (230, 230, 230), font=font)
        if e["name"] in ("requester-chest", "storage-chest") and e.get("request_filters"):
            f = e["request_filters"]["sections"][0].get("filters", [])
            if f:
                qc = QUALITY_COLORS.get(f[0].get("quality", "normal"))
                if qc:
                    dr.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=qc)
    img.save(path)
    return path
