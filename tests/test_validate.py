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


# ---- Patterns reported from a real (confidential) project; names here are made up.

TAGS = {"a": "BOOL", "Ctl": "CONTROL", "Dst": "DINT", "Src": "DINT", "Fifo": "DINT", "Dt": "DINT",
        "StrA": "STRING", "StrB": "STR_20", "Flag": "BOOL", "M1": "Vendor_AOI", "T": "TIMER", "N": "DINT"}


def found(*rungs, **kw):
    return [str(i) for i in validate([parse_rung(r) for r in rungs], kw.pop("tags", TAGS), **kw)]


def test_file_instructions_with_control_length_position_and_mode_keyword():
    assert found(
        "XIC(a)FAL(Ctl,?,?,ALL,Dst[Ctl.POS],Src[Ctl.POS]*2);",
        "XIC(a)FSC(Ctl,?,?,ALL,Src[Ctl.POS] = 5)OTE(Flag);",
        "XIC(a)FFL(Src,Fifo[0],Ctl,?,?);",
        "XIC(a)FFU(Fifo[0],Dst,Ctl,?,?);",
    ) == []


def test_gsv_ssv_blank_or_placeholder_instance():
    assert found("GSV(WallClockTime,,DateTime,Dt[0]);", "GSV(Controller,?,Status,Dt[1]);",
                 "XIC(a)SSV(WallClockTime,,DateTime,Dt[0]);") == []
    assert any("attribute_name is empty" in m for m in found("GSV(WallClockTime,,,Dt[0]);"))


def test_string_compare_and_mid():
    strings = {"STR_20"}
    assert found("NE(StrA,StrB)MID(StrA,3,1,StrB);", string_types=strings) == []
    assert found("EQU(StrA,'AB')OTE(Flag);", string_types=strings) == []
    assert any("expected a number or string" in m and "error" in m for m in found("NE(StrA,T)OTE(Flag);"))


def test_aoi_without_definition_is_a_warning_not_an_error():
    issues = validate([parse_rung("XIC(a)Vendor_AOI(M1,Src,Dst);")], TAGS)
    assert [i.level for i in issues] == ["warning"]
    assert "definition is not in this export" in issues[0].message
    assert any("unknown instruction Nope" in m for m in found("XIC(a)Nope(M1);"))


def test_repeated_problem_reported_once_per_rung():
    issues = validate([parse_rung("[Nope(a) ,Nope(a) ,Nope(a) ]OTE(Flag);")], TAGS)
    assert sum("unknown instruction Nope" in i.message for i in issues) == 1


def test_real_findings_still_reported():
    m = found("XIC(a)OTE(N.3);", "XIC(Flag)OTE(N.3);", "XIC(a)OTL(T.DN);")
    assert any("duplicate destructive coil" in x for x in m)
    assert any("status bit" in x for x in m)
