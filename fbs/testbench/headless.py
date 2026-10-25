"""Thin wrapper around a Factorio headless install.

Everything the suite does in the real engine goes through here: assembling a
mod directory (the user's mods plus one generated helper mod), creating a map,
and running the game in benchmark mode for a fixed number of ticks.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

BUILTIN_MODS = ("base", "elevated-rails", "quality", "recycler", "space-age")
HELPER_MOD_NAME = "fbs-helper"


class HeadlessError(RuntimeError):
    pass


def find_factorio(explicit: str | os.PathLike | None = None) -> Path:
    """Return the factorio binary. Looks at the argument, $FBS_FACTORIO, then ./.factorio."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("FBS_FACTORIO"):
        candidates.append(Path(os.environ["FBS_FACTORIO"]))
    here = Path.cwd()
    candidates += [here / ".factorio", Path.home() / ".cache" / "fbs" / "factorio"]
    for c in candidates:
        if c.is_dir():
            c = c / "bin" / "x64" / "factorio"
        if c.is_file():
            return c.resolve()
    raise HeadlessError(
        "Factorio headless not found. Run scripts/setup_headless.sh or set FBS_FACTORIO "
        "to the install directory (the one containing bin/x64/factorio)."
    )


def factorio_root(binary: Path) -> Path:
    return binary.parent.parent.parent


def factorio_version(binary: Path) -> str:
    out = subprocess.run([str(binary), "--version"], capture_output=True, text=True, check=False).stdout
    m = re.search(r"Version: (\d+\.\d+\.\d+)", out)
    if not m:
        raise HeadlessError(f"could not read Factorio version from: {out[:200]}")
    return m.group(1)


@dataclass
class ModSet:
    """A mod directory to run the game with.

    ``source`` is the user's mods folder (with mod-list.json, mod-settings.dat
    and zips). When it is None, only the built-in mods listed in ``builtin``
    are enabled.
    """

    source: Path | None = None
    builtin: tuple[str, ...] = BUILTIN_MODS
    disable: tuple[str, ...] = ()
    extra_enabled: dict[str, bool] = field(default_factory=dict)

    def materialize(self, target: Path, helper_mod: Path | None) -> Path:
        target.mkdir(parents=True, exist_ok=True)
        mods: list[dict] = []
        if self.source:
            src = Path(self.source)
            for entry in src.iterdir():
                if entry.name in ("mod-list.json",):
                    continue
                if entry.name.startswith(HELPER_MOD_NAME):
                    continue
                dest = target / entry.name
                if dest.exists() or dest.is_symlink():
                    continue
                try:
                    dest.symlink_to(entry.resolve())
                except OSError:
                    if entry.is_dir():
                        shutil.copytree(entry, dest)
                    else:
                        shutil.copy2(entry, dest)
            ml = src / "mod-list.json"
            if ml.exists():
                mods = json.loads(ml.read_text(encoding="utf-8"))["mods"]
        else:
            mods = [{"name": m, "enabled": True} for m in self.builtin]
        mods = [m for m in mods if m["name"] != HELPER_MOD_NAME]
        for m in mods:
            if m["name"] in self.disable:
                m["enabled"] = False
        for name, enabled in self.extra_enabled.items():
            mods = [m for m in mods if m["name"] != name] + [{"name": name, "enabled": enabled}]
        if helper_mod is not None:
            dest = target / helper_mod.name
            if dest.exists() or dest.is_symlink():
                if dest.is_dir() and not dest.is_symlink():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            shutil.copytree(helper_mod, dest)
            mods.append({"name": HELPER_MOD_NAME, "enabled": True})
        (target / "mod-list.json").write_text(json.dumps({"mods": mods}, indent=2), encoding="utf-8")
        return target


def write_helper_mod(directory: Path, factorio_minor: str, control_lua: str, extra_files: dict[str, str] | None = None) -> Path:
    """Create the generated helper mod folder (unzipped mods are allowed)."""
    mod = directory / HELPER_MOD_NAME
    if mod.exists():
        shutil.rmtree(mod)
    mod.mkdir(parents=True)
    info = {
        "name": HELPER_MOD_NAME,
        "version": "0.0.1",
        "title": "fbs helper (generated)",
        "author": "factorio-blueprint-suite",
        "factorio_version": factorio_minor,
        "dependencies": ["base"],
    }
    (mod / "info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    (mod / "control.lua").write_text(control_lua, encoding="utf-8")
    for name, content in (extra_files or {}).items():
        (mod / name).write_text(content, encoding="utf-8")
    return mod


@dataclass
class RunResult:
    returncode: int
    seconds: float
    log: str
    script_output: Path


class Headless:
    def __init__(self, binary: str | os.PathLike | None = None, workdir: Path | None = None):
        self.binary = find_factorio(binary)
        self.root = factorio_root(self.binary)
        self.version = factorio_version(self.binary)
        self.minor = ".".join(self.version.split(".")[:2])
        self.workdir = Path(workdir or tempfile.mkdtemp(prefix="fbs-"))
        self.workdir.mkdir(parents=True, exist_ok=True)
        # private write-data dir: parallel runs do not fight over the lock file or script-output
        self.write_data = self.workdir / "write-data"
        self.write_data.mkdir(exist_ok=True)
        self.config = self.workdir / "config.ini"
        self.config.write_text(
            "[path]\nread-data=" + str(self.root / "data") + "\nwrite-data=" + str(self.write_data) + "\n",
            encoding="utf-8")

    @property
    def script_output(self) -> Path:
        return self.write_data / "script-output"

    def _run(self, args: list[str], timeout: float) -> RunResult:
        start = time.time()
        proc = subprocess.run([str(self.binary), "--config", str(self.config), *args], capture_output=True, text=True,
                              timeout=timeout, check=False)
        return RunResult(proc.returncode, time.time() - start, proc.stdout + proc.stderr, self.script_output)

    def create_map(self, path: Path, mod_dir: Path, map_gen: dict | None = None, map_settings: dict | None = None, timeout: float = 600) -> Path:
        args = ["--create", str(path), "--mod-directory", str(mod_dir)]
        if map_gen is not None:
            p = self.workdir / "map-gen-settings.json"
            p.write_text(json.dumps(map_gen), encoding="utf-8")
            args += ["--map-gen-settings", str(p)]
        if map_settings is not None:
            p = self.workdir / "map-settings.json"
            p.write_text(json.dumps(map_settings), encoding="utf-8")
            args += ["--map-settings", str(p)]
        res = self._run(args, timeout)
        if res.returncode != 0 or not path.exists():
            raise HeadlessError(f"map creation failed:\n{res.log[-3000:]}")
        return path

    def benchmark(self, save: Path, mod_dir: Path, ticks: int, timeout: float = 7200) -> RunResult:
        args = ["--benchmark", str(save), "--benchmark-ticks", str(ticks), "--mod-directory", str(mod_dir)]
        res = self._run(args, timeout)
        if res.returncode != 0:
            raise HeadlessError(f"benchmark run failed (exit {res.returncode}):\n{res.log[-4000:]}")
        errors = [l for l in res.log.splitlines() if "Error" in l and "ModManager" in l or "Failed to load mods" in l]
        if errors:
            raise HeadlessError("mod loading failed:\n" + "\n".join(errors[:20]))
        return res
