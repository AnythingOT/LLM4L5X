import random

import pytest

from core.logicspec import Assign, parse_spec
from core.compiler import CompileError, Compiler, compile_spec, tag_name_problem
from core.rung import format_rung
from core.simulator import Simulator, preset_state
from core.validator import errors, validate
from helpers import environments, evaluate, random_expr


def texts(spec, **kw):
    return compile_spec(spec, comments=False, **kw).texts


# ------------------------------------------------------------ exact shapes

def test_seal_in():
    assert texts("Pump := (Start_PB OR Pump) AND NOT Stop_PB AND NOT Fault;") == [
        "[XIC(Start_PB) ,XIC(Pump) ]XIO(Stop_PB)XIO(Fault)OTE(Pump);"
    ]


def test_de_morgan_and_comparison_complement():
    assert texts("Lamp := NOT (A AND (B OR C > 5));") == ["[XIO(A) ,XIO(B) LEQ(C,5) ]OTE(Lamp);"]


def test_nested_or_flattened():
    assert texts("X := A OR (B OR C);") == ["[XIC(A) ,XIC(B) ,XIC(C) ]OTE(X);"]


def test_nested_branch():
    assert texts("X := (A AND (B OR C)) OR D;") == ["[XIC(A) [XIC(B) ,XIC(C) ] ,XIC(D) ]OTE(X);"]


def test_comparisons_map_to_logix_mnemonics():
    out = texts("X := A = 1 AND B <> 2 AND C > 3 AND D < 4 AND E >= 5 AND F <= 6;")
    assert out == ["EQU(A,1)NEQ(B,2)GRT(C,3)LES(D,4)GEQ(E,5)LEQ(F,6)OTE(X);"]


def test_multiple_actions_become_output_branch():
    assert texts("IF A THEN SET B, RESET C, CLEAR N;") == ["XIC(A)[OTL(B) ,OTU(C) ,CLR(N) ];"]


def test_math_and_move():
    assert texts("IF TRUE THEN X := A + B, Y := 3, Z := A / 2;") == ["[ADD(A,B,X) ,MOV(3,Y) ,DIV(A,2,Z) ];"]


def test_rise_first_is_inline():
    assert texts("X := RISE(A) AND B;") == ["XIC(A)ONS(L4X_ONS_1)XIC(B)OTE(X);"]


def test_rise_not_first_uses_helper_rung():
    assert texts("X := B AND RISE(A);") == [
        "XIC(A)ONS(L4X_ONS_1)OTE(L4X_EDGE_1);",
        "XIC(B)XIC(L4X_EDGE_1)OTE(X);",
    ]


def test_not_rise_rejected():
    with pytest.raises(CompileError):
        compile_spec("X := NOT RISE(A);")


def test_delay_helper_rung_and_preset():
    res = compile_spec("Alarm := DELAY(Level > 80, 5s) AND NOT Muted;", comments=False)
    assert res.texts == ["GRT(Level,80)TON(L4X_TMR_1,?,?);", "XIC(L4X_TMR_1.DN)XIO(Muted)OTE(Alarm);"]
    assert res.tags["L4X_TMR_1"].datatype == "TIMER" and res.tags["L4X_TMR_1"].preset == 5000


def test_display_values_option():
    assert texts("X := DELAY(A, 2s);", display_operands="values")[0] == "XIC(A)TON(L4X_TMR_1,2000,0);"


def test_not_delay_is_xio_done():
    assert texts("X := NOT DELAY(A, 1s);")[1] == "XIO(L4X_TMR_1.DN)OTE(X);"


def test_allocated_names_avoid_user_tags():
    assert texts("X := RISE(L4X_ONS_1);")[0] == "XIC(L4X_ONS_1)ONS(L4X_ONS_2)OTE(X);"


# ------------------------------------------------------------ tags

def test_tag_typing():
    res = compile_spec("IF A AND N > 2.5 THEN COUNT_UP(C, 3), M := M + 1;")
    t = {k: v.datatype for k, v in res.tags.items()}
    assert t == {"C": "COUNTER", "A": "BOOL", "N": "REAL", "M": "DINT"}
    assert res.tags["C"].preset == 3


def test_type_conflict():
    with pytest.raises(CompileError, match="used as"):
        compile_spec("X := A; IF A > 3 THEN SET Y;")


def test_known_tags_not_recreated_and_checked():
    res = compile_spec("X := A;", known_tags={"A": "BOOL", "X": "BOOL"})
    assert res.tags == {}
    with pytest.raises(CompileError, match="is a DINT"):
        compile_spec("X := A;", known_tags={"A": "DINT"})


def test_member_reference_warns():
    res = compile_spec("X := Motor.Running;")
    assert any("Motor" in w for w in res.warnings)
    assert "Motor" not in res.tags


def test_bad_tag_names():
    assert tag_name_problem("Ok_Name1") is None
    assert tag_name_problem("Bad__Name")
    assert tag_name_problem("Trailing_")
    assert tag_name_problem("x" * 41)
    with pytest.raises(CompileError):
        compile_spec("X_ := A;")


def test_named_timer_two_presets_rejected():
    with pytest.raises(CompileError, match="two presets"):
        compile_spec("X := DELAY(A, 1s, T1); Y := DELAY(B, 2s, T1);")


# ------------------------------------------------------------ equivalence

def test_truth_table_equivalence_random():
    """For random expressions, the compiled rung computes exactly the expression."""
    rng = random.Random(7)
    envs = list(environments())
    for _ in range(150):
        e = random_expr(rng)
        res = Compiler(comments=False).compile([Assign("OUT", e)])
        assert not errors(validate(res.rungs))
        sim = Simulator(res.rungs)
        for env in envs:
            sim.state = dict(env)
            got = sim.scan()["OUT"]
            assert got == evaluate(e, env), (format_rung(res.rungs[0]), env)


def run(spec, steps, dt=0):
    res = compile_spec(spec, comments=False)
    sim = Simulator(res.rungs, preset_state(res.tags))
    return [bool(sim.scan(dt, inp).get("X")) for inp in steps]


def test_rise_semantics_edge_of_its_own_argument():
    # Ack rises while Run is off; Run comes on later: no pulse.
    steps = [{"Run": 0, "Ack": 0}, {"Run": 0, "Ack": 1}, {"Run": 1, "Ack": 1}, {"Ack": 0}, {"Ack": 1}, {"Ack": 1}]
    assert run("X := Run AND RISE(Ack);", steps) == [False, False, False, False, True, False]
    assert run("X := RISE(Ack) AND Run;", steps) == [False, False, False, False, True, False]


def test_delay_semantics():
    steps = [{"A": 1}] * 5 + [{"A": 0}]
    assert run("X := DELAY(A, 3s);", steps, dt=1000) == [False, False, True, True, True, False]


def test_offdelay_semantics():
    steps = [{"A": 1}, {"A": 0}, {"A": 0}, {"A": 0}]
    assert run("X := OFFDELAY(A, 2s);", steps, dt=1000) == [True, True, False, False]


def test_counter_semantics():
    res = compile_spec("IF P THEN COUNT_UP(C, 2); X := C.DN;", comments=False)
    sim = Simulator(res.rungs, preset_state(res.tags))
    out = [bool(sim.scan(0, {"P": p})["X"]) for p in (1, 1, 0, 1, 0)]
    assert out == [False, False, False, True, True]


def test_comments_are_read_back():
    res = compile_spec("Pump := Start OR Pump;")
    assert res.rungs[0].comment.startswith("Pump is on while either Start is on OR Pump is on")


def test_v36_mnemonics():
    spec = "X := A = 1 AND B <> 2 AND C > 3 AND D < 4 AND E >= 5 AND F <= 6; IF G THEN N := 3;"
    assert texts(spec, revision="36.00") == [
        "EQ(A,1)NE(B,2)GT(C,3)LT(D,4)GE(E,5)LE(F,6)OTE(X);", "XIC(G)MOVE(3,N);"]
    assert texts(spec, revision="35.01")[0].startswith("EQU(A,1)NEQ(B,2)GRT(C,3)")
    assert texts(spec)[1] == "XIC(G)MOV(3,N);"  # unknown version: pre-v36 names


def test_v36_rungs_simulate_and_decompile():
    from explain.decompiler import decompile_rung
    from core.logicspec import format_spec
    res = compile_spec("X := N > 5 AND NOT (M = 2);", comments=False, revision="36")
    assert res.texts == ["GT(N,5)NE(M,2)OTE(X);"]
    assert Simulator(res.rungs, {"N": 6, "M": 1}).scan()["X"] is True
    assert format_spec(decompile_rung(res.rungs[0])) == "X := N > 5 AND M <> 2;"


def test_simulator_add_with_zero_does_not_evaluate_division():
    # regression: all four results used to be computed up front, so ADD(x,0,z) raised
    from core.rung import parse_rung
    sim = Simulator([parse_rung("ADD(A,B,C);")], {"A": 3, "B": 0})
    assert sim.scan()["C"] == 3


def test_reset_only_counter_or_timer_is_created_with_a_warning():
    from core.compiler import compile_spec
    r = compile_spec("IF a THEN RESET_ACC Part_CTR, RESET_ACC Fill_TMR;", comments=False)
    assert r.tags["Part_CTR"].datatype == "COUNTER" and r.tags["Fill_TMR"].datatype == "TIMER"
    assert any("Part_CTR is new and only reset here" in w for w in r.warnings)
    r = compile_spec("IF r THEN RESET_ACC Box;\nIF b THEN COUNT_UP(Box, 12);", comments=False)
    assert r.tags["Box"].preset == 12 and not r.warnings


def test_v36_move_destination_gets_a_tag():
    # MOVE (v36) accepts any type; typing must not lose the destination of a literal move
    r = Compiler(revision="37.00").compile(parse_spec("IF A THEN Lane_No := 250, Total := Speed / 100;"))
    assert {t.name: t.datatype for t in r.tags.values()}["Lane_No"] == "DINT"
    assert "MOVE(250,Lane_No)" in format_rung(r.rungs[0])


@pytest.mark.parametrize("spec", ["Lamp := DELAY(Start, 1000h);", "IF A THEN ON_DELAY_TIMER(T1, 600h);",
                                  "IF RISE(Btn) THEN COUNT_UP(Cnt, 3000000000);"])
def test_a_preset_beyond_dint_is_refused(spec):
    # .PRE is a DINT: 2,147,483,647 ms is about 596 hours
    with pytest.raises(CompileError, match="outside 0 to 2147483647"):
        Compiler().compile(parse_spec(spec))


def test_the_largest_dint_preset_is_accepted():
    r = Compiler().compile(parse_spec("Lamp := DELAY(Start, 596h);"))
    assert max(t.preset or 0 for t in r.tags.values()) == 596 * 3600000


@pytest.mark.parametrize("name", ["Purge_Done", "Shuttle_Rev", "Step_No", "Batch_Count"])
def test_reset_acc_on_a_tag_that_is_no_counter_or_timer_is_refused(name):
    # hard holdout seed 17: "reset Purge_Done", "unlatch Shuttle_Rev" and "reset Step_No to zero"
    # came back as RES, and each tag was quietly made a COUNTER
    from core.compiler import CompileError, compile_spec
    with pytest.raises(CompileError, match=f"RESET {name}.*CLEAR {name}"):
        compile_spec(f"IF a THEN RESET_ACC {name};", comments=False)


def test_reset_acc_on_a_project_counter_still_works():
    from core.compiler import Compiler
    from core.logicspec import parse_spec
    r = Compiler(known_tags={"Box_Tally": "COUNTER"}).compile(parse_spec("IF a THEN RESET_ACC Box_Tally;"))
    from core.rung import format_rung
    assert format_rung(r.rungs[0]).endswith("RES(Box_Tally);") and not r.warnings
