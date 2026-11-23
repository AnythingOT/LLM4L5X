import pytest
import yaml

import lint
from library import LibraryError, load_block, load_library
from plant import load_plant
from scenario import SimBackend, parse_scenarios, report, run_scenarios

LIB = load_library()
EXAMPLES = {"Motor": {"name": "P101"}, "Valve2Pos": {"name": "XV101"},
            "AlarmLatch": {"name": "LT101_HH_ALM", "cond": "LT101_HH"}}


@pytest.mark.parametrize("block", sorted(EXAMPLES))
def test_every_block_passes_its_own_scenarios_with_its_own_plant(block):
    inst = LIB[block].instantiate(EXAMPLES[block])
    plant = yaml.safe_dump({"devices": [inst.plant]}) if inst.plant else None
    res = run_scenarios(parse_scenarios(inst.scenarios),
                        lambda: SimBackend(inst.rungs, plant=load_plant(plant) if plant else None))
    assert res and all(r.passed for r in res), "\n".join(report(res))


@pytest.mark.parametrize("block", sorted(EXAMPLES))
def test_block_rungs_are_clean_and_commented(block):
    inst = LIB[block].instantiate(EXAMPLES[block])
    types = {t.name: t.datatype for t in inst.tags}
    assert [f.code for f in lint.check_rungs(inst.rungs, types) if f.severity in ("critical", "error")] == []
    assert all(r.comment for r in inst.rungs)


def test_defaults_build_names_from_the_instance_and_can_be_overridden():
    inst = LIB["Motor"].instantiate({"name": "P101", "running": "P101_Run_FB", "fts_ms": 8000})
    assert inst.values["cmd"] == "P101_Cmd" and inst.values["running"] == "P101_Run_FB"
    from core.rung import format_rung
    assert format_rung(inst.rungs[1]) == "XIC(P101_Cmd)XIO(P101_Run_FB)TON(P101_FTS_TMR,8000,0);"
    assert inst.plant == {"name": "P101", "type": "motor", "cmd": "P101_Cmd", "running": "P101_Run_FB",
                          "start_ms": 1000.0}
    assert inst.rungs[0].comment == "P101: start/stop with seal-in; a failure drops the command"


def test_a_mis_set_instance_fails_its_own_scenarios():
    """The block's own scenarios catch a mistake in the block: here a fail timer too short for the motor."""
    inst = LIB["Motor"].instantiate({"name": "P101", "fts_ms": 500})          # motor needs 1000 ms to start
    plant = yaml.safe_dump({"devices": [inst.plant]})
    res = {r.id: r.passed for r in run_scenarios(parse_scenarios(inst.scenarios),
                                                 lambda: SimBackend(inst.rungs, plant=load_plant(plant)))}
    assert res["P101-OK"] is False and res["P101-RUN"] is False


@pytest.mark.parametrize("given, msg", [
    ({}, "name is required"),
    ({"name": "P101", "colour": "red"}, "no parameter colour"),
    ({"name": "P1 01"}, "is not a tag name or a number"),
    ({"name": "P101", "fts_ms": "5s; DROP"}, "is not a tag name or a number"),
])
def test_instance_errors_say_what_to_fix(given, msg):
    with pytest.raises(LibraryError, match=msg):
        LIB["Motor"].instantiate(given)


@pytest.mark.parametrize("text, msg", [
    ("name: X", "at least name and rungs"),
    ("name: X\nparams: {name: {}}\nrungs: ['XIC({a})OTE({name});']", "not a parameter"),
    ("name: X\nrungs: ['XIC(a)OTE(b);']", "every block takes a name"),
    ("name: X\nparams: {name: {}}\nrungs: ['XIC(a)OTE({name}']", "does not parse"),
    ("name: X\nparams: {name: {}}\nrungs: ['XIC(a)OTE({name});', 'XIC(b)OTE({name});']", "fail rule"),
    ("name: X\ncolour: red\nparams: {name: {}}\nrungs: ['XIC(a)OTE({name});']", "unknown colour"),
])
def test_a_broken_block_is_refused_when_loaded(text, msg):
    with pytest.raises(LibraryError, match=msg):
        load_block(text)


def test_a_company_block_replaces_the_starter_of_the_same_name(tmp_path):
    (tmp_path / "motor.yaml").write_text("name: Motor\nversion: '7.2'\nparams: {name: {}}\n"
                                         "rungs: ['XIC({name}_Start)OTE({name}_Cmd);']\n")
    lib = load_library(tmp_path)
    assert lib["Motor"].version == "7.2" and lib["Valve2Pos"].version == "1.0"
