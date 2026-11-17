import pytest

from core.rung import Branch, Instr, RungSyntaxError, base_tag, format_rung, is_literal, normalize, parse_rung

ROUND_TRIP = [
    "XIC(a)OTE(b);",
    "XIC(Start)[XIC(Run) ,XIO(Stop) ]OTE(Motor);",
    "[XIC(a) ,XIC(b) ,XIC(c) ]OTE(d);",
    "[XIC(a) [XIC(b) ,XIC(c) ] ,XIO(d) ]OTE(e);",
    "XIC(a)[OTE(b) ,OTL(c) ,MOV(5,d) ];",
    "XIC(Local:1:I.Data.0)XIC(Arr[3].Member.2)OTE(Out[Idx+1]);",
    "TON(T1,?,?);",
    "CPT(Dest,(A + B) * 2.5);",
    "NOP();",
    "XIC(a)[,XIC(b) ]OTE(c);",
    "XIC(a)[XIC(b) ,]OTE(c);",
    # verbatim from Rockwell's public ra-logix-cicd sample export
    "XIC(I_ToggleEnable_LocalTag)[XIC(I_ToggleSINT_LocalTag) MOVE(127,O_SINT_LocalTag) ,XIO(I_ToggleSINT_LocalTag) MOVE(-128,O_SINT_LocalTag) ];",
    "MOV(16#FF,x);",
]


@pytest.mark.parametrize("text", ROUND_TRIP)
def test_round_trip_exact(text):
    assert format_rung(parse_rung(text)) == text


def test_whitespace_tolerant():
    assert normalize("  XIC( a )  [ XIC(b)XIO(e),XIO(c) ]  OTE(d) ; ") == "XIC(a)[XIC(b) XIO(e) ,XIO(c) ]OTE(d);"


def test_structure():
    r = parse_rung("XIC(a)[XIC(b) ,XIO(c) ]OTE(d);")
    a, br, d = r.body.items
    assert a == Instr("XIC", ("a",))
    assert isinstance(br, Branch) and len(br.legs) == 2
    assert [i.name for i in r.instructions()] == ["XIC", "XIC", "XIO", "OTE"]


@pytest.mark.parametrize("bad", [
    "XIC(a)OTE(b)",          # missing ;
    "XIC(a",                  # unterminated
    "[XIC(a) ]OTE(b);",       # one-leg branch
    "XIC(a)OTE(b); XIC(c);",  # trailing text
    "XIC(a]OTE(b);",          # unbalanced bracket
    "(a)OTE(b);",             # no instruction name
])
def test_syntax_errors(bad):
    with pytest.raises(RungSyntaxError):
        parse_rung(bad)


def test_tag_helpers():
    assert base_tag("Tank[3].Level.2") == "Tank"
    assert base_tag("Local:1:I.Data.0") == "Local:1:I"
    assert base_tag("5") is None and base_tag("?") is None
    assert is_literal("-2.5e3") and is_literal("16#0F") and not is_literal("A1")
