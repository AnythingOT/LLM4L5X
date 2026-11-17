from core.rung import parse_rung
from core.validator import errors, validate


def msgs(*texts, tags=None):
    return [str(i) for i in validate([parse_rung(t) for t in texts], tags)]


def test_clean():
    assert msgs("XIC(a)OTE(b);") == []


def test_unknown_instruction_and_arity():
    m = " ".join(msgs("FOO(a,b)OTE(c);", "XIC(a,b)OTE(c);"))
    assert "unknown instruction FOO" in m and "XIC takes 1 operands, got 2" in m


def test_must_end_in_output():
    assert any("does not end in an output" in x for x in msgs("XIC(a)XIC(b);"))
    assert any("does not end in an output" in x for x in msgs("XIC(a)[OTE(b) ,XIC(c) ];"))


def test_write_to_literal_and_placeholder():
    m = " ".join(msgs("XIC(a)MOV(1,5);", "XIC(a)OTE(?);"))
    assert "writes to a literal 5" in m and "is '?'" in m


def test_ons_reuse_and_duplicate_coil_and_timer_reuse():
    m = " ".join(msgs("XIC(a)ONS(s)OTE(b);", "XIC(c)ONS(s)OTE(b);", "XIC(a)TON(t,?,?);", "XIC(b)TON(t,?,?);"))
    assert "ONS storage bit s already used" in m
    assert "duplicate destructive coil" in m
    assert "timer t driven by more than one" in m


def test_types_and_unknown_tags():
    tags = {"a": "BOOL", "n": "DINT", "t": "TIMER"}
    m = " ".join(msgs("XIC(n)OTE(a);", "XIC(a)TON(n,?,?);", "XIC(zz)OTE(a);", "XIC(t.DN)OTE(a);", tags=tags))
    assert "n is DINT, needs BOOL" in m
    assert "n is DINT, needs TIMER" in m
    assert "tag zz does not exist" in m
    assert "t.DN" not in m  # member access of an existing tag is fine


def test_levels():
    issues = validate([parse_rung("XIC(a)[,XIC(b) ]OTE(c);")])
    assert issues and not errors(issues)


def test_writing_timer_status_bit_warned():
    assert any("status bit" in m for m in msgs("XIC(a)OTE(T1.DN);"))


def test_mnemonics_checked_against_target_version():
    v35 = [str(i) for i in validate([parse_rung("GT(a,1)MOVE(1,b);")], revision="35.01")]
    assert any("GT needs v36+, target is v35; use GRT" in m for m in v35)
    assert any("MOVE needs v36+" in m and "use MOV" in m for m in v35)
    v36 = validate([parse_rung("GRT(a,1)MOV(1,b);")], revision="v36.00")
    assert [i.level for i in v36] == ["warning", "warning"]
    assert "GRT was renamed GT in v36" in v36[0].message
    assert validate([parse_rung("GT(a,1)MOVE(1,b);")], revision="36.00") == []
    assert validate([parse_rung("GRT(a,1)MOV(1,b);")]) == []  # unknown target: both accepted
