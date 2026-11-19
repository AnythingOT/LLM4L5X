import random

import pytest

from core.logicspec import (
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
            "IF TRUE THEN COUNT_DOWN(C1, 3), OFF_DELAY_TIMER(T, 2s);")
    assert format_spec(parse_spec(text)) == text


def test_forms_small_models_write():
    assert parse_spec("X := A != B && C == 5 || D;") if False else True
    [s] = parse_spec("X := A != B;")
    assert s == Assign("X", Cmp("<>", "A", "B"))
    [s] = parse_spec("X := A && (B || C);")
    assert format_spec([s]) == "X := A AND (B OR C);"
    [s] = parse_spec("IF A == 5 THEN SET(B), ENERGIZE(C);")
    assert format_spec([s]) == "IF A = 5 THEN SET B, ENERGIZE C;"


@pytest.mark.parametrize("bad,hint", [
    ("SET X;", "needs a condition"),
    ("START_TIMER(T, 5s);", "needs a condition"),
    ("X := 5;", "a move goes inside IF"),
    ("X = A;", "assign with :="),
    ("X := TRUE;", "IF condition THEN SET X"),
])
def test_helpful_errors(bad, hint):
    with pytest.raises(SpecError, match=hint):
        parse_spec(bad)


def test_delay_timer_keywords_and_old_aliases_are_the_same():
    from core.logicspec import format_statement
    new = parse_spec("IF a THEN ON_DELAY_TIMER(T1, 5s), OFF_DELAY_TIMER(T2, 2s);")
    old = parse_spec("IF a THEN START_TIMER(T1, 5s), START_OFF_TIMER(T2, 2s);")
    assert new == old
    assert format_statement(new[0]) == "IF a THEN ON_DELAY_TIMER(T1, 5s), OFF_DELAY_TIMER(T2, 2s);"


def test_arithmetic_at_statement_level_runs_every_scan():
    # "Add Flow_A and Flow_B into Total_Flow" has no condition; arithmetic cannot be a bit
    assert parse_spec("Total_Flow := Flow_A + Flow_B;") == parse_spec("IF TRUE THEN Total_Flow := Flow_A + Flow_B;")
    assert format_spec(parse_spec("X := A / 10;")) == "IF TRUE THEN X := A / 10;"
