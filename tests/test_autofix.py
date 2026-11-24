"""Lint auto-fix: what is safe is proven so, what changes behaviour says so, the rest of the file is untouched."""
from pathlib import Path

import pytest
from lxml import etree

import lint
from l5x.reader import read_l5x
from lint.autofix import AutoFix, fix_file

FIX = Path(__file__).parent / "fixtures"

CASES = [  # rung text (None: an empty rung), comment
    (None, None),                                   # WAR006: deleted
    ("XIC(Start_PB)XIC(Start_PB)XIO(Stop_PB)OTE(Out_A);", None),   # ERR010: repeated condition
    ("[XIC(In_D) ,XIC(In_D) ]OTE(Out_E);", None),   # ERR010: identical parallel legs
    ("XIC(In_F)DIV(Num_X,Num_Y,Num_Z);", None),     # ERR012: division by a tag
    ("XIC(In_G)ONS(Shared_ONS)OTE(Out_H);", None),  # ERR015: storage shared ...
    ("XIC(In_I)ONS(Shared_ONS)OTE(Out_J);", None),  # ... by two one-shots
    ("XIC(In_K)TON(Zero_TMR,?,?);", None),          # WAR008: preset 0, nothing sets it
    (None, "Section: pumps"),                       # an empty heading rung: keeps its comment, gets a NOP()
]
TAGS = ([("BOOL", n, "Read/Write") for n in ("Out_A", "In_D", "Out_E", "In_F", "In_G", "Out_H", "In_I", "Out_J",
                                              "In_K", "Shared_ONS")]
        + [("DINT", n, "Read/Write") for n in ("Num_X", "Num_Y", "Num_Z")]
        + [("BOOL", "Unused_Hidden", "None"), ("BOOL", "Unused_Shown", "Read/Write")])


def project() -> bytes:
    """The sample project with one case per fixable rule added."""
    root = etree.fromstring((FIX / "sample_project.L5X").read_bytes(),
                            etree.XMLParser(strip_cdata=False, remove_blank_text=False))
    tags = root.find("Controller/Tags")
    for dtype, name, access in TAGS:
        t = etree.SubElement(tags, "Tag", Name=name, TagType="Base", DataType=dtype, Radix="Decimal",
                             Constant="false", ExternalAccess=access)
        etree.SubElement(t, "Data", Format="L5K").text = etree.CDATA("0")
    t = etree.SubElement(tags, "Tag", Name="Zero_TMR", TagType="Base", DataType="TIMER", Constant="false",
                         ExternalAccess="Read/Write")
    etree.SubElement(t, "Data", Format="L5K").text = etree.CDATA("[0,0,0]")
    dec = etree.SubElement(etree.SubElement(t, "Data", Format="Decorated"), "Structure", DataType="TIMER")
    etree.SubElement(dec, "DataValueMember", Name="PRE", DataType="DINT", Radix="Decimal", Value="0")
    rt = root.find("Controller/Programs/Program/Routines/Routine[@Name='Fixes']")
    if rt is None:
        rt = etree.SubElement(root.find("Controller/Programs/Program/Routines"), "Routine", Name="Fixes", Type="RLL")
    rll = etree.SubElement(rt, "RLLContent")
    for n, (text, comment) in enumerate(CASES):
        r = etree.SubElement(rll, "Rung", Number=str(n), Type="N")
        if comment:
            etree.SubElement(r, "Comment").text = etree.CDATA(comment)
        etree.SubElement(r, "Text").text = etree.CDATA(text or ";")
    # the routine must be called, or WAR004 hides nothing here but it would be odd
    main = root.find("Controller/Programs/Program/Routines/Routine[@Name='MainRoutine']/RLLContent")
    jsr = etree.SubElement(main, "Rung", Number=str(len(main)), Type="N")
    etree.SubElement(jsr, "Text").text = etree.CDATA("JSR(Fixes,0);")
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + etree.tostring(root, encoding="UTF-8")


def codes(data: bytes) -> list[str]:
    return sorted(f.code for f in lint.run(read_l5x(data)).findings
                  if f.code in ("WAR006", "ERR010", "ERR012", "ERR015", "INF001", "WAR008"))


@pytest.fixture
def fixes():
    return {(f.code, f.where.split(" / ")[-1] if " / " in f.where else f.where): f for f in AutoFix(project()).proposals()}


def test_every_case_is_found_before_fixing():
    assert codes(project()) == ["ERR010", "ERR010", "ERR012", "ERR015", "INF001", "INF001", "WAR006", "WAR006",
                                "WAR008"]


def test_safe_fixes_are_proven_safe_in_the_simulator(fixes):
    for key in [("WAR006", "Rung 0"), ("ERR010", "Rung 1"), ("ERR010", "Rung 2")]:
        f = fixes[key]
        assert f.safe and f.checked == "same behaviour in the simulator" and not f.change, key


def test_fixes_that_change_behaviour_say_what_changes(fixes):
    div = fixes[("ERR012", "Rung 3")]
    assert not div.safe and "when Num_Y is 0 the division does not run" in div.change
    ons = fixes[("ERR015", "Rung 4")]
    assert not ons.safe and "own rising edge" in ons.change
    pre = fixes[("WAR008", "Controller:Zero_TMR")]
    assert not pre.safe and pre.needs == "preset in ms"


def test_a_tag_is_deleted_safely_only_if_nothing_outside_the_logic_can_reach_it(fixes):
    assert fixes[("INF001", "Controller:Unused_Hidden")].safe
    shown = fixes[("INF001", "Controller:Unused_Shown")]
    assert not shown.safe and "an HMI, SCADA or another controller may still read it" in shown.change


def test_an_empty_rung_with_a_comment_is_a_heading_and_gets_a_nop(fixes):
    f = fixes[("WAR006", "Rung 7")]
    assert f.safe and "NOP()" in f.what and "comment stays" in f.what


def test_applying_everything_clears_every_finding_and_keeps_the_rest_of_the_file():
    before = project()
    out, done, still = fix_file(before, lambda f: "5000" if f.needs else True)
    assert len(done) == 9 and still == []
    p = read_l5x(out)
    fixes_rt = next(r for r in p.routines if r.name == "Fixes")
    texts = [r.text for r in fixes_rt.rungs]
    assert texts == ["XIC(Start_PB)XIO(Stop_PB)OTE(Out_A);", "XIC(In_D)OTE(Out_E);",
                     "XIC(In_F)NEQ(Num_Y,0)DIV(Num_X,Num_Y,Num_Z);", "XIC(In_G)ONS(Shared_ONS)OTE(Out_H);",
                     "XIC(In_I)ONS(Shared_ONS_2)OTE(Out_J);", "XIC(In_K)TON(Zero_TMR,?,?);", "NOP();"]
    assert fixes_rt.rungs[-1].comment == "Section: pumps"
    assert [r.number for r in fixes_rt.rungs] == list(range(7))  # renumbered after the deletion
    assert p.presets()["Zero_TMR"] == 5000 and "Shared_ONS_2" in p.tags
    assert "Unused_Hidden" not in p.tags and "Unused_Shown" not in p.tags
    # everything the fixes did not touch is as it was: the other routines, word for word
    old = {r.name: [x.text for x in r.rungs] for r in read_l5x(before).routines if r.name != "Fixes"}
    new = {r.name: [x.text for x in r.rungs] for r in p.routines if r.name != "Fixes"}
    assert old == new


def test_only_the_safe_batch_when_every_question_is_answered_no():
    out, done, still = fix_file(project(), lambda f: False, safe_all=True)
    assert [d.split(" ")[0] for d in done] == ["WAR006", "WAR006", "ERR010", "ERR010", "INF001"]
    assert codes(out) == ["ERR012", "ERR015", "INF001", "WAR008"]


def test_two_fixes_on_one_rung_both_take_effect():
    data = project().replace(b"XIC(In_F)DIV(Num_X,Num_Y,Num_Z);", b"XIC(In_F)XIC(In_F)DIV(Num_X,Num_Y,Num_Z);")
    out, _, _ = fix_file(data, lambda f: "5000" if f.needs else True)
    texts = [r.text for r in next(r for r in read_l5x(out).routines if r.name == "Fixes").rungs]
    assert "XIC(In_F)NEQ(Num_Y,0)DIV(Num_X,Num_Y,Num_Z);" in texts


def test_a_preset_must_be_above_zero():
    af = AutoFix(project())
    pre = [f for f in af.proposals() if f.code == "WAR008"]
    with pytest.raises(ValueError, match="above 0"):
        af.apply(pre, {0: "0"})


def test_outside_the_fixed_rungs_the_xml_is_the_same():
    # compared in canonical form, with rung texts blanked: only the fixed rungs may differ
    parser = etree.XMLParser(strip_cdata=False)

    def canon(b):
        root = etree.fromstring(b, parser)
        for r in root.iter("Rung"):
            for el in r:
                el.text = ""
            r.set("Number", "")
        return etree.tostring(root, method="c14n")

    af = AutoFix(project())
    af.apply([f for f in af.proposals() if f.code == "ERR010"])
    assert canon(af.write()) == canon(project())


def test_command_line_asks_checks_values_and_writes_a_new_file(tmp_path, monkeypatch, capsys):
    import cli
    src = tmp_path / "p.L5X"
    src.write_bytes(project())
    # safe batch: yes; division: yes; one-shots: no; preset: "abc" (asked again), then 5000; HMI tags: no
    answers = iter(["y", "y", "n", "abc", "5000", "n"])
    monkeypatch.setattr("builtins.input", lambda _q: next(answers))
    assert cli.main(["fix", str(src)]) == 0
    out = capsys.readouterr().out
    assert "A number above 0, please." in out and "written to" in out
    fixed = (tmp_path / "p_fixed.L5X").read_bytes()
    assert src.read_bytes() == project()  # the original is never overwritten
    assert codes(fixed) == ["ERR015", "INF001"]  # what was declined is still there
    assert read_l5x(fixed).presets()["Zero_TMR"] == 5000


def test_command_line_safe_only_asks_nothing(tmp_path, monkeypatch):
    import cli
    src = tmp_path / "p.L5X"
    src.write_bytes(project())
    monkeypatch.setattr("builtins.input", lambda _q: pytest.fail("--safe must not ask"))
    assert cli.main(["fix", str(src), "--safe", "-o", str(tmp_path / "out.L5X")]) == 0
    assert codes((tmp_path / "out.L5X").read_bytes()) == ["ERR012", "ERR015", "INF001", "WAR008"]
