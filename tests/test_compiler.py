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
    assert texts("Lamp := NOT (A AND (B OR C > 5));") == ["[XIO(A) ,XIO(B)LEQ(C,5) ]OTE(Lamp);"]


def test_nested_or_flattened():
    assert texts("X := A OR (B OR C);") == ["[XIC(A) ,XIC(B) ,XIC(C) ]OTE(X);"]


def test_nested_branch():
    assert texts("X := (A AND (B OR C)) OR D;") == ["[XIC(A)[XIC(B) ,XIC(C) ] ,XIC(D) ]OTE(X);"]


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
