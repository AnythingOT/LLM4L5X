"""The simulator runs whole programs: subroutines (JSR), Add-On Instruction logic, CPT and CMP."""
import pytest

from core.expression import ExprError, compile_expr
from core.rung import parse_rung
from core.simulator import AoiDef, SimError, Simulator


def rungs(*texts):
    return [parse_rung(t) for t in texts]


def test_cpt_and_cmp_follow_logix_precedence():
    env = {"A": 7, "B": 2, "R": 1.5}
    assert compile_expr("A+B*3")(env.get) == 13 and compile_expr("(A+B)*3")(env.get) == 27
    assert compile_expr("A MOD B")(env.get) == 1 and compile_expr("ABS(-R)*2")(env.get) == 3.0
    assert compile_expr("A > B AND B > 1")(env.get) == 1 and compile_expr("16#FF AND 15")(env.get) == 15
    s = Simulator(rungs("CPT(Out,(A+B)*3);", "CMP(A*B>=14)OTE(Big);"), {"A": 7, "B": 2})
    s.scan()
    assert s.get("Out") == 27 and s.bit("Big")
    with pytest.raises(ExprError):
        compile_expr("__import__('os')")  # never Python eval: a file cannot run code


def test_a_real_written_to_an_integer_tag_rounds_to_even():
    s = Simulator(rungs("CPT(D1,2.5);", "CPT(D2,3.5);", "CPT(D3,-2.5);", "CPT(R,2.5);", "MOV(7.6,D4);"),
                  types={"D1": "DINT", "D2": "DINT", "D3": "INT", "R": "REAL", "D4": "DINT"})
    s.scan()
    assert [s.get(t) for t in ("D1", "D2", "D3", "R", "D4")] == [2, 4, -2, 2.5, 8]


def test_jsr_runs_a_subroutine_only_when_called():
    r = rungs("XIC(Go)JSR(Sub,0);", "XIC(In)OTE(Out);")
    s = Simulator(r, {"In": 1}, routine_of=["P/Main", "P/Sub"])
    s.scan()
    assert not s.bit("Out") and s.power == [False, False]  # Sub not called: its rung did not run
    s.scan(inputs={"Go": 1})
    assert s.bit("Out") and s.power == [True, True]
    s.scan(inputs={"Go": 0, "In": 0})
    assert s.bit("Out")  # not called, so its OTE is not scanned false: the output holds, as on a controller


def test_jsr_to_a_skipped_or_missing_routine():
    s = Simulator(rungs("JSR(MAP_IN,0)OTE(After);"), routine_of=["P/Main"], skip={"MAP_IN"})
    s.scan()
    assert s.bit("After")
    with pytest.raises(SimError, match="not loaded"):
        Simulator(rungs("JSR(Nowhere,0);"), routine_of=["P/Main"]).scan()
    loop = Simulator(rungs("JSR(A,0);", "JSR(A,0);"), routine_of=["P/Main", "P/A"])
    with pytest.raises(SimError, match="nested"):
        loop.scan()


def test_an_aoi_runs_its_logic_per_instance():
    # Start_Delay(Inst, Start, Run): Run comes on 500 ms after Start, through a local timer
    d = AoiDef("Start_Delay", [("Start", "Input"), ("Run", "Output")],
               rungs("XIC(Start)TON(Tmr,?,?);", "XIC(Tmr.DN)OTE(Run);"),
               members={"Start", "Run", "Tmr"}, defaults={"Tmr.PRE": 500})
    s = Simulator(rungs("Start_Delay(P1,Go1,Motor1);", "Start_Delay(P2,Go2,Motor2);"), aois={"Start_Delay": d})
    s.scan(10, {"Go1": 1})
    for _ in range(60):
        s.scan(10)
    assert s.bit("Motor1") and not s.bit("Motor2")  # two instances, two timers
    assert s.get("P1.Tmr.ACC") == 500 and s.get("P2.Tmr.ACC") == 0


def test_an_aoi_inout_parameter_is_the_tag_passed_in():
    d = AoiDef("Bump", [("Count", "InOut")], rungs("ADD(Count,1,Count);"), members={"Count"})
    s = Simulator(rungs("XIC(Go)Bump(B1,Total);"), {"Total": 5, "Go": 1}, aois={"Bump": d})
    s.scan()
    s.scan()
    assert s.get("Total") == 7 and "B1.Count" not in s.state


def test_osr_and_osf_give_one_scan_edges():
    s = Simulator(rungs("XIC(In)OSR(St1,Up);", "XIC(In)OSF(St2,Down);"))
    seen = []
    for v in (0, 1, 1, 0, 0):
        s.scan(inputs={"In": v})
        seen.append((s.get("Up"), s.get("Down")))
    assert seen == [(False, False), (True, False), (False, False), (False, True), (False, False)]
