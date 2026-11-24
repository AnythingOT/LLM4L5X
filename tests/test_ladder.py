"""Ladder diagrams: valid SVG, the right symbols, outputs on the right rail."""
from lxml import etree

from core.rung import parse_rung
from explain.ladder import to_svg

NS = {"s": "http://www.w3.org/2000/svg"}


def svg(text, **kw):
    return etree.fromstring(to_svg(parse_rung(text), **kw).encode())


def texts(root):
    return [t.xpath("string(text())", namespaces=NS) for t in root.iterfind(".//s:text", NS)]


def test_contacts_coil_and_rails():
    root = svg("XIC(Start)[XIC(Run) ,XIO(Stop) ]OTE(Motor);", number=0)
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert {"Start", "Run", "Stop", "Motor", "0"} <= set(texts(root))
    rails = [ln.get("class") for ln in root.iterfind(".//s:line", NS) if "lad-rail" in ln.get("class", "")]
    assert rails == ["lad-rail lad-left", "lad-rail lad-right"]  # a live page keeps the supply (left) energized
    assert len(root.findall(".//s:line[@class='lad-bar']", NS)) == 2  # one branch: two vertical bars
    assert len(root.findall(".//s:path", NS)) == 1  # the coil


def test_boxes_show_operand_names_and_values():
    t = texts(svg("XIC(A)TON(T1,5000,0);"))
    assert {"TON", "Timer", "T1", "Preset", "5000", "Accum"} <= set(t)


def test_outputs_are_pushed_to_the_right_rail():
    root = svg("XIC(A)OTE(B);")
    width = float(root.get("width"))
    coil = next(t for t in root.iterfind(".//s:text", NS) if t.text == "B")
    x = float(coil.get("x")) + sum(float(g.get("transform").split("(")[1].split(",")[0])
                                   for g in coil.iterancestors("{http://www.w3.org/2000/svg}g") if g.get("transform"))
    assert x > width * 0.75


def test_long_tags_are_cut_but_kept_in_a_tooltip():
    root = svg("XIC(A_Very_Long_Tag_Name_That_Goes_On_And_On)OTE(B);")
    cut = [t for t in texts(root) if "…" in t]
    assert cut and cut[0].startswith("A_Very") and cut[0].endswith("On_And_On")  # cut in the middle
    assert any("Goes_On_And_On" in (x.text or "") for x in root.iterfind(".//s:title", NS))


def test_long_tags_that_differ_at_the_end_stay_apart():
    # Tracer lesson: corner suffixes (_LF, _LR) are what tells such tags apart, so the end must survive
    root = svg("XIC(BUG01_SFTY.IO_UP_LIMIT_SWITCH_LF)XIC(BUG01_SFTY.IO_UP_LIMIT_SWITCH_LR)OTE(B);")
    cut = [t for t in texts(root) if "…" in t]
    assert len(cut) == 2 and cut[0] != cut[1] and cut[0].endswith("_LF") and cut[1].endswith("_LR")


def test_every_wire_names_the_power_it_carries():
    # the live page lights a wire from the simulator's trace: element path + in/out side
    root = svg("[XIC(A) ,XIC(B) ]XIO(C)OTE(D);")
    at = {ln.get("data-p") for ln in root.iterfind(".//s:line", NS) if ln.get("data-p")}
    assert {"0:in", "0:out", "0.0.0:in", "0.0.0:out", "0.1.0:out", "1:in", "1:out", "2:in", "2:out"} <= at


def test_special_characters_are_escaped():
    etree.fromstring(to_svg(parse_rung('MOV(Arr[Idx+1],Dest);')).encode())


def test_res_is_drawn_as_a_coil_like_studio_5000():
    svg = to_svg(parse_rung("XIC(Go)RES(Fill_Count);"))
    assert "lad-box" not in svg            # not an instruction box
    assert ">RES</text>" in svg and ">Fill_Count</text>" in svg


def test_a_question_mark_preset_shows_the_tag_preset():
    # exports write TON(T,?,?); the preset is in the tag's data
    svg = to_svg(parse_rung("XIC(Go)TON(Fill_TMR,?,?);"), presets={"Fill_TMR": 5000})
    assert ">5000</text>" in svg and ">?</text>" in svg      # preset filled, accum still '?'
    assert ">?</text>" in to_svg(parse_rung("XIC(Go)TON(Other_TMR,?,?);"), presets={"Fill_TMR": 5000})
    assert ">7</text>" in to_svg(parse_rung("XIC(Go)TON(Fill_TMR,7,0);"), presets={"Fill_TMR": 5000})  # written wins


def test_contacts_and_coils_carry_their_tag_for_a_live_page():
    root = svg("XIC(A)XIO(B.DN)[OTE(C) ,OTL(D) ];")
    els = {(g.get("data-kind"), g.get("data-tag")) for g in root.iterfind(".//s:g[@class='lad-el']", NS)}
    assert els == {("XIC", "A"), ("XIO", "B.DN"), ("OTE", "C"), ("OTL", "D")}
