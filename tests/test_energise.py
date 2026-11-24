import re

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
    assert "P101_FTS_TMR.ACC" in s.outputs and "P101_FTS_TMR" not in s.outputs   # timers show ACC and DN


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


@pytest.fixture
def web():
    import app as gui
    from gui import ENERGISE
    gui.app.config["TESTING"] = True
    ENERGISE.clear()
    with gui.app.test_client() as c:
        yield c
    ENERGISE.clear()


def _upload(web, files, plant=PLANT, scenarios=SCENARIOS):
    import io
    data = {"files": [(io.BytesIO(f.encode()), f"R{i}.L5X") for i, f in enumerate(files)],
            "plant": plant, "scenarios": scenarios}
    return web.post("/api/energise/load", data=data, content_type="multipart/form-data")


def test_energise_page_and_api(web):
    assert web.get("/energise").status_code == 200
    assert web.post("/api/energise/step", json={}).get_json()["error"] == "load a program first"
    j = _upload(web, FILES).get_json()
    assert len(j["rungs"]) == 9 and "Start_PB" in j["inputs"] and j["feedbacks"] == ["P101_Running"]
    assert j["rungs"][3]["routine"] == "Tank" and j["has_scenarios"]
    web.post("/api/energise/step", json={"ms": 50, "writes": {"Start_PB": 1}})
    snap = web.post("/api/energise/step", json={"ms": 1200, "writes": {"Start_PB": 0, "Level_Low": 1}}).get_json()
    assert snap["tags"]["P101_Running"] == 1 and snap["power"][3] is True
    bad = web.post("/api/energise/step", json={"writes": {"P101_Cmd": 1}})
    assert bad.status_code == 400 and "written by the logic" in bad.get_json()["error"]
    out = web.post("/api/energise/scenarios").get_json()
    assert (out["passed"], out["total"]) == (6, 6) and out["trace"]["R3"] == [["TC-07", True], ["TC-08", True]]
    assert web.post("/api/energise/step", json={"reset": True}).get_json()["tags"]["Auto_Mode"] == 0


def test_energise_load_tells_the_page_how_to_show_each_tag(web):
    # bits get a switch or a lamp, numbers a field: a setpoint is no longer flipped 0/1 by a click
    j = _upload(web, FILES).get_json()
    kinds = j["kinds"]
    assert kinds["Start_PB"] == "BOOL" and kinds["P101_Running"] == "BOOL"
    assert all(kinds[t] in ("BOOL", "NUM") for t in j["inputs"] + j["outputs"] + j["feedbacks"])
    nums = [t for t in j["inputs"] + j["outputs"] if kinds[t] == "NUM"]
    assert nums, "the tank program has numbers (a level)"
    for s in j["structs"]:  # each timer or counter: its preset is watched live, its done bit is a bit
        assert f"{s['name']}.PRE" in j["snapshot"]["tags"] and kinds[f"{s['name']}.DN"] == "BOOL"
    # every rung is drawn, and its contacts and coils name their tag so the page can light them
    assert all(r["svg"] and 'class="lad-el"' in r["svg"] for r in j["rungs"] if "XIC(" in r["text"])
    lit = {t for r in j["rungs"] for t in re.findall(r'data-tag="([^"]+)"', r["svg"] or "")}
    assert lit <= set(j["snapshot"]["tags"])  # every lit symbol has a live value

def test_energise_takes_the_routines_zip_and_reports_bad_files(web):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i, f in enumerate(FILES):
            z.writestr(f"R{i}.L5X", f)
        z.writestr("Report.txt", "not a routine")
    r = web.post("/api/energise/load", data={"files": [(io.BytesIO(buf.getvalue()), "Routines.zip")],
                                             "plant": PLANT}, content_type="multipart/form-data")
    assert r.status_code == 200 and len(r.get_json()["rungs"]) == 9
    r = _upload(web, FILES, plant="devices: [")
    assert r.status_code == 400 and "YAML" in r.get_json()["error"]


def test_energise_refuses_requests_from_other_sites(web):
    r = web.post("/api/energise/step", json={}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_timer_and_counter_presets_come_from_the_tags():
    # an export from v36 on writes TON(T,?,?): the preset is only in the tag's data. Without it every timer
    # had preset 0 and was done on the first scan (seed-41 Routines.zip: Purge_TMR, Batch_Done at 0.1 s)
    from core.compiler import TagDef
    rungs = [parse_rung(t) for t in ("XIC(Go)TON(Fill_TMR,?,?);", "XIC(Box_Eye)CTU(Box_CTR,?,?);",
                                     "XIC(Box_CTR.DN)OTE(Batch_Done);")]
    tags = [TagDef("Go", "BOOL"), TagDef("Box_Eye", "BOOL"), TagDef("Batch_Done", "BOOL"),
            TagDef("Fill_TMR", "TIMER", preset=5000), TagDef("Box_CTR", "COUNTER", preset=3)]
    s = load([write_routine(rungs, tags, routine="Main")])
    snap = s.step(100, {"Go": 1})
    assert snap["tags"]["Fill_TMR.DN"] == 0 and not snap["tags"]["Batch_Done"]
    assert s.step(5000)["tags"]["Fill_TMR.DN"] == 1
    for _ in range(3):
        s.step(10, {"Box_Eye": 1})
        snap = s.step(10, {"Box_Eye": 0})
    assert snap["tags"]["Box_CTR.ACC"] == 3 and snap["tags"]["Batch_Done"]
