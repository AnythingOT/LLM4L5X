import pytest

from core.rung import parse_rung
from devices import load_plant
from testcases import ScenarioError, SimBackend, parse_scenarios, report, run_scenario, run_scenarios, trace

# the tank example: R1 fill between switches, R2 stop button, R3 fail to start, R4 high-high
TANK = """\
[XIC(Start_PB) ,XIC(Auto_Mode) ]XIO(Stop_PB)OTE(Auto_Mode);
XIC(Level_Low)OTL(Fill_Req);
XIC(Level_High)OTU(Fill_Req);
XIC(Auto_Mode)XIC(Fill_Req)XIO(P101_Fail)XIO(HH_Alarm)OTE(P101_Cmd);
XIC(P101_Cmd)XIO(P101_Running)TON(P101_FTS_TMR,5000,0);
XIC(P101_FTS_TMR.DN)OTL(P101_Fail);
XIC(Reset_PB)XIO(P101_FTS_TMR.DN)OTU(P101_Fail);
XIC(Level_HH)OTL(HH_Alarm);
XIC(Reset_PB)XIO(Level_HH)OTU(HH_Alarm);
"""
PLANT = "devices:\n  - {name: P101, type: pump, cmd: P101_Cmd, running: P101_Running, start_ms: 1000}\n"

SCENARIOS = """
SCENARIO RTN "back to normal"
  SET Start_PB = 0
  SET Stop_PB = 0
  SET Reset_PB = 0

SCENARIO TC-01 "fills from low to high" REQ R1
SETUP:
  SET Start_PB = 1
  WAIT 50
  SET Start_PB = 0
MAIN:
  SET Level_Low = 1
  EXPECT P101_Cmd == 1 within_ms 100
  SET Level_Low = 0
  EXPECT P101_Cmd == 1 within_ms 2000 hold      # hysteresis: keeps filling between the switches
  SET Level_High = 1
  EXPECT P101_Cmd == 0 within_ms 100
TEARDOWN:
  CALL RTN

SCENARIO TC-02 "stop button stops it" REQ R2
SETUP:
  SET Start_PB = 1
  SET Level_Low = 1
  WAIT 50
  SET Start_PB = 0
MAIN:
  EXPECT PLANT:P101.running == 1 within_ms 1500
  SET Stop_PB = 1
  EXPECT P101_Cmd == 0 within_ms 100
TEARDOWN:
  CALL RTN

SCENARIO TC-07 "fail to start alarms and stops" REQ R3
SETUP:
  SET Start_PB = 1
  WAIT 50
  SET Start_PB = 0
MAIN:
  SET PLANT:P101.fault = fail_to_start
  SET Level_Low = 1
  EXPECT P101_Cmd == 1 within_ms 100
  EXPECT P101_Fail == 1 within_ms 5200
  EXPECT P101_Cmd == 0 within_ms 100
TEARDOWN:
  SET PLANT:P101.fault = none
  CALL RTN

SCENARIO TC-08 "normal start raises no alarm" REQ R3
SETUP:
  SET Start_PB = 1
  WAIT 50
  SET Start_PB = 0
MAIN:
  SET Level_Low = 1
  EXPECT P101_Fail == 0 within_ms 8000 hold      # the negative test

SCENARIO TC-10 "high-high stops and latches" REQ R4
SETUP:
  SET Start_PB = 1
  SET Level_Low = 1
  WAIT 50
MAIN:
  SET Level_HH = 1
  EXPECT P101_Cmd == 0 within_ms 100
  SET Level_HH = 0
  EXPECT HH_Alarm == 1 within_ms 1000 hold
  SET Reset_PB = 1
  EXPECT HH_Alarm == 0 within_ms 100
TEARDOWN:
  CALL RTN
"""


def backend(logic=TANK):
    return SimBackend([parse_rung(t) for t in logic.strip().splitlines()], plant=load_plant(PLANT))


def test_tank_scenarios_all_pass_on_correct_logic():
    scs = parse_scenarios(SCENARIOS)
    res = run_scenarios(scs, backend)
    assert [(r.id, r.passed) for r in res if r.id != "RTN"] == [
        ("TC-01", True), ("TC-02", True), ("TC-07", True), ("TC-08", True), ("TC-10", True)], report(res)
    fail = next(r for r in res if r.id == "TC-07")
    t = next(s for s in fail.steps if "P101_Fail == 1" in s.text)
    assert 4900 <= t.t_ms <= 5200                                  # the 5 s timer, measured
    assert trace(res) == {"R1": [("TC-01", True)], "R2": [("TC-02", True)],
                          "R3": [("TC-07", True), ("TC-08", True)], "R4": [("TC-10", True)]}


@pytest.mark.parametrize("bug, fails", [
    ("XIC(P101_Cmd)XIO(P101_Running)TON(P101_FTS_TMR,500,0);", "TC-08"),   # timer too short: trips normal starts
    ("XIC(Level_Low)OTE(Fill_Req);", "TC-01"),                             # no hysteresis
    ("XIC(Level_HH)OTE(HH_Alarm);", "TC-10"),                              # alarm not latched
])
def test_scenarios_catch_broken_logic(bug, fails):
    first = bug.split("OT")[0].split("TON")[0]
    logic = "\n".join(bug if line.startswith(first) else line for line in TANK.splitlines())
    if "OTE(Fill_Req)" in bug:
        logic = logic.replace("XIC(Level_High)OTU(Fill_Req);\n", "")
    assert logic != TANK and bug.strip() in logic                # the bug really is in the logic
    res = {r.id: r.passed for r in run_scenarios(parse_scenarios(SCENARIOS), lambda: backend(logic))}
    assert res[fails] is False
    assert sum(1 for k, v in res.items() if v is False) >= 1


def test_a_typo_cannot_pass_a_negative_test():
    sc = parse_scenarios("SCENARIO T\n  EXPECT P101_Fial == 0 within_ms 1000 hold")[0]
    r = run_scenario(sc, backend())
    assert not r.passed and r.error == "unknown tags: P101_Fial" and r.steps == []


def test_teardown_runs_after_a_failure_and_main_stops():
    sc = parse_scenarios("""SCENARIO T
MAIN:
  EXPECT P101_Cmd == 1
  SET Start_PB = 1
TEARDOWN:
  SET Stop_PB = 1""")[0]
    be = backend()
    r = run_scenario(sc, be)
    assert not r.passed and [s.action for s in r.steps] == ["EXPECT", "SET"]
    assert be.read("Stop_PB") == 1 and be.read("Start_PB") == 0


def test_tolerance_and_plant_fault_names():
    be = SimBackend([parse_rung("MOV(Raw,Level);")], state={"Raw": 50.3})
    sc = parse_scenarios("SCENARIO T\n  EXPECT Level == 50 tolerance 0.5\n  EXPECT Level != 50 tolerance 0.1")[0]
    assert run_scenario(sc, be).passed
    sc = parse_scenarios("SCENARIO T\n  SET PLANT:P101.fault = stuck")[0]
    r = run_scenario(sc, backend())
    assert not r.passed and "a motor can have" in r.steps[0].message


@pytest.mark.parametrize("text, msg", [
    ("SET A = 1", "start with SCENARIO"),
    ("SCENARIO T\n  PRESS A", "not an action"),
    ("SCENARIO T\n  EXPECT A = 1", "op one of"),
    ("SCENARIO T\n  EXPECT A == 1 hold", "hold needs within_ms"),
    ("SCENARIO T\n  EXPECT A == 1 within_ms soon", "needs a number"),
    ("SCENARIO T\n  EXPECT A == 1 forever", "unknown 'forever'"),
    ("SCENARIO T\n  WAIT a bit", "WAIT <milliseconds>"),
    ("SCENARIO T\n  CALL X", "no such scenario"),
    ("SCENARIO T\n  CALL T", "calls itself"),
    ("SCENARIO T\nSCENARIO T", "defined twice"),
    ("SCENARIO T\n  SET A = 1 2", "SET <tag> = <value>"),
])
def test_scenario_errors_say_what_to_write(text, msg):
    with pytest.raises(ScenarioError, match=msg):
        parse_scenarios(text)


def test_call_loops_are_refused_not_run_forever():
    scs = parse_scenarios("SCENARIO A\n  CALL B\nSCENARIO B\n  CALL A")
    r = run_scenario(scs[0], backend(), scs)
    assert not r.passed and "loops" in r.error


def test_report_names_the_failing_step_and_requirement_status():
    logic = TANK.replace("TON(P101_FTS_TMR,5000,0)", "TON(P101_FTS_TMR,500,0)")
    res = run_scenarios(parse_scenarios(SCENARIOS), lambda: backend(logic))
    text = "\n".join(report(res))
    assert "FAIL  TC-08 normal start raises no alarm  [R3]" in text
    assert "P101_Fail == 0 within_ms 8000 hold" in text and "did not hold" in text
    assert "R3: FAILS (TC-07 ✓, TC-08 ✗)" in text
