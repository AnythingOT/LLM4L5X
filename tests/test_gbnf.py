import pytest

from eval.suite import generate
from inputs.gbnf import build_gbnf
from inputs.llm import request_identifiers
from helpers import Grammar

TAGS = {"A": "BOOL", "B": "BOOL", "C": "BOOL", "OUT": "BOOL", "N1": "DINT", "N2": "REAL",
        "T1": "TIMER", "C1": "COUNTER", "Buf": "DINT", "Dst": "DINT"}


@pytest.fixture(scope="module")
def g():
    return Grammar(build_gbnf(TAGS))


@pytest.mark.parametrize("ok", [
    "OUT := (A OR OUT) AND NOT B;",
    "IF RISE(A) THEN SET OUT, COUNT_UP(C1, 5), N1 := N1 + 1;",
    "IF TRUE THEN START_TIMER(T1, 5s);",
    "OUT := T1.DN AND C1.ACC >= 3;",
    "OUT := DELAY(N1 > 5, 500ms);",
    "IF A THEN ENERGIZE OUT, COPY(Buf, Dst, 10), RESET_ACC C1;",
    "OUT := A;\nIF B THEN RESET OUT;",
])
def test_accepts(g, ok):
    assert g.accepts(ok)


@pytest.mark.parametrize("bad", [
    "OUT := Invented_Tag;",          # unknown tag
    "OUT := A AND B OR C;",          # mixed without parentheses
    "OUT := N1;",                    # numeric tag used as a contact
    "OUT := A > 5;",                 # bool tag in a comparison
    "IF A THEN SET N1;",             # latch a number
    "T1.DN := A;",                   # write a timer status bit
    "IF A THEN COUNT_UP(T1, 5);",    # timer used as counter
    "Sure! OUT := A;",               # prose
    "OUT := A != B;",                # non-canonical operator
])
def test_rejects(g, bad):
    assert not g.accepts(bad)


def test_every_suite_answer_is_in_its_grammar():
    """The grammar built for each request (offered tags + names in the request)
    must accept that request's expected LogicSpec, for every instruction and structure."""
    cases = generate(per_combo=1, seed=11)
    for c in cases:
        types = dict(c.tags)
        types.update({i: "ANY" for i in request_identifiers(c.english) if i not in types})
        assert Grammar(build_gbnf(types)).accepts(c.spec), (c.id, c.spec)


def test_new_tags_only_when_allowed():
    assert Grammar(build_gbnf(TAGS, allow_new_tags=True)).accepts("Some_New_Bit := A;")
    assert not Grammar(build_gbnf(TAGS)).accepts("Some_New_Bit := A;")
