import pytest

from core.rung import parse_rung
from gui.energise import EnergiseError, load
from l5x.writer import write_routine
from test_scenario import PLANT, SCENARIOS, TANK


def routine(name, text):
    return write_routine([parse_rung(t) for t in text.strip().splitlines()], routine=name)


MAIN = "XIO(Sim_Mode)JSR(MAP_IN,0);\nJSR(Tank,0);\nJSR(MAP_OUT,0);"
FILES = [routine("MainRoutine", MAIN), routine("MAP_IN", "XIC(Local:1:I.Data.0)OTE(P101_Running);"),
         routine("Tank", TANK), routine("MAP_OUT", "XIC(P101_Cmd)XIO(Sim_Mode)OTE(Local:2:O.Data.0);")]


def test_whole_program_loads_with_mapping_and_calls_skipped():
    s = load(FILES, PLANT)
    assert len(s.rungs) == 9 and {p.routine for p in s.places} == {"Tank"}
    assert any("MAP_IN: not run in simulation" in x for x in s.skipped)
    assert sum("subroutine call" in x for x in s.skipped) == 3
    assert "Start_PB" in s.inputs and "Level_Low" in s.inputs
    assert "P101_Running" not in s.inputs and s.feedbacks == ["P101_Running"]     # the plant owns it
    assert "P101_Cmd" in s.outputs and "Sim_Mode" not in s.inputs


def test_energise_runs_logic_and_plant_live():
    s = load(FILES, PLANT)
    snap = s.step(50, {"Start_PB": 1})
    assert snap["tags"]["Auto_Mode"] == 1 and len(snap["power"]) == 9
    s.step(50, {"Start_PB": 0, "Level_Low": 1})
    assert s.snapshot()["tags"]["P101_Cmd"] == 1 and s.snapshot()["tags"]["P101_Running"] == 0
    snap = s.step(1000)
    assert snap["tags"]["P101_Running"] == 1 and snap["now_ms"] >= 1100
    assert snap["power"][3] is True                                            # the pump rung is energised
    assert s.reset()["tags"]["Auto_Mode"] == 0


def test_the_page_cannot_fight_the_logic_or_invent_tags():
    s = load(FILES, PLANT)
    with pytest.raises(EnergiseError, match="written by the logic"):
        s.step(0, {"P101_Cmd": 1})
    with pytest.raises(EnergiseError, match="not used by this program"):
        s.step(0, {"Start_Pb2": 1})


def test_scenarios_run_from_the_session_on_fresh_programs():
    s = load(FILES, PLANT, SCENARIOS)
    s.step(100, {"Start_PB": 1})
    out = s.run_scenarios()
    assert (out["passed"], out["total"]) == (6, 6)
    assert out["trace"]["R3"] == [("TC-07", True), ("TC-08", True)]
    assert s.snapshot()["tags"]["Auto_Mode"] == 1                              # live session untouched


def test_unsupported_instructions_stop_the_load_with_a_list():
    files = FILES + [routine("Loop", "XIC(A)PID(PID_1,PV,0,CV,0,0,0);\nXIC(B)MSG(M1);")]
    with pytest.raises(EnergiseError, match=r"Loop rung 0: PID; Loop rung 1: MSG"):
        load(files, PLANT)


def test_bad_plant_or_scenarios_fail_at_load():
    from plant import PlantError
    from scenario import ScenarioError
    with pytest.raises(PlantError):
        load(FILES, "devices: [")
    with pytest.raises(ScenarioError):
        load(FILES, PLANT, "SCENARIO T\n  PRESS A")
