from datetime import datetime
from pathlib import Path

from lxml import etree

from l5x.reader import read_l5x
from l5x.writer import write_routine, write_rungs
from l5x.xref import cross_reference
from core.compiler import compile_spec
from explain.decompiler import try_decompile
from core.validator import errors, validate

FIX = Path(__file__).parent / "fixtures" / "sample_project.L5X"
SPEC = """Pump := (Start_PB OR Pump) AND NOT Stop_PB;
Alarm := DELAY(Level > 80, 5s);
IF RISE(Reset_PB) THEN RESET Latched, COUNT_UP(Resets, 3);"""


def test_write_rungs_round_trip():
    res = compile_spec(SPEC)
    xml = write_rungs(res.rungs, res.tags.values(), date=datetime(2026, 1, 2, 3, 4, 5))
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
    root = etree.fromstring(xml.encode())
    assert root.get("TargetType") == "Rung" and root.get("TargetCount") == str(len(res.rungs))
    assert root.get("ExportDate") == "Fri Jan 02 03:04:05 2026"
    rungs = root.findall(".//Rung")
    assert [r.get("Number") for r in rungs] == [str(i) for i in range(len(res.rungs))]
    assert all(r.get("Use") == "Target" for r in rungs)

    p = read_l5x(xml)
    got = [r.text for rt in p.routines for r in rt.rungs]
    assert got == res.texts
    assert p.tags["L4X_TMR_1"].preset == 5000
    assert p.tags["Resets"].preset == 3 and p.tags["Resets"].datatype == "COUNTER"
    # integer literal only -> DINT; a project export or "80.0" makes it REAL
    assert p.tags["Level"].datatype == "DINT"


def test_write_routine_and_program_scope():
    res = compile_spec("X := A;")
    xml = write_routine(res.rungs, res.tags.values(), routine="Gen", scope="program")
    root = etree.fromstring(xml.encode())
    assert root.get("TargetType") == "Routine" and root.get("TargetName") == "Gen"
    assert root.find(".//Program/Tags/Tag") is not None
    assert root.find("Controller/Tags") is None
    assert root.find(".//Routine").get("Use") == "Target"


def test_special_characters_escaped():
    res = compile_spec("X := A;")
    res.rungs[0] = res.rungs[0].__class__(res.rungs[0].body, 'Comment with <tags> & "quotes" and ]]> end')
    xml = write_rungs(res.rungs, res.tags.values())
    p = read_l5x(xml)
    assert p.routines[0].rungs[0].comment == 'Comment with <tags> & "quotes" and ]]> end'


def test_read_fixture():
    p = read_l5x(FIX)
    assert p.controller == "Demo" and p.software_revision == "32.04"
    assert "Valve_UDT" in p.udts and ("Position", "REAL") in p.udts["Valve_UDT"]
    assert p.tag_types("MainProgram")["HighAlarm"] == "BOOL"
    assert "HighAlarm" not in p.tag_types()
    main = next(r for r in p.routines if r.name == "MainRoutine")
    assert main.rungs[0].comment == "Pump seal-in"
    assert main.rungs[4].rung is None and "column" in main.rungs[4].parse_error
    assert next(r for r in p.routines if r.name == "Calc").rungs == []
    assert p.presets() == {"HighTmr": 5000}


def test_aoi_extends_catalog_and_validates():
    p = read_l5x(FIX)
    cat = p.catalog()
    aoi = cat.get("Motor_AOI")
    assert [o.name for o in aoi.operands] == ["instance", "Start", "Running"]
    main = next(r for r in p.routines if r.name == "MainRoutine")
    rungs = [r.rung for r in main.rungs if r.rung]
    assert not errors(validate(rungs, p.tag_types("MainProgram"), catalog=cat))


def test_xref():
    p = read_l5x(FIX)
    x = cross_reference(p)
    roles = sorted((r.rung, r.instruction, r.role) for r in x["Pump"])
    assert roles == [(0, "OTE", "write"), (0, "XIC", "read"), (3, "Motor_AOI", "write")]
    assert [r.operand for r in x["HighTmr"]] == ["HighTmr", "HighTmr.DN"]


def test_decompile_fixture_with_presets():
    p = read_l5x(FIX)
    main = next(r for r in p.routines if r.name == "MainRoutine")
    out = [try_decompile(r.rung, p.presets())[0] for r in main.rungs[:3]]
    assert all(out)


def test_survey_on_fixture_folder():
    from explain.survey import survey
    s = survey(FIX.parent)
    assert s.files == 1 and s.rungs == 5 and s.parsed == 4
    assert s.exact_round_trip == 4 and s.convertible == 3
    assert "exact round trip" in s.report()


def test_string_types_and_protected_aoi_from_l5x():
    xml = FIX.read_text().replace(
        "<DataTypes>",
        '<DataTypes>\n<DataType Name="STR_20" Family="StringFamily" Class="User"><Members/></DataType>', 1,
    ).replace(
        "</AddOnInstructionDefinitions>",
        '<EncodedData EncryptionConfig="3" Type="AddOnInstructionDefinition" Name="Locked_AOI">x</EncodedData>\n'
        "</AddOnInstructionDefinitions>", 1,
    )
    p = read_l5x(xml)
    assert p.string_types == {"STRING", "STR_20"}
    assert p.protected_aois == {"Locked_AOI"}
    spec = p.catalog().get("Locked_AOI")
    assert spec.variadic and spec.arity_ok(1) and spec.arity_ok(5)
