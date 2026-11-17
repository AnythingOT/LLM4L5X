import random

import pytest

from llm4l5x.logicspec import (
    And, Assign, Cmp, Count, Delay, IfThen, Math, Not, Or, Rise, SetBit, SpecError, StartTimer, Var,
    format_expr, format_spec, parse_expr, parse_spec,
)
from helpers import random_expr


def test_parse_basic():
    [s] = parse_spec("Pump := (Start OR Pump) AND NOT Stop;")
    assert s == Assign("Pump", And((Or((Var("Start"), Var("Pump"))), Not(Var("Stop")))))


def test_mixed_and_or_rejected():
    with pytest.raises(SpecError, match="parentheses"):
        parse_spec("X := A AND B OR C;")


def test_if_then_actions():
    [s] = parse_spec("IF RISE(PB) THEN SET Lamp, COUNT_UP(C1, 10), Total := Total + 2.5, START_TIMER(T1, 1.5s);")
    assert s == IfThen(Rise(Var("PB")), (
        SetBit("Lamp"), Count("C1", 10), Math("Total", "Total", "+", "2.5"), StartTimer("T1", 1500),
    ))


def test_if_true_and_move():
    [s] = parse_spec("IF TRUE THEN Speed := -5;")
    assert s == IfThen(None, (Math("Speed", "-5"),))


def test_delay_units_and_named_timer():
    e = parse_expr("DELAY(A, 2min, T_A) AND OFFDELAY(B, 250ms)")
    assert e == And((Delay(Var("A"), 120000, False, "T_A"), Delay(Var("B"), 250, True)))


def test_comparison_and_members():
    assert parse_expr("Tank[2].Level >= 80.5") == Cmp(">=", "Tank[2].Level", "80.5")
    assert parse_expr("T1.DN") == Var("T1.DN")


@pytest.mark.parametrize("bad", [
    "X := 5;",                 # number as condition
    "X := A",                  # missing ;
    "IF A THEN ;",             # no action
    "X := TRUE;",              # TRUE outside IF
    "IF A THEN COUNT_UP(C, 2.5);",
    "X := DELAY(A, 5);",       # missing unit
    "X := A AND;",
])
def test_errors(bad):
    with pytest.raises(SpecError):
        parse_spec(bad)


def test_keywords_case_insensitive_but_reserved():
    [s] = parse_spec("x := a and not b;")
    assert s == Assign("x", And((Var("a"), Not(Var("b")))))
    with pytest.raises(SpecError):
        parse_spec("Set := A;")


def test_format_parse_round_trip_random():
    rng = random.Random(1)
    for _ in range(500):
        e = random_expr(rng)
        assert parse_expr(format_expr(e)) == e, format_expr(e)


def test_format_spec_round_trip():
    text = ("Pump := (Start OR Pump) AND NOT Stop;\n"
            "IF RISE(A) AND NOT (B AND C) THEN SET D, CLEAR N, X := Y * 2;\n"
            "IF TRUE THEN COUNT_DOWN(C1, 3), START_OFF_TIMER(T, 2s);")
    assert format_spec(parse_spec(text)) == text
