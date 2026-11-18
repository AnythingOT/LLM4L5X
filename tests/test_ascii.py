import pytest

from core.ascii import (AsciiSyntaxError, format_ascii, looks_like_ascii, parse_ascii,
                        parse_ascii_rung, split_ascii_rungs)
from core.rung import format_rung, parse_rung

PAIRS = [
    ("XIC(a)OTE(b);", "XIC a OTE b"),
    ("XIC(a)[XIC(b) ,XIO(c) ]OTE(d);", "XIC a BST XIC b NXB XIO c BND OTE d"),
    ("[XIC(a) [XIC(b) ,XIC(c) ] ,XIO(d) ]OTE(e);", "BST XIC a BST XIC b NXB XIC c BND NXB XIO d BND OTE e"),
    ("XIC(a)[,XIC(b) ]OTE(c);", "XIC a BST NXB XIC b BND OTE c"),
    ("GRT(Level,80.0)TON(T1,?,?);", "GRT Level 80.0 TON T1 ? ?"),
    ("XIC(Local:1:I.Data.0)MOV(Arr[3].Val,N[Idx+1]);", "XIC Local:1:I.Data.0 MOV Arr[3].Val N[Idx+1]"),
    ("XIC(a)JSR(Sub,2,x,y,r);", "XIC a JSR Sub 2 x y r"),
    ("XIC(a)CPT(Out,A + B * 2);", 'XIC a CPT Out "A + B * 2"'),
    ("XIC(a)[OTE(b) ,MOVE(1,c) ];", "XIC a BST OTE b NXB MOVE 1 c BND"),
]


@pytest.mark.parametrize("neutral,ascii_", PAIRS)
def test_both_directions(neutral, ascii_):
    assert format_ascii(parse_rung(neutral)) == ascii_
    assert format_rung(parse_ascii_rung(ascii_)) == neutral


def test_whitespace_and_sor_eor():
    text = "SOR XIC a  BST XIC b NXB XIO c BND OTE d EOR\nSOR XIC x OTE y EOR"
    assert split_ascii_rungs(text) == ["XIC a BST XIC b NXB XIO c BND OTE d", "XIC x OTE y"]
    assert [format_rung(r) for r in parse_ascii(text)] == ["XIC(a)[XIC(b) ,XIO(c) ]OTE(d);", "XIC(x)OTE(y);"]
    assert len(parse_ascii("XIC a OTE b\n\nXIC c OTE d\n")) == 2


def test_tag_named_like_instruction_in_fixed_operand():
    # operands are taken by count, so a tag called ADD is fine
    assert format_rung(parse_ascii_rung("XIC ADD OTE b")) == "XIC(ADD)OTE(b);"


@pytest.mark.parametrize("bad,why", [
    ("XIC a BST XIC b OTE c", "BND"),
    ("XIC a NXB OTE c", "without BST"),
    ("XIC a FOO b OTE c", "unknown instruction"),
    ("XIC", "operands"),
    ("XIC a BST XIC b BND OTE c", "NXB"),
    ("TON T1 ? BND", "ran into BND"),
])
def test_errors(bad, why):
    with pytest.raises(AsciiSyntaxError, match=why):
        parse_ascii_rung(bad)


def test_aoi_needs_project_catalog():
    from core.catalog import Instruction, Operand, default_catalog
    with pytest.raises(AsciiSyntaxError, match="Add-On Instruction"):
        parse_ascii_rung("Motor_AOI M1 Start Run")
    cat = default_catalog().copy()
    cat.add(Instruction("Motor_AOI", "output", (Operand("i", "ANY", "struct"), Operand("s", "ANY", "read"),
                                                Operand("r", "ANY", "write"))))
    assert format_rung(parse_ascii_rung("XIC x Motor_AOI M1 Start Run", cat)) == "XIC(x)Motor_AOI(M1,Start,Run);"


def test_detection():
    assert looks_like_ascii("XIC a OTE b")
    assert looks_like_ascii("SOR XIC a OTE b EOR")
    assert not looks_like_ascii("XIC(a)OTE(b);")
    assert not looks_like_ascii("Pump := Start OR Pump;")


def test_string_literal_spacing_preserved():
    n = "XIC(a)MOV('two  spaces kept',Msg);"
    a = format_ascii(parse_rung(n))
    assert a == "XIC a MOV \"'two  spaces kept'\" Msg"
    assert format_rung(parse_ascii_rung(a)) == n
