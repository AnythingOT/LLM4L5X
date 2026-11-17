import random

import pytest

from core.logicspec import Assign, format_statement
from inputs.gbnf import build_gbnf
from helpers import BOOLS, NUMS, Grammar, random_expr

TAGS = {**{b: "BOOL" for b in BOOLS}, **{n: "DINT" for n in NUMS}, "OUT": "BOOL", "T1": "TIMER", "C1": "COUNTER"}


@pytest.fixture(scope="module")
def g():
    return Grammar(build_gbnf(TAGS))


def test_accepts_random_compiler_inputs(g):
    rng = random.Random(11)
    for _ in range(60):
        s = format_statement(Assign("OUT", random_expr(rng, depth=2)))
        assert g.accepts(s), s


@pytest.mark.parametrize("ok", [
    "OUT := (A OR OUT) AND NOT B;",
    "IF RISE(A) THEN SET OUT, COUNT_UP(C1, 5), N1 := N1 + 1;",
    "IF TRUE THEN START_TIMER(T1, 5s);",
    "OUT := T1.DN AND C1.ACC >= 3;",
    "OUT := DELAY(N1 > 5, 500ms);",
])
def test_accepts(g, ok):
    assert g.accepts(ok)


@pytest.mark.parametrize("bad", [
    "OUT := Invented_Tag;",          # unknown tag
    "OUT := A AND B OR C;",          # mixed without parentheses
    "OUT := N1;",                    # numeric tag used as a contact
    "OUT := A > 5;",                 # bool tag in a comparison
    "IF A THEN SET N1;",             # latch a number
    "OUT := EQ(A, B);",              # old invalid mnemonic syntax
    "IF A THEN COUNT_UP(T1, 5);",    # timer used as counter
    "T1.DN := A;",                   # writing a timer status bit (old repo bug)
    "IF A THEN SET C1.DN;",
])
def test_rejects(g, bad):
    assert not g.accepts(bad)


def test_new_tags_option():
    g2 = Grammar(build_gbnf(TAGS, allow_new_tags=True))
    assert g2.accepts("OUT := Some_New_Bit;")


def test_no_tags_is_an_error():
    with pytest.raises(ValueError):
        build_gbnf({"S": "STRING"})
