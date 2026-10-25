# factorio-blueprint-suite (`fbs`)

Generate Factorio blueprints in Python and test them in the **real headless engine** before you import them.

```
fbs gen lds-shuffle -p normal_foundries=12 --test --robots 60
```

writes a blueprint string, a preview PNG, the production plan, and a test report. The report comes from
building the blueprint on an empty lab surface, powering it, running it for 30 minutes of game time, and
measuring what came out.

## What is in the box

| piece | what it does |
|---|---|
| `fbs.codec` | blueprint string <-> JSON |
| `fbs.model.Blueprint` | place entities by top-left tile; catches overlaps; writes recipes + recipe quality, module insert plans, logistic requests, storage filters, inserter / splitter filters, circuit conditions, wires in the exact Factorio 2.1 format |
| `fbs.protos` | prototype data (sizes, fluid connections, recipes, module effects, qualities) dumped from the game, **including your mods** |
| `fbs.render` | top-down PNG preview (footprints, quality colours, flow arrows) |
| `fbs.testbench` | headless runner: build -> power -> robots -> run N minutes -> report |
| `fbs.designs` | parametric designs (`lds-shuffle` so far) |

## Setup

```bash
pip install -e .                    # Python >= 3.10, Pillow
scripts/setup_headless.sh 2.1.23    # free headless server, Linux x86-64 only
fbs protos --mods ~/path/to/Factorio/mods   # optional: prototype dump with your mods
```

Without `fbs protos` the bundled dump (vanilla 2.1.23 + Space Age) is used.
`fbs` finds the game via `./.factorio`, `$FBS_FACTORIO` or `~/.cache/fbs/factorio`.

## Commands

```bash
fbs info   <bp>                     # entity counts, size, description
fbs decode <bp> -o bp.json          # <bp> = string, file, or - for stdin
fbs encode bp.json -o bp.txt
fbs render <bp> -o preview.png
fbs export save.zip                 # list surfaces in a save
fbs export save.zip --surface bpsb-lab-p-NAME --mods MODS -o lab.txt   # blueprint from a sandbox lab
fbs test   <bp> [options]           # run any blueprint in the engine
fbs gen    <design> -p key=value ... [--test options]
```

### Test options

| option | meaning |
|---|---|
| `--minutes 30` | game minutes to simulate (the headless server runs faster than real time) |
| `--warmup 5` | minutes ignored when computing rates |
| `--mods DIR` | your mods folder (`mod-list.json`, `mod-settings.dat`, zips); mod settings are respected |
| `--save SAVE` | run inside a copy of your save, so the force has **your** research; the blueprint goes on a new surface `fbs-lab` |
| `--research all/keep` | default `keep` with `--save`, otherwise `all` |
| `--tech NAME=LEVELS` | e.g. `--tech low-density-structure-productivity=3` |
| `--planet vulcanus` | copy the planet's surface properties onto the lab surface |
| `--robots 60` | logistic robots inserted into every roboport |

The testbench supplies power itself (one electric-energy-interface per electric network). Inputs and outputs
are whatever the blueprint contains, so test variants carry infinity chests / pipes. Designs tag those
entities with `test`, and `fbs gen` writes both variants: `blueprint.txt` (production) and
`blueprint-test.txt`.

### The report

* legendary (or any) output per hour, from the force's production statistics of the lab surface
* machine utilisation per machine, recipe and recipe quality, with the stall reasons (missing input, output
  blocked, no power, ...)
* containers whose stock keeps growing, and containers that are full (a jam that is coming)
* machines that were stalled more than half of the time, with positions
* problems: entities that could not be built, unpowered entities, separate power networks, mods that broke
  the setup

Example (the generated LDS shuffle, vanilla + Space Age, 30 min):

```
## Legendary output per hour
- copper-plate: 650
- plastic-bar: 110
- steel-plate: 84

| machine | recipe | working | main stalls |
| foundry | casting-low-density-structure@normal | 98% | missing item input 2% |
| recycler | - | 86% | no input 14% |
```

## Designs

### `lds-shuffle`

Normal plastic in; legendary plastic, copper and steel out. Logistic-bot cells, so it scales by counts:
foundries per quality tier (requester for that tier's plastic -> foundry -> passive provider), LDS
recyclers (request LDS of every quality, drop the output into an active provider), void recyclers that
recycle non-legendary copper / steel into themselves (with quality modules they add more legendary), and
filtered storage for the legendary outputs.

The planner computes the tier sizes, recycler counts and expected output from the module setup, the
foundry productivity (`lds_productivity_research`) and the real recipe data, using the same quality roll
the engine uses (`LuaQualityPrototype::get_roll_chances`).

Parameters (`-p key=value`): `normal_foundries`, `foundry_modules`, `recycler_modules`, `void_modules`
(e.g. `quality-module-3@legendary`), `lds_productivity_research`, `recycle_legendary_lds`,
`foundries=12,2,1,1`, `lds_recyclers`, `void_recyclers`, `roboport_spacing`, `robots_per_roboport`,
`inserter`, `foundry`, `headroom`.

Ports on the left edge: plastic input chests at x=2, y=12..13 (an inserter picks up from x=0), molten iron
at (0, 8), molten copper at (0, 10).

## Writing a design

```python
from fbs.model import Blueprint
from fbs.protos import Prototypes

protos = Prototypes.load()
bp = Blueprint(protos, "my build")
bp.place("requester-chest", 0, 0, requests=[("plastic-bar@rare", 20)])
bp.place("bulk-inserter", 0, 1, "north")          # direction = pickup side
f = bp.place("foundry", -2, 2, recipe="casting-low-density-structure", recipe_quality="rare",
             modules=["quality-module-3@legendary"] * 4)
bp.place("infinity-chest", 5, 0, tag="test", infinity_items=[("plastic-bar@rare", 100)])
print(bp.to_string())                              # with test sources
print(bp.without_tags("test").to_string())         # production version
```

Put it in `fbs/designs/`, register it in `fbs/designs/__init__.py`, and `fbs gen` picks it up.

## Notes

* Factorio headless exists only for Linux x86-64 (not Raspberry Pi / ARM).
* Ghost revive drops infinity-chest / infinity-pipe settings; the testbench re-applies them.
* Mods that replace entities in their build handler (for example quality variants) are supported; the
  testbench raises `on_entity_revived` and inserts modules into the replacement. Use `raise_events=False`
  in `TestConfig` to build vanilla entities.

## Development

```bash
pip install -e .[dev]
pytest
```

The unit tests need no game. `fbs test` / `fbs gen --test` need the headless server.
