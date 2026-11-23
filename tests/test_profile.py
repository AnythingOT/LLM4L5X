import pytest

import lint
from core.compiler import TagDef
from core.rung import parse_rung
from l5x.reader import read_l5x
from l5x.writer import write_routine
from lint.profile import ProfileError, load_profile

PROFILE = """
name: Example Co.
naming:
  TIMER: '_(TMR|TON)$'
  any: '^[A-Z]'
banned_instructions: [JMP]
restricted:
  OTL: '_(ALM|Fail)$'
rung_comments: required
disabled_rules: [INF004]
"""


def project(rungs, tags):
    return read_l5x(write_routine([parse_rung(t, c) for t, c in rungs], [TagDef(n, d) for n, d in tags],
                                  routine="Main"))


def codes(report):
    return sorted((f.code, f.message) for f in report.findings if f.code.startswith("STD"))


def test_each_standard_rule_fires_on_a_project():
    p = project([("XIC(Start)OTL(Run_Latch);", "latch the run"), ("XIC(Run_Latch)TON(Delay,500,0);", None),
                 ("XIC(Delay.DN)OTL(Pump_Fail);", "fail")],
                [("Start", "BOOL"), ("Run_Latch", "BOOL"), ("Delay", "TIMER"), ("Pump_Fail", "BOOL")])
    found = codes(lint.run(p, profile=load_profile(PROFILE)))
    assert ("STD001", "Delay (TIMER) does not match the timer pattern '_(TMR|TON)$'") in found
    assert any(c == "STD003" and "OTL(Run_Latch)" in m for c, m in found)       # a latch on a non-alarm
    assert not any(c == "STD003" and "Pump_Fail" in m for c, m in found)        # allowed: a fault
    assert [c for c, _ in found].count("STD004") == 1                           # rung 1 has no comment
    assert all(f.severity in ("warning", "error") for f in lint.run(p, profile=load_profile(PROFILE)).findings)


def test_no_profile_no_standard_findings_and_rule_count_unchanged():
    p = project([("XIC(start)OTE(x);", None)], [("start", "BOOL"), ("x", "BOOL")])
    assert codes(lint.run(p)) == [] and len(lint.RULES) == 50


def test_generated_rungs_are_checked_on_the_tags_they_use():
    found = lint.check_rungs([parse_rung("XIC(a)OTL(Motor_Run);"), parse_rung("XIC(b)OTE(Lamp);", "lamp")],
                             {"a": "BOOL"}, profile=load_profile(PROFILE))
    msgs = [(f.code, f.message) for f in found if f.code.startswith("STD")]
    assert ("STD001", "a (BOOL) does not match the any pattern '^[A-Z]'") in msgs
    assert any(c == "STD003" for c, _ in msgs) and any(c == "STD004" for c, _ in msgs)


def test_profile_switches_rules_off_and_lint_disable_still_works():
    prof = load_profile(PROFILE + "\n")
    prof.disabled_rules |= {"STD004"}
    p = project([("XIC(Start)OTL(Run_Latch);", "lint:disable=STD003")], [("Start", "BOOL"), ("Run_Latch", "BOOL")])
    rep = lint.run(p, profile=prof)
    assert codes(rep) == [] and any(f.code == "STD003" for f in rep.suppressed)
    assert "INF004" in rep.disabled


@pytest.mark.parametrize("text, msg", [
    ("naming: [", "not valid YAML"),
    ("- a\n- b", "a set of keys"),
    ("colours: red", "unknown colours"),
    ("severity: {WAR001: info}", "severity cannot be changed"),
    ("naming: {TIMER: '_(TMR'}", "not a valid pattern"),
    ("rung_comments: sometimes", "required or optional"),
    ("disabled_rules: [XYZ999]", "no such rule XYZ999"),
])
def test_profile_errors_say_what_to_fix(text, msg):
    with pytest.raises(ProfileError, match=msg):
        load_profile(text)


def test_cli_validate_takes_a_profile(tmp_path, capsys):
    import cli
    f = tmp_path / "Main.L5X"
    f.write_bytes(write_routine([parse_rung("XIC(start)OTE(Lamp);")], [TagDef("start", "BOOL"), TagDef("Lamp", "BOOL")],
                                routine="Main").encode())
    prof = tmp_path / "std.yaml"
    prof.write_text("naming: {any: '^[A-Z]'}\n")
    try:
        cli.main(["validate", str(f), "--profile", str(prof)])
    except SystemExit:
        pass
    assert "STD001" in capsys.readouterr().out
