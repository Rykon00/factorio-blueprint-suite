"""Run a blueprint in the real engine and turn the raw samples into a report."""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from .. import codec
from .headless import Headless, HeadlessError, ModSet, write_helper_mod

STALL_STATES = {
    "full_output": "output blocked",
    "waiting_for_space_in_destination": "output blocked",
    "item_ingredient_shortage": "missing item input",
    "fluid_ingredient_shortage": "missing fluid input",
    "no_ingredients": "no input",
    "no_input_fluid": "no fluid",
    "low_power": "low power",
    "no_power": "no power",
    "no_recipe": "no recipe",
    "disabled_by_control_behavior": "disabled by circuit",
    "no_minable_resources": "nothing to mine",
}


def _lua(name: str) -> str:
    return resources.files("fbs.testbench").joinpath("lua", name).read_text(encoding="utf-8")


@dataclass
class TestConfig:
    blueprint: str
    minutes: float = 30.0
    sample_minutes: float = 1.0
    save: Path | None = None          # run inside a copy of this save (keeps its research)
    mods: Path | None = None          # user mods directory; None = vanilla + Space Age
    research: str = "all"             # "all" or "keep" (keep = the save's research)
    tech_levels: dict[str, int] = field(default_factory=dict)
    planet: str | None = None         # copy surface properties from this planet
    robots_per_roboport: int = 0
    half_extent: int | None = None
    origin: tuple[int, int] = (0, 0)
    force: str = "player"
    raise_events: bool = True         # let mods react to the built entities (on_entity_revived)
    extra_lua: str = ""               # appended to the testbench control.lua (debug hooks)

    def lua_config(self, half_extent: int) -> dict[str, Any]:
        ticks = int(self.minutes * 3600)
        return {
            "blueprint": self.blueprint,
            "ticks": ticks,
            "sample_interval": max(60, int(self.sample_minutes * 3600)),
            "research": self.research,
            "tech_levels": self.tech_levels or {},
            "planet": self.planet,
            "robots_per_roboport": self.robots_per_roboport,
            "half_extent": half_extent,
            "origin": list(self.origin),
            "force": self.force,
            "raise_events": self.raise_events,
        }


def blueprint_half_extent(bp_string: str, margin: int = 24) -> int:
    data = codec.decode(bp_string)
    ents = data["blueprint"]["entities"]
    xs = [e["position"]["x"] for e in ents]
    ys = [e["position"]["y"] for e in ents]
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    return int(span / 2 + margin)


def run(cfg: TestConfig, headless: Headless | None = None, keep_workdir: bool = False) -> dict[str, Any]:
    hl = headless or Headless()
    work = Path(tempfile.mkdtemp(prefix="fbs-run-"))
    try:
        half = cfg.half_extent or blueprint_half_extent(cfg.blueprint)
        conf = cfg.lua_config(half)
        lua = "local FBS_CONFIG_JSON = [==[" + json.dumps(conf) + "]==]\n" + _lua("testbench.lua") + "\n" + cfg.extra_lua
        helper = write_helper_mod(work / "helper-src", hl.minor, lua)
        modset = ModSet(source=cfg.mods, disable=("even-distribution",) if cfg.mods else ())
        mod_dir = modset.materialize(work / "mods", helper)

        if cfg.save:
            save = work / "base.zip"
            shutil.copy2(cfg.save, save)
        else:
            save = hl.create_map(work / "base.zip", mod_dir, map_gen={"peaceful_mode": True, "no_enemies_mode": True})

        report_path = hl.script_output / "fbs-report.json"
        if report_path.exists():
            report_path.unlink()
        ticks = int(cfg.minutes * 3600) + int(cfg.sample_minutes * 3600) + 5
        try:
            res = hl.benchmark(save, mod_dir, ticks)
            seconds, log = res.seconds, res.log
        except HeadlessError as err:
            if not report_path.exists():
                raise
            seconds, log = 0.0, str(err)
        if not report_path.exists():
            raise HeadlessError("testbench produced no report. Log tail:\n" + log[-3000:])
        raw = json.loads(report_path.read_text(encoding="utf-8"))
        # Lua serialises empty tables as {}; normalise list-like fields
        for key in ("problems", "samples", "crafters"):
            if isinstance(raw.get(key), dict):
                raw[key] = list(raw[key].values())
        if not raw.get("finished"):
            raw.setdefault("problems", []).append("run aborted early; log tail: " + log[-800:])
        raw["wall_seconds"] = round(seconds, 1)
        raw["factorio_version"] = hl.version
        return raw
    finally:
        if not keep_workdir:
            shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------- analysis

def _rate_per_hour(a: dict[str, float], b: dict[str, float], minutes: float) -> dict[str, float]:
    if minutes <= 0:
        return {}
    keys = set(a) | set(b)
    return {k: (b.get(k, 0) - a.get(k, 0)) * 60.0 / minutes for k in keys if b.get(k, 0) - a.get(k, 0) > 0}


def analyse(raw: dict[str, Any], warmup_minutes: float = 5.0) -> dict[str, Any]:
    samples = raw.get("samples", [])
    out: dict[str, Any] = {
        "problems": list(raw.get("problems", [])),
        "build": raw.get("build", {}),
        "finished": raw.get("finished", False),
        "wall_seconds": raw.get("wall_seconds"),
        "factorio_version": raw.get("factorio_version"),
    }
    if len(samples) < 2:
        out["problems"].append("not enough samples to compute rates")
        return out
    last = samples[-1]
    total_min = last["tick"] / 3600.0
    # steady-state window: skip warm-up if the run is long enough
    start = samples[0]
    for s in samples:
        if s["tick"] / 3600.0 >= min(warmup_minutes, total_min / 3):
            start = s
            break
    window = (last["tick"] - start["tick"]) / 3600.0
    out["minutes_simulated"] = round(total_min, 2)
    out["window_minutes"] = round(window, 2)
    out["produced_per_hour"] = dict(sorted(_rate_per_hour(start["produced"], last["produced"], window).items()))
    out["consumed_per_hour"] = dict(sorted(_rate_per_hour(start.get("consumed", {}), last.get("consumed", {}), window).items()))
    # stock trends
    trend = {}
    for k in set(start["stock"]) | set(last["stock"]):
        a, b = start["stock"].get(k, 0), last["stock"].get(k, 0)
        trend[k] = {"start": a, "end": b, "per_hour": round((b - a) * 60.0 / window, 1) if window else 0}
    out["stock"] = dict(sorted(trend.items()))
    out["full_containers_end"] = last.get("full_containers", [])
    out["items_on_ground_end"] = last.get("items_on_ground", 0)
    # machine utilisation per (name, recipe, quality)
    groups: dict[str, dict[str, int]] = {}
    for s in samples:
        if s["tick"] < start["tick"]:
            continue
        for key, counts in s.get("status", {}).items():
            g = groups.setdefault(key, {})
            for st, n in counts.items():
                g[st] = g.get(st, 0) + n
    util = {}
    for key, counts in groups.items():
        total = sum(counts.values())
        working = counts.get("working", 0) + counts.get("normal", 0)
        reasons = {STALL_STATES.get(k, k): round(v / total, 3) for k, v in counts.items() if k not in ("working", "normal")}
        util[key] = {"working": round(working / total, 3) if total else 0, "stalls": dict(sorted(reasons.items(), key=lambda kv: -kv[1]))}
    out["utilisation"] = dict(sorted(util.items()))
    # individual machines that are stalled most of the time
    stalled = []
    for c in raw.get("crafters", []):
        n = max(1, c.get("samples", 1))
        working = (c["counts"].get("working", 0) + c["counts"].get("normal", 0)) / n
        if working < 0.5:
            worst = max(((k, v) for k, v in c["counts"].items() if k not in ("working", "normal")), key=lambda kv: kv[1], default=("?", 0))
            stalled.append({"name": c["name"], "position": c["position"], "recipe": c.get("recipe"), "recipe_quality": c.get("recipe_quality"),
                            "working": round(working, 2), "main_stall": STALL_STATES.get(worst[0], worst[0])})
    out["mostly_stalled_machines"] = sorted(stalled, key=lambda s: (s["recipe"] or "", s["position"][0], s["position"][1]))
    # predictions: containers filling up
    warnings = []
    for c in out["full_containers_end"]:
        warnings.append(f"{c['name']} at ({c['position'][0]}, {c['position'][1]}) is {c['used']}/{c['slots']} slots full")
    if out["items_on_ground_end"]:
        warnings.append(f"{out['items_on_ground_end']} item stacks lying on the ground")
    for name, u in (last.get("unpowered") or {}).items():
        warnings.append(f"{u['count']}x {name} without enough power, e.g. at {u['positions'][0]}")
    out["warnings"] = warnings
    return out


def format_markdown(rep: dict[str, Any], highlight_quality: str = "legendary") -> str:
    lines = ["# Testbench report", ""]
    lines.append(f"Simulated {rep.get('minutes_simulated', 0)} min game time (steady-state window {rep.get('window_minutes', 0)} min), "
                 f"wall time {rep.get('wall_seconds')} s, Factorio {rep.get('factorio_version')}.")
    b = rep.get("build", {})
    if b:
        lines.append(f"Built {b.get('built')}/{b.get('expected_entities')} entities, {b.get('electric_networks', '?')} electric network(s).")
    lines.append("")
    if rep.get("problems"):
        lines.append("## Problems")
        lines += [f"- {p}" for p in rep["problems"]]
        lines.append("")
    if rep.get("warnings"):
        lines.append("## Warnings")
        lines += [f"- {w}" for w in rep["warnings"]]
        lines.append("")
    prod = rep.get("produced_per_hour", {})
    hi = {k: v for k, v in prod.items() if k.endswith("@" + highlight_quality)}
    if hi:
        lines.append(f"## {highlight_quality.capitalize()} output per hour")
        lines += [f"- {k.split('@')[0]}: {v:,.0f}" for k, v in sorted(hi.items(), key=lambda kv: -kv[1])]
        lines.append("")
    lines.append("## Machine utilisation")
    lines.append("| machine | recipe | working | main stalls |")
    lines.append("|---|---|---|---|")
    for key, u in rep.get("utilisation", {}).items():
        name, recipe, q = (key.split("|") + ["", ""])[:3]
        stalls = ", ".join(f"{k} {v:.0%}" for k, v in list(u["stalls"].items())[:2])
        lines.append(f"| {name} | {recipe}{'@' + q if q else ''} | {u['working']:.0%} | {stalls} |")
    lines.append("")
    growing = {k: v for k, v in rep.get("stock", {}).items() if v["per_hour"] > 0}
    if growing:
        lines.append("## Growing stock (containers)")
        lines.append("| item | start | end | per hour |")
        lines.append("|---|---|---|---|")
        for k, v in sorted(growing.items(), key=lambda kv: -kv[1]["per_hour"]):
            lines.append(f"| {k} | {v['start']} | {v['end']} | {v['per_hour']:+,.0f} |")
        lines.append("")
    if rep.get("mostly_stalled_machines"):
        lines.append("## Machines stalled more than half the time")
        for m in rep["mostly_stalled_machines"][:40]:
            lines.append(f"- {m['name']} at ({m['position'][0]}, {m['position'][1]}) {m['recipe'] or ''}"
                         f"{'@' + m['recipe_quality'] if m.get('recipe_quality') else ''}: working {m['working']:.0%}, mostly {m['main_stall']}")
        lines.append("")
    return "\n".join(lines)
