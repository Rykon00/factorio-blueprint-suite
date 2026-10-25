"""Command line interface: ``fbs <command>`` (or ``python -m fbs``)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import codec
from .protos import DEFAULT_CACHE, Prototypes


def _read_bp(arg: str) -> str:
    p = Path(arg)
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    if arg == "-":
        return sys.stdin.read().strip()
    return arg.strip()


def _protos(args) -> Prototypes:
    return Prototypes.load(args.protos)


def _kv(pairs: list[str]) -> dict[str, str]:
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise SystemExit(f"expected key=value, got {p!r}")
        k, v = p.split("=", 1)
        out[k] = v
    return out


def cmd_decode(args):
    data = codec.decode(_read_bp(args.blueprint))
    text = json.dumps(data, indent=1, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)


def cmd_encode(args):
    data = json.loads(Path(args.json).read_text(encoding="utf-8"))
    s = codec.encode(data)
    if args.output:
        Path(args.output).write_text(s, encoding="utf-8")
    else:
        print(s)


def cmd_info(args):
    data = codec.decode(_read_bp(args.blueprint))
    bp = data.get("blueprint")
    if not bp:
        print("blueprint book with", len(data.get("blueprint_book", {}).get("blueprints", [])), "entries")
        return
    ents = bp.get("entities", [])
    counts: dict[str, int] = {}
    for e in ents:
        key = e["name"] + (f"@{e['quality']}" if e.get("quality") else "")
        counts[key] = counts.get(key, 0) + 1
    xs = [e["position"]["x"] for e in ents] or [0]
    ys = [e["position"]["y"] for e in ents] or [0]
    print(f"label: {bp.get('label')}")
    print(f"version: {'.'.join(map(str, codec.int_to_version(bp.get('version', 0))))}")
    print(f"entities: {len(ents)}, size ~{max(xs) - min(xs) + 1:.0f} x {max(ys) - min(ys) + 1:.0f}")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {v:5d}  {k}")
    if bp.get("description"):
        print("\n" + bp["description"])


def cmd_render(args):
    from .render import render
    data = codec.decode(_read_bp(args.blueprint))
    out = render(data, _protos(args), args.output, scale=args.scale)
    print(out)


def cmd_protos(args):
    from .testbench.protodump import dump_prototypes
    out = dump_prototypes(Path(args.output), mods=Path(args.mods) if args.mods else None)
    print(f"wrote {out}")


def cmd_export(args):
    from .testbench.protodump import export_area
    area = tuple(float(x) for x in args.area.split(",")) if args.area else None
    res = export_area(Path(args.save), args.surface, mods=Path(args.mods) if args.mods else None, force=args.force, area=area)
    if not args.surface or res.get("error"):
        if args.surface and res.get("error"):
            print("error:", res["error"])
        print("surfaces in this save:")
        for s in res.get("surfaces", []):
            print(f"  {s['name']:40s} {s['entities']} entities")
        return
    if args.output:
        Path(args.output).write_text(res["blueprint"], encoding="utf-8")
        print(f"wrote {args.output} (force {res['force']}, area {res['area']})")
    else:
        print(res["blueprint"])


def _test_config(args, blueprint: str):
    from .testbench.runner import TestConfig
    return TestConfig(
        blueprint=blueprint,
        minutes=args.minutes,
        sample_minutes=args.sample_minutes,
        save=Path(args.save) if args.save else None,
        mods=Path(args.mods) if args.mods else None,
        research=args.research or ("keep" if args.save else "all"),
        tech_levels={k: int(v) for k, v in _kv(args.tech).items()},
        planet=args.planet,
        robots_per_roboport=args.robots,
    )


def _run_test(args, blueprint: str, out_dir: Path | None):
    from .testbench.runner import analyse, format_markdown, run
    raw = run(_test_config(args, blueprint))
    rep = analyse(raw, warmup_minutes=args.warmup)
    md = format_markdown(rep)
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
        (out_dir / "report-raw.json").write_text(json.dumps(raw), encoding="utf-8")
        (out_dir / "report.md").write_text(md, encoding="utf-8")
    return rep, md


def cmd_test(args):
    out = Path(args.output) if args.output else None
    _, md = _run_test(args, _read_bp(args.blueprint), out)
    print(md)


def cmd_gen(args):
    from .designs import DESIGNS, coerce_params
    from .render import render
    module = DESIGNS.get(args.design)
    if not module:
        raise SystemExit(f"unknown design {args.design!r}; available: {', '.join(DESIGNS)}")
    protos = _protos(args)
    params = coerce_params(module, _kv(args.param))
    bp, plan = module.build(protos, params)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    production = bp.without_tags("test")
    (out / "blueprint.txt").write_text(production.to_string(), encoding="utf-8")
    (out / "blueprint-test.txt").write_text(bp.to_string(), encoding="utf-8")
    (out / "plan.json").write_text(json.dumps(bp.meta, indent=1), encoding="utf-8")
    render(bp.to_dict(), protos, str(out / "preview.png"), scale=args.scale)
    print(f"{args.design}: {sum(bp.count().values())} entities -> {out}")
    print(json.dumps(bp.meta.get("plan", {}), indent=1))
    if args.test:
        _, md = _run_test(args, bp.to_string(), out)
        print(md)


def _add_test_args(p: argparse.ArgumentParser):
    p.add_argument("--minutes", type=float, default=30, help="game minutes to simulate (default 30)")
    p.add_argument("--sample-minutes", type=float, default=1)
    p.add_argument("--warmup", type=float, default=5, help="minutes ignored for rates (default 5)")
    p.add_argument("--mods", help="your Factorio mods folder (mod-list.json, mod-settings.dat, zips)")
    p.add_argument("--save", help="run inside a copy of this save (uses its research unless --research all)")
    p.add_argument("--research", choices=["all", "keep"], help="default: keep with --save, else all")
    p.add_argument("--tech", action="append", metavar="NAME=LEVELS", help="researched levels, e.g. low-density-structure-productivity=3")
    p.add_argument("--planet", help="copy surface properties of this planet (e.g. vulcanus)")
    p.add_argument("--robots", type=int, default=0, help="logistic robots inserted into every roboport")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="fbs", description="Generate, inspect and test Factorio blueprints in the real engine.")
    ap.add_argument("--protos", default=str(DEFAULT_CACHE), help=f"prototype dump (default {DEFAULT_CACHE})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("decode", help="blueprint string -> JSON")
    p.add_argument("blueprint", help="string, file or - for stdin")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_decode)

    p = sub.add_parser("encode", help="JSON -> blueprint string")
    p.add_argument("json")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_encode)

    p = sub.add_parser("info", help="summary of a blueprint")
    p.add_argument("blueprint")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("render", help="PNG preview")
    p.add_argument("blueprint")
    p.add_argument("-o", "--output", default="preview.png")
    p.add_argument("--scale", type=int, default=12)
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("protos", help="dump prototype data from the game (needs headless)")
    p.add_argument("--mods", help="mods folder to load (default: vanilla + Space Age)")
    p.add_argument("-o", "--output", default=str(DEFAULT_CACHE))
    p.set_defaults(func=cmd_protos)

    p = sub.add_parser("export", help="export entities from a save as a blueprint (e.g. a blueprint-sandbox lab)")
    p.add_argument("save")
    p.add_argument("--surface", help="surface name; omit to list surfaces")
    p.add_argument("--force", help="default: the force with most entities in the area")
    p.add_argument("--area", help="x1,y1,x2,y2 (default: everything of that force on the surface)")
    p.add_argument("--mods", help="mods folder the save needs")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("test", help="build a blueprint in the headless game, run it and report")
    p.add_argument("blueprint")
    p.add_argument("-o", "--output", help="directory for report.md / report.json")
    _add_test_args(p)
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("gen", help="generate a parametric design")
    p.add_argument("design")
    p.add_argument("-p", "--param", action="append", metavar="KEY=VALUE")
    p.add_argument("-o", "--output", default="out")
    p.add_argument("--scale", type=int, default=12)
    p.add_argument("--test", action="store_true", help="also run the testbench on the test variant")
    _add_test_args(p)
    p.set_defaults(func=cmd_gen)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
