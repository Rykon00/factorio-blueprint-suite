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
