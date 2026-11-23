import random

import pytest

from core.logicspec import Assign, format_spec
from core.compiler import Compiler, compile_spec
from explain.decompiler import decompile_rung, try_decompile
from core.rung import parse_rung
from helpers import environments, evaluate, random_expr


def dec(text, presets=None):
    return format_spec(decompile_rung(parse_rung(text), presets))


def test_basic_shapes():
    assert dec("[XIC(Start) ,XIC(Pump) ]XIO(Stop)OTE(Pump);") == "Pump := (Start OR Pump) AND NOT Stop;"
    assert dec("XIC(A)ONS(S)XIC(B)[OTL(C) ,CLR(N) ];") == "IF RISE(A) AND B THEN SET C, CLEAR N;"
    assert dec("GRT(L,80)TON(T1,?,?);", {"T1": 5000}) == "IF L > 80 THEN ON_DELAY_TIMER(T1, 5s);"
    assert dec("MOV(3,X);") == "IF TRUE THEN X := 3;"


def test_ote_in_output_branch_becomes_energize():
    assert dec("XIC(A)[OTE(B) ,OTE(C) ];") == "IF A THEN ENERGIZE B, ENERGIZE C;"
    # condition reading its own outputs stays one rung, so it is still exact
    assert dec("[XIC(A) ,XIC(B) ]XIO(B)[OTE(B) ,OTE(C) ];") == "IF (A OR B) AND NOT B THEN ENERGIZE B, ENERGIZE C;"


@pytest.mark.parametrize("text,why", [
    ("XIC(A)OTE(B)XIC(C)OTE(D);", "middle"),
    ("[XIC(A)OTE(B) ,XIC(C) ]OTE(D);", "middle"),
    ("XIC(A)[,XIC(B) ]OTE(C);", "empty"),
    ("XIC(A)TON(T1,?,?);", "preset"),
    ("XIC(A)JSR(Sub,0);", "outputs only"),
    ("XIC(A)[XIC(B) ONS(S) ,XIC(C) ]OTE(X);", "start of the power path"),
    ("XIC(A)ONS(S)ONS(T)OTE(X);", "more than one ONS"),
    ("[ONS(S) ,XIC(C) ]OTE(X);", "nothing to its left"),
])
def test_not_convertible(text, why):
    stmts, reason = try_decompile(parse_rung(text))
    assert stmts is None and why in reason


def test_compile_decompile_equivalent_random():
    rng = random.Random(3)
    envs = list(environments())[::7]
    for _ in range(100):
        e = random_expr(rng)
        rung = Compiler(comments=False).compile([Assign("OUT", e)]).rungs[0]
        [back] = decompile_rung(rung)
        for env in envs:
            assert evaluate(back.expr, env) == evaluate(e, env)


def test_recompile_is_identical():
    src = "[XIC(a) [XIC(b) ,XIO(c) ] ,GRT(n,5) ]XIO(d)OTE(q);"
    spec = dec(src)
    assert compile_spec(spec, comments=False).texts == [src]


def test_ons_at_start_of_or_leg():
    # the shape the compiler writes for RISE as the first item of an OR leg (test workbook "Parallel" rows)
    src = "[LEQ(PT,Cycles) ,XIC(Manual) ONS(S) ,NEQ(SP,5) ]TOF(T1,2000,0);"
    assert dec(src, {"T1": 2000}) == "IF PT <= Cycles OR RISE(Manual) OR SP <> 5 THEN OFF_DELAY_TIMER(T1, 2s);"
    assert dec("[XIC(A) XIC(B) ONS(S) XIO(C) ,XIC(D) ]OTE(X);") == "X := (RISE(A AND B) AND NOT C) OR D;"


def test_ons_in_or_leg_recompiles_to_the_same_shape():
    back = compile_spec(dec("[XIC(a) ONS(s) ,XIC(b) ]OTE(q);"), comments=False).texts
    assert len(back) == 1 and back[0].startswith("[XIC(a) ONS(") and back[0].endswith(",XIC(b) ]OTE(q);")
