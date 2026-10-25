"""Dump prototype data from the real game for the configured mod set."""

from __future__ import annotations

import json
import shutil
import tempfile
from importlib import resources
from pathlib import Path

from .headless import Headless, HeadlessError, ModSet, write_helper_mod


def dump_prototypes(out: Path, mods: Path | None = None, headless: Headless | None = None) -> Path:
    hl = headless or Headless()
    work = Path(tempfile.mkdtemp(prefix="fbs-protos-"))
    try:
        lua = resources.files("fbs.testbench").joinpath("lua", "protodump.lua").read_text(encoding="utf-8")
        helper = write_helper_mod(work / "helper-src", hl.minor, lua)
        mod_dir = ModSet(source=mods, disable=("even-distribution",) if mods else ()).materialize(work / "mods", helper)
        save = hl.create_map(work / "protos.zip", mod_dir)
        target = hl.script_output / "fbs-prototypes.json"
        if target.exists():
            target.unlink()
        res = hl.benchmark(save, mod_dir, 2)
        if not target.exists():
            raise HeadlessError("prototype dump missing. Log tail:\n" + res.log[-3000:])
        data = json.loads(target.read_text(encoding="utf-8"))
        data["factorio_version"] = hl.version
        data["mods"] = sorted(p.name for p in mod_dir.iterdir())
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data), encoding="utf-8")
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


def export_area(save: Path, surface: str | None, mods: Path | None = None, force: str | None = None,
                area: tuple[float, float, float, float] | None = None, headless: Headless | None = None) -> dict:
    """Export entities of a save as a blueprint string (run with surface=None to list surfaces)."""
    hl = headless or Headless()
    work = Path(tempfile.mkdtemp(prefix="fbs-export-"))
    try:
        conf = {"surface": surface, "force": force,
                "area": [[area[0], area[1]], [area[2], area[3]]] if area else None}
        lua = "local FBS_CONFIG_JSON = [==[" + json.dumps(conf) + "]==]\n" + \
            resources.files("fbs.testbench").joinpath("lua", "export.lua").read_text(encoding="utf-8")
        helper = write_helper_mod(work / "helper-src", hl.minor, lua)
        mod_dir = ModSet(source=mods, disable=("even-distribution",) if mods else ()).materialize(work / "mods", helper)
        copy = work / "save.zip"
        shutil.copy2(save, copy)
        target = hl.script_output / "fbs-export.json"
        if target.exists():
            target.unlink()
        res = hl.benchmark(copy, mod_dir, 2)
        if not target.exists():
            raise HeadlessError("export produced no output. Log tail:\n" + res.log[-3000:])
        return json.loads(target.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(work, ignore_errors=True)
