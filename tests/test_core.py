import json
from pathlib import Path

import pytest

from fbs import codec
from fbs.geometry import Direction, rotate_vec
from fbs.model import Blueprint, OverlapError
from fbs.protos import Prototypes
from fbs.quality import roll

FIXTURE = Path(__file__).parent / "fixtures" / "prototypes-mini.json"


@pytest.fixture(scope="module")
def protos():
    return Prototypes(json.loads(FIXTURE.read_text()))


def test_codec_roundtrip():
    data = {"blueprint": {"item": "blueprint", "entities": [{"entity_number": 1, "name": "pipe", "position": {"x": 0.5, "y": 0.5}}], "version": codec.version_to_int(2, 1, 0)}}
    s = codec.encode(data)
    assert s[0] == "0"
    assert codec.decode(s) == data


def test_version_packing():
    v = codec.version_to_int(2, 1, 23, 1)
    assert codec.int_to_version(v) == (2, 1, 23, 1)


def test_rotate_vec_matches_recycler_output():
    # recycler drops its output at (-0.35, -2.3) when facing north
    assert rotate_vec((-0.35, -2.3), Direction.EAST) == pytest.approx((2.3, -0.35))
    assert rotate_vec((-0.35, -2.3), Direction.SOUTH) == pytest.approx((0.35, 2.3))


def test_roll_matches_engine():
    # values from LuaQualityPrototype::get_roll_chances(0.16) in Factorio 2.1.23
    assert roll(0, 0.16) == pytest.approx([0.84, 0.144, 0.0144, 0.00144, 0.00016])
    assert roll(3, 0.16) == pytest.approx([0, 0, 0, 0.84, 0.16])
    assert roll(4, 0.16) == pytest.approx([0, 0, 0, 0, 1])


def test_place_uses_top_left_and_detects_overlap(protos):
    bp = Blueprint(protos)
    f = bp.place("foundry", 0, 0)
    assert f.position == (2.5, 2.5)
    r = bp.place("recycler", 10, 0, Direction.EAST)  # 4x2 when facing east
    assert r.position == (12.0, 1.0)
    with pytest.raises(OverlapError):
        bp.place("pipe", 4, 4)


def test_entity_settings_serialise_like_the_game(protos):
    bp = Blueprint(protos)
    f = bp.place("foundry", 0, 0, recipe="casting-low-density-structure", recipe_quality="uncommon",
                 modules=["quality-module-3@epic"] * 4)
    req = bp.place("requester-chest", 6, 0, requests=[("plastic-bar@rare", 50)])
    st = bp.place("storage-chest", 7, 0, storage_filter="copper-plate@legendary")
    ins = bp.place("bulk-inserter", 8, 0, Direction.NORTH, filters=["steel-plate@legendary"], filter_mode="blacklist",
                   circuit_condition={"first_signal": {"type": "virtual", "name": "signal-anything"}, "constant": 2000, "comparator": ">"})
    sp = bp.place("turbo-splitter", 10, 0, splitter_filter="plastic-bar@rare", output_priority="left")
    bp.wire(ins, req)
    d = bp.to_dict()["blueprint"]
    ents = {e["name"]: e for e in d["entities"]}
    assert ents["foundry"]["recipe_quality"] == "uncommon"
    assert ents["foundry"]["items"] == [{"id": {"name": "quality-module-3", "quality": "epic"},
                                          "items": {"in_inventory": [{"inventory": 4, "stack": i} for i in range(4)]}}]
    assert ents["requester-chest"]["request_filters"]["sections"][0]["filters"][0] == {
        "index": 1, "name": "plastic-bar", "quality": "rare", "comparator": "=", "count": 50}
    assert ents["storage-chest"]["request_filters"]["sections"][0]["filters"][0]["count"] == 0
    assert ents["bulk-inserter"]["filter_mode"] == "blacklist" and ents["bulk-inserter"]["use_filters"] is True
    assert ents["bulk-inserter"]["control_behavior"]["circuit_condition"]["constant"] == 2000
    assert ents["turbo-splitter"]["filter"] == {"name": "plastic-bar", "quality": "rare", "comparator": "="}
    assert d["wires"] == [[ins.number, 1, req.number, 1]]


def test_without_tags_drops_test_entities_and_remaps_wires(protos):
    bp = Blueprint(protos)
    a = bp.place("infinity-chest", 0, 0, tag="test", infinity_items=[("plastic-bar", 100)])
    b = bp.place("requester-chest", 2, 0)
    c = bp.place("bulk-inserter", 3, 0)
    bp.wire(b, c)
    bp.wire(a, b)
    prod = bp.without_tags("test")
    names = [e.name for e in prod.entities]
    assert "infinity-chest" not in names
    assert prod.wires == [[1, 1, 2, 1]]


def test_lds_plan_is_consistent(protos):
    from fbs.designs import lds_shuffle as L
    pl = L.plan(protos, L.Params())
    assert pl.foundries[0] == 12
    assert all(n >= 1 for n in pl.foundries)
    # 12 foundries at 3.2 speed, 15 s recipe -> 2.56 crafts/s
    assert pl.flows["crafts_per_s"][0] == pytest.approx(2.56)
    assert pl.legendary_per_hour["plastic-bar"] > 0
    bp, _ = L.build(protos, L.Params(normal_foundries=4))
    s = bp.to_string()
    assert codec.decode(s)["blueprint"]["entities"]


def test_find_factorio_uses_dot_factorio(tmp_path, monkeypatch):
    from fbs.testbench.headless import find_factorio
    binary = tmp_path / "install" / "factorio" / "bin" / "x64" / "factorio"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    (tmp_path / ".factorio").symlink_to(tmp_path / "install" / "factorio")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FBS_FACTORIO", raising=False)
    assert find_factorio() == binary.resolve()


def test_grid_snapping_and_corner_nodes(protos):
    from fbs.grid import Cell, add_grid, snap_to_grid
    bp = Blueprint(protos)
    ents = add_grid(bp, [Cell(0, 0), Cell(1, 0)])
    # two cells share one corner column: 6 roboports, not 8
    assert sum(1 for e in ents if e.name == "roboport") == 6
    snap_to_grid(bp)
    d = bp.to_dict()["blueprint"]
    assert d["snap-to-grid"] == {"x": 50, "y": 50} and d["absolute-snapping"] is True
    assert d["position-relative-to-grid"] == {"x": 25, "y": 25}


def test_auto_power_covers_everything(protos):
    from fbs.power import auto_power
    bp = Blueprint(protos)
    anchor = bp.place("medium-electric-pole", 0, 0)
    for i in range(6):
        bp.place("electromagnetic-plant", 4 + i * 6, 4)
    poles = auto_power(bp, (2, 2, 45, 20), connect_to=[anchor])
    assert poles
    # every placed pole is wired into the tree
    wired = {w[0] for w in bp.wires} | {w[2] for w in bp.wires}
    assert all(p.number in wired for p in poles)


def test_em_upcycler_plan_and_layout(protos):
    from fbs.designs import em_upcycler as U
    pl = U.plan(protos, U.Params(normal_iron_cells=2))
    assert pl.iron_cells[0] == 2 and all(n >= 1 for n in pl.iron_cells)
    assert pl.legendary_per_hour["iron-plate"] > 0 and pl.legendary_per_hour["copper-plate"] > 0
    bp, _ = U.build(protos, U.Params(normal_iron_cells=2))
    assert bp.meta["grid_cells"] == [(0, 0)]
    prod = bp.without_tags("test")
    assert not any(e.name.startswith("infinity") for e in prod.entities)
    # everything except the grid nodes stays inside the cell interior 3..46
    for e in prod.entities:
        if e.tag == "grid":
            continue
        assert all(3 <= t[0] <= 46 and 3 <= t[1] <= 46 for t in e.tiles), (e.name, e.position)


@pytest.mark.parametrize("design", ["brick-upcycler", "raw-upcycler", "steel-upcycler", "self-recycler", "em-upcycler"])
def test_grid_designs_build_inside_their_cells(design):
    from fbs.designs import DESIGNS
    full = Prototypes.load()  # bundled vanilla + Space Age dump
    bp, _ = DESIGNS[design].build(full)
    prod = bp.without_tags("test")
    cells = bp.meta["grid_cells"]
    assert prod.extra.get("absolute-snapping") is True
    for e in prod.entities:
        if e.tag == "grid":
            continue
        ok = any(cx * 50 + 3 <= t[0] <= cx * 50 + 48 and cy * 50 + 3 <= t[1] <= cy * 50 + 46
                 for t in e.tiles for cx, cy in cells)
        assert ok, (design, e.name, e.position)
    assert codec.decode(prod.to_string())["blueprint"]["entities"]
