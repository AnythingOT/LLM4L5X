"""Lint rules. The fixture breaks every rule at a known place and keeps a compliant
twin next to it, so a rule that never fires, or fires everywhere, fails here."""

from pathlib import Path

import pytest

import lint
from core.rung import parse_rung
from l5x.reader import read_l5x
from lint.registry import CHECKS
from lint.rules import BY_CODE, RULES

FIX = Path(__file__).parent / "fixtures" / "lint_project.L5X"


@pytest.fixture(scope="module")
def project():
    return read_l5x(FIX)


@pytest.fixture(scope="module")
def found(project):
    return {(f.code, f.location) for f in lint.run(project).findings}


def where(found, code):
    return {loc for c, loc in found if c == code}


def test_every_rule_has_a_check_and_every_check_a_rule():
    emitted = {c for codes, _ in CHECKS for c in codes}
    assert emitted == set(BY_CODE)
    assert len(RULES) == 49 and len(BY_CODE) == 49


def test_every_rule_fires_on_the_fixture(found):
    fired = {c for c, _ in found}
    assert set(BY_CODE) - fired == {"ERR007"}  # the fixture has a valid fault handler: tested below


@pytest.mark.parametrize("code, hit, clean", [
    ("CRT002", "Main / R / Rung 0", None),
    ("ERR001", "Main / R / Rung 1", None),
    ("ERR002", "Main / R / Rung 3", None),
    ("ERR003", "Main / R / Rung 5", None),
    ("ERR004", "Main / R / Rung 7", None),
    ("ERR005", "Main / R / Rung 8", None),
    ("ERR006", "Main / R / Rung 9", None),
    ("ERR009", "AOI:Motor_AOI / Logic / Rung 0", None),
    ("ERR010", "Main / R / Rung 11", None),
    ("ERR010", "Main / R / Rung 12", None),
    ("ERR011", "Main / R / Rung 13", "Main / R / Rung 14"),
    ("ERR012", "Main / R / Rung 15", "Main / R / Rung 16"),
    ("ERR013", "Main / R / Rung 18", None),
    ("ERR014", "Main / R / Rung 19", "Main / R / Rung 24"),
    ("ERR015", "Main / R / Rung 21", None),
    ("ERR016", "Main / R / Rung 23", "Main / R / Rung 24"),
    ("ERR017", "Module:Comms", "Module:In1"),
    ("ERR008", "Program:NoFault", "Program:FaultHandler"),
    ("ERR008", "Program:Unsched", "Program:Main"),
    ("WAR001", "Controller:WrongStd", "Controller:STD_EStop"),
    ("WAR002", "Controller:BadProd", "Controller:Line2_PRO_100MS"),
    ("WAR002", "Controller:WrongCon", "Controller:FromL2_CON_100MS"),
    ("WAR003", "Task:Fast", "Task:Task_20MS"),
    ("WAR004", "Main / Orphan", "Main / Sub4"),
    ("WAR005", "Program:Unsched", "Program:FaultHandler"),
    ("WAR006", "Main / R / Rung 27", None),
    ("WAR007", "Main / R / Rung 28", None),
    ("WAR008", "Controller:ZeroTmr", "Controller:OkTmr"),
    ("WAR009", "Task:Fast", "Task:Task_20MS"),
    ("WAR010", "DataType:Pad_UDT", "DataType:Order_UDT"),
    ("WAR011", "DataType:Order_UDT", "DataType:Good_UDT"),
    ("WAR013", "Main / R / Rung 9", None),
    ("WAR014", "Main / R", None),
    ("WAR015", "Main / R / Rung 31", None),
    ("WAR016", "Controller:IntTag", "Controller:DintTag"),
    ("WAR017", "IO:Local:2:I.Data.2", "IO:Local:2:I.Data.0"),
    ("WAR018", "IO:Local:2:I.Data.1", "IO:Local:2:I.Data.0"),
    ("WAR019", "Controller:SpareUsed", None),
    ("WAR020", "DataType:Unused_UDT", "DataType:Good_UDT"),
    ("WAR020", "AOI:Unused_AOI", "AOI:Motor_AOI"),
    ("WAR021", "Module:Cpu2", None),
    ("WAR022", "Controller:AlPB", None),
    ("INF001", "Controller:UnusedTag", "Controller:DintTag"),
    ("INF003", "Controller:NoDescUsed", "Controller:DintTag"),
    ("INF004", "Main / R / Rung 35", "Main / R / Rung 34"),
    ("INF005", "AOI:Unused_AOI", None),
    ("INF006", "DataType:NoDesc_UDT", "DataType:Good_UDT"),
    ("INF007", "Main / R / Rung 32", "Main / R / Rung 31"),
    ("INF008", "Module:In1", "Module:Comms"),
    ("INF009", "Module:Comms2", None),
])
def test_rule_hits_the_violation_and_not_its_twin(found, code, hit, clean):
    assert hit in where(found, code)
    if clean:
        assert clean not in where(found, code)


def test_alias_and_comment_cover_io_points(found):
    unmapped = where(found, "WAR017")
    assert "IO:Local:2:I.Data.7" not in unmapped  # covered by alias AlPB (WAR022 says so instead)
    assert "IO:Local:2:I.Data.1" not in unmapped  # used directly


def test_individually_used_bits_need_a_comment(project):
    msgs = [f.message for f in lint.run(project).findings if f.code == "INF003"]
    assert any("'Flags.3' has no comment" in m for m in msgs)
    assert not any("'Flags.2'" in m for m in msgs)  # commented in the tag


def test_controller_fault_handler_variants(project):
    import copy
    p = copy.copy(project)
    p.major_fault_program = None
    r = lint.run(p)
    assert "ERR007" in r.not_verified and not [f for f in r.findings if f.code == "ERR007"]
    p.major_fault_program = ""
    assert [f for f in lint.run(p).findings if f.code == "ERR007"]
    p.major_fault_program = "Missing"
    assert "not in the project" in [f for f in lint.run(p).findings if f.code == "ERR007"][0].message


def test_disabled_rules_do_not_run(project):
    r = lint.run(project, disabled={"ERR001", "inf004"})
    codes = {f.code for f in r.findings}
    assert "ERR001" not in codes and "INF004" not in codes and "ERR002" in codes
    assert r.disabled == ["ERR001", "INF004"]


def test_severity_comes_from_the_code(project):
    r = lint.run(project)
    assert all(f.severity == {"CRT": "critical", "ERR": "error", "WAR": "warning", "INF": "info"}[f.code[:3]]
               for f in r.findings)
    order = [f.severity for f in r.findings]
    assert order == sorted(order, key=["critical", "error", "warning", "info"].index)


def test_lint_disable_in_a_rung_comment_hides_but_keeps_the_finding():
    xml = FIX.read_text(encoding="utf-8").replace(
        '<Rung Number="11" Type="N"><Comment><![CDATA[c]]>',
        '<Rung Number="11" Type="N"><Comment><![CDATA[double contact on purpose lint:disable=ERR010]]>')
    r = lint.run(read_l5x(xml))
    assert ("ERR010", "Main / R / Rung 11") not in {(f.code, f.location) for f in r.findings}
    assert ("ERR010", "Main / R / Rung 11") in {(f.code, f.location) for f in r.suppressed}
    assert ("ERR010", "Main / R / Rung 12") in {(f.code, f.location) for f in r.findings}


def test_partial_export_runs_only_rung_rules():
    xml = FIX.read_text(encoding="utf-8").replace('TargetType="Controller"', 'TargetType="Routine"')
    r = lint.run(read_l5x(xml))
    assert {BY_CODE[f.code].scope for f in r.findings} == {"rung"}
    assert any("only the" in n for n in r.notes)


def test_check_rungs_on_generated_logic():
    rungs = [parse_rung("XIC(a)OTE(b);"), parse_rung("XIC(c)OTE(b);"), parse_rung("XIC(a)DIV(x,y,z);"),
             parse_rung("XIC(a)ONS(os)OTE(p);"), parse_rung("XIC(c)ONS(os)OTE(q);")]
    got = {(f.code, f.location) for f in lint.check_rungs(rungs, {"x": "DINT", "y": "DINT", "z": "DINT"})}
    assert ("ERR001", "Rung 0") in got and ("ERR012", "Rung 2") in got and ("ERR015", "Rung 3") in got
    assert not {c for c, _ in got} - {r.code for r in RULES if r.scope == "rung"}


def test_a_crashing_check_is_reported_not_hidden(project, monkeypatch):
    def boom(ctx):
        raise RuntimeError("bad")
    patched = [((("CRT002",), boom) if codes == ("CRT002",) else (codes, fn)) for codes, fn in CHECKS]
    monkeypatch.setattr("lint.CHECKS", patched)
    r = lint.run(project)
    assert any(e.startswith("boom") for e in r.errors)
    assert "ERR001" in {f.code for f in r.findings}  # the other rules still ran
