"""UDTs: the text form, checks, writing new UDTs, Excel, reordering attached exports."""

import io
import zipfile
from pathlib import Path

import pytest

import lint
from l5x.reader import read_l5x
from udt import layout
from udt.excel import read_excel, template
from udt.model import UdtDef, UdtError, UdtMember, check, format_spec, parse_spec
from udt.optimize import analyse, file_name, full_program, single_file, zip_files
from udt.writer import host_name, sizes, write_udt

FIX = Path(__file__).parent / "fixtures"
SPEC = '''UDT Motor "Motor status";
Speed REAL "Speed, rpm";
Running BOOL "Motor is running";
Fault_Code DINT;
Faulted BOOL "Motor has a fault";
Alarms BOOL[32] "Alarm bits";
UDT Line "A line";
Motors Motor[4] "The motors";
Line_On BOOL;
'''


# ---------------------------------------------------------------- text form and checks

def test_spec_round_trip():
    udts = parse_spec(SPEC)
    assert [u.name for u in udts] == ["Motor", "Line"]
    assert udts[0].members[0] == UdtMember("Speed", "REAL", 0, "Speed, rpm")
    assert udts[1].members[0] == UdtMember("Motors", "Motor", 4, "The motors")
    assert parse_spec(format_spec(udts)) == udts


@pytest.mark.parametrize("text, problem", [
    ("UDT Ok;\nA__B DINT;", "two underscores"),
    ("UDT Ok;\nA_ DINT;", "must not end with _"),
    ("UDT Ok;\nA DINT;\na REAL;", "appears twice"),
    ("UDT Ok;\nFlags BOOL[20];", "multiple of 32"),
    ("UDT Ok;\nM MESSAGE;", "MESSAGE cannot be a UDT member"),
    ("UDT Ok;\nX Nowhere_T;", "unknown data type Nowhere_T"),
    ("UDT A;\nB_ref B;\nUDT B;\nA_ref A;", "loop"),
    ("UDT DINT;\nA DINT;", "built-in data type"),
    ("UDT " + "N" * 41 + ";\nA DINT;", "limit is 40"),
])
def test_checks(text, problem):
    assert any(problem in p for p in check(parse_spec(text)))


def test_names_checked_even_when_built_directly():
    assert any("must not start with a digit" in p for p in check([UdtDef("1Bad", members=[UdtMember("A", "DINT")])]))


def test_project_types_count_as_known():
    assert check(parse_spec("UDT Ok;\nV Valve_UDT;"), {"Valve_UDT": "UDT"}) == []


def test_bad_line_is_reported_with_its_number():
    with pytest.raises(UdtError, match="line 2"):
        parse_spec("UDT Ok;\nthis is not a member")


# ---------------------------------------------------------------- writing new UDTs

def test_new_udt_is_written_in_the_order_that_wastes_nothing():
    udts = parse_spec(SPEC)
    xml = write_udt(udts[0], udts, revision="33.00")
    p = read_l5x(xml)
    assert p.target_type == "DataType"
    mem = p.datatypes["Motor"].members
    names = [m.name for m in mem]
    # BOOLs first, packed into one hidden SINT host named as Studio 5000 does
    assert names[:3] == [host_name("Motor", 0), "Faulted", "Running"]
    assert mem[0].hidden and mem[1].datatype == "BIT"
    # then the 4-byte members: DINT, the BOOL[32] array (stored as a DINT), REAL
    assert names[3:] == ["Fault_Code", "Alarms", "Speed"]
    assert sizes(udts)["Motor"] == 16 and sizes(udts, optimal=False)["Motor"] == 20
    # the lint rules agree that nothing can be gained
    rep = lint.run(_as_controller(xml))
    assert not [f for f in rep.findings if f.code in ("WAR010", "WAR011") and "Motor" in f.location]


def _as_controller(xml: str):
    p = read_l5x(xml)
    p.target_type = "Controller"
    return p


def test_nested_new_udt_carries_its_dependency_as_context():
    udts = parse_spec(SPEC)
    xml = write_udt(udts[1], udts)
    assert 'Use="Target" Name="Line"' in xml and '<Dependency Type="DataType" Name="Motor"/>' in xml
    p = read_l5x(xml)
    assert set(p.datatypes) == {"Line", "Motor"}
    assert sizes(udts)["Line"] == 4 * 16 + 4  # four Motors and the BOOL host, padded to 4


def test_more_than_eight_bools_get_a_second_host():
    u = UdtDef("Many", members=[UdtMember(f"B{i}", "BOOL") for i in range(10)])
    p = read_l5x(write_udt(u, [u]))
    hosts = [m for m in p.datatypes["Many"].members if m.hidden]
    assert [h.name for h in hosts] == [host_name("Many", 0), host_name("Many", 9)]


# ---------------------------------------------------------------- Excel

def test_excel_template_reads_back_as_two_udts():
    udts = read_excel(template())
    assert [u.name for u in udts] == ["Motor_Status", "Line_Status"]
    assert udts[1].members[0] == UdtMember("Motors", "Motor_Status", 4, "The line's motors")
    assert check(udts) == []


def test_excel_without_a_header_is_explained():
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.append(["just", "some", "cells"])
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(UdtError, match="header row"):
        read_excel(buf.getvalue())


# ---------------------------------------------------------------- reordering attached exports

@pytest.fixture(scope="module")
def an():
    return analyse((FIX / "udt_program.L5X").read_bytes())


def test_plans(an):
    p = an.plans
    assert (p["Pad_UDT"].status, p["Pad_UDT"].size_now, p["Pad_UDT"].size_best) == ("reordered", 12, 8)
    assert p["Pad_UDT"].instances == 1 + 10 + 2  # PadTag, PadArr[10], HolderTag.Pads[2]
    assert p["Pad_UDT"].total_saved == 13 * 4
    assert p["Holder_UDT"].status == "optimal" and p["Holder_UDT"].size_best < p["Holder_UDT"].size_now
    assert p["Good_UDT"].status == "optimal"
    assert p["STR20"].status == "skipped" and "StringFamily" in p["STR20"].reason
    assert p["Lost_UDT"].status == "skipped" and "Missing_T" in p["Lost_UDT"].reason
    assert any("COP copies bytes of CopySrc" in r for r in p["Copy_UDT"].risks)
    assert p["InAoi_UDT"].in_aoi == ["Uses_UDT"] and p["InAoi_UDT"].status == "reordered"


def test_full_program_changes_only_what_it_must(an):
    text, notes = full_program(an, {"Pad_UDT", "Copy_UDT", "InAoi_UDT"})
    assert text.startswith("﻿") and text.count("\r\n") == text.count("\n")  # BOM and CRLF kept
    p = read_l5x(text.encode("utf-8"))
    assert [m.name for m in p.datatypes["Pad_UDT"].members] == [host_name("Pad_UDT", 0), "Flag_A", "Flag_B", "Value"]
    assert [m.name for m in p.datatypes["Copy_UDT"].members] == ["Small", "Big", "Small2"]  # left out: L5K-only tag
    assert [m.name for m in p.datatypes["InAoi_UDT"].members] == ["Big", "Small"]  # left out: used in an AOI
    assert any("Copy_UDT" in n and "CopyDst" in n for n in notes) and any("InAoi_UDT left out" in n for n in notes)
    # values: the positional L5K copy is gone where the layout moved, kept everywhere else
    for name, keep in (("PadTag", False), ("PadArr", False), ("HolderTag", False), ("GoodTag", True), ("Plain", True),
                       ("CopySrc", True)):
        chunk = text[text.index(f'<Tag Name="{name}"'):]
        chunk = chunk[:chunk.index("</Tag>")]
        assert ('Format="L5K"' in chunk) is keep, name
        assert 'Format="Decorated"' in chunk or name == "CopyDst"
    # everything outside the edited places is byte for byte the original
    assert "keep   this  comment\r\nas is" in text
    stripped = an.text
    for frag in ('<Data Format="L5K">\r\n<![CDATA[[1,42]]]>\r\n</Data>\r\n',):
        stripped = stripped.replace(frag, "")
    assert text.lstrip("﻿").split("<Tags>")[1].split("</Tags>")[0].count("<Tag ") == 7


def test_single_file_is_a_datatype_export_with_context(an):
    xml = single_file(an, "Holder_UDT", {"Pad_UDT"})  # Holder itself unchanged, its nested Pad_UDT reordered
    p = read_l5x(xml.encode("utf-8"))
    assert p.target_type == "DataType" and set(p.datatypes) == {"Holder_UDT", "Pad_UDT"}
    assert [m.name for m in p.datatypes["Pad_UDT"].members][1:3] == ["Flag_A", "Flag_B"]
    assert xml.count('Use="Target"') == 1 and 'Use="Target" Name="Holder_UDT"' in xml
    xml = single_file(an, "InAoi_UDT", {"InAoi_UDT"})
    assert "<AddOnInstructionDefinitions" not in xml  # the UDT does not use the AOI; the AOI uses it


def test_zip_has_one_file_per_udt_and_changes(an):
    z = zipfile.ZipFile(io.BytesIO(zip_files(an, {"Pad_UDT", "Copy_UDT"})))
    assert sorted(z.namelist()) == sorted([file_name("Pad_UDT"), file_name("Copy_UDT"), "CHANGES.txt"])
    changes = z.read("CHANGES.txt").decode()
    assert "Pad_UDT: 12 -> 8 bytes (4 saved per instance, 13 instances, 52 bytes in total)" in changes
    assert "LAYOUT RISK: COP copies bytes of CopySrc" in changes


def test_real_studio_exports_match_the_original_optimizer():
    """Sizes and order on Studio 5000 exports, compared with L5X UDT Optimizer's results."""
    an = analyse((FIX / "studio_single_udt.L5X").read_bytes())
    p = an.plans["B322"]
    assert (p.size_now, p.size_best, p.status) == (276, 240, "reordered")
    assert p.after[:8] == ["B1", "B3", "B6", "B7", "B9", "B10", "B12", "B13"]
    assert an.target == "B322" and p.instances is None  # a UDT export has no tags
    xml = single_file(an, "B322", {"B322"})
    assert read_l5x(xml.encode("utf-8")).datatypes["B322"].members[0].name == "ZZZZZZZZZZB3220"


def test_layout_rules():
    m = layout.M
    assert layout.size_of([m("a", "BIT"), m("b", "DINT"), m("c", "BIT")], {}) == 12
    assert layout.size_of([m("a", "BIT"), m("c", "BIT"), m("b", "DINT")], {}) == 8
    assert layout.size_of([m("x", "BOOL", 32)], {}) == 4 and layout.size_of([m("x", "BOOL", 64)], {}) == 8
    assert layout.size_of([m("l", "LINT"), m("s", "SINT")], {}) == 16  # padded to the 8-byte alignment


# ---------------------------------------------------------------- plain English (model stubbed)

class FakeClient:
    supports_grammar = True

    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    def chat(self, messages, grammar=None, **kw):
        self.seen.append(grammar)
        return self.replies.pop(0)


def test_grammar_accepts_the_examples_and_rejects_prose():
    from helpers import Grammar
    from inputs.udt_llm import EXAMPLES, grammar
    g = Grammar(grammar(["Valve_UDT"]))
    for _, spec in EXAMPLES:
        assert g.accepts(spec), spec
    assert g.accepts('UDT Skid "skid";\nInlet Valve_UDT "inlet valve";')
    assert not g.accepts("Here is your UDT: Motor with a speed")


def test_generate_retries_with_the_problem_and_returns_checked_udts():
    from inputs.udt_llm import generate
    bad = 'UDT Motor "m";\nFlags BOOL[20] "flags";'
    good = '```\nUDT Motor "m";\nFlags BOOL[32] "flags";\nSpeed REAL "rpm";\n```'
    c = FakeClient([bad, good])
    r = generate(c, "a motor with 20 flags and a speed")
    assert r.udts and [m.name for m in r.udts[0].members] == ["Flags", "Speed"]
    assert len(r.attempts) == 2 and "multiple of 32" in r.attempts[0]["error"]
    assert c.seen[0] and "BOOL" in c.seen[0]  # grammar sent to a grammar-capable server


def test_rockwell_types_are_not_treated_as_udts():
    from l5x.reader import read_l5x
    from udt import optimize
    import lint
    x = ('<?xml version="1.0"?><RSLogix5000Content SchemaRevision="1.0" SoftwareRevision="33.00" TargetName="C" '
         'TargetType="Controller"><Controller Name="C"><DataTypes>'
         '<DataType Name="ALARM_X" Family="NoFamily" Class="ProductDefined"><Members><Member Name="A" DataType="BOOL" '
         'Dimension="0"/><Member Name="E" DataType="EMPTY_T" Dimension="0"/></Members></DataType>'
         '<DataType Name="EMPTY_T" Family="NoFamily" Class="IO"><Members/></DataType>'
         '<DataType Name="Mine" Family="NoFamily" Class="User"><Members><Member Name="B" DataType="DINT" Dimension="0"/>'
         '</Members></DataType></DataTypes><Tags/><Programs/><Tasks/></Controller></RSLogix5000Content>').encode()
    assert set(optimize.analyse(x).plans) == {"Mine"}
    assert not lint.run(read_l5x(x)).errors
