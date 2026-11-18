from core.compiler import compile_spec
from core.rung import parse_rung
from eval.rung_compare import Side, compare


def side(*texts, presets=None):
    return Side([parse_rung(t) for t in texts], presets or {})


def test_same_behaviour_different_text():
    assert compare(side("XIC(A)XIC(B)OTE(X);"), side("XIC(B)XIC(A)OTE(X);"))[0]
    assert compare(side("XIC(A)GRT(N,5)OTE(X);"), side("GT(N,5)XIC(A)OTE(X);"))[0]          # v36 name
    assert compare(side("[XIO(A) ,XIO(B) ]OTE(X);"), side("XIC(A)XIC(B)OTU(Y)OTE(Z);"))[0] is False
    assert compare(side("XIC(A)ONS(REF_S)OTE(X);"), side("XIC(A)ONS(L4X_ONS_1)OTE(X);"))[0]  # internal names


def test_detects_wrong_logic_with_reason():
    ok, why = compare(side("XIC(A)XIC(B)OTE(X);"), side("[XIC(A) ,XIC(B) ]OTE(X);"))
    assert not ok and why.startswith("X: expected")
    ok, why = compare(side("XIC(A)OTE(X);"), side("XIC(A)OTE(X)OTE(Y);"))
    assert not ok and "writes Y" in why


def test_timers_compared_over_time():
    exp = side("XIC(A)TON(T1,?,?);", "XIC(T1.DN)OTE(X);", presets={"T1": 5000})
    assert compare(exp, side("XIC(A)TON(T1,?,?);", "XIC(T1.DN)OTE(X);", presets={"T1": 5000}))[0]
    ok, why = compare(exp, side("XIC(A)TON(T1,?,?);", "XIC(T1.DN)OTE(X);", presets={"T1": 3000}))
    assert not ok and "T1" in why
    # an auto-named DELAY timer behaves like a named one: outputs match
    got = compile_spec("X := DELAY(A, 5s);", comments=False)
    exp2 = side("XIC(A)TON(REF_T,?,?);", "XIC(REF_T.DN)OTE(X);", presets={"REF_T": 5000})
    assert compare(exp2, Side(got.rungs, {t.name: t.preset for t in got.tags.values() if t.preset}))[0]


def test_counters_math_copy():
    assert compare(side("XIC(A)CTU(C,?,?);", presets={"C": 3}), side("XIC(A)CTU(C,?,?);", presets={"C": 3}))[0]
    assert not compare(side("XIC(A)CTU(C,?,?);"), side("XIC(A)CTD(C,?,?);"))[0]
    assert not compare(side("XIC(A)ADD(P,Q,R);"), side("XIC(A)SUB(P,Q,R);"))[0]
    assert compare(side("XIC(A)COP(S[0],D[0],3);"), side("XIC(A)COP(S[0],D[0],3);"))[0]
    assert not compare(side("XIC(A)COP(S[0],D[0],3);"), side("XIC(A)COP(S[0],D[0],2);"))[0]
