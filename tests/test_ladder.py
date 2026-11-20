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
    assert len(root.findall(".//s:line[@class='lad-rail']", NS)) == 2
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
                                   for g in coil.iterancestors("{http://www.w3.org/2000/svg}g"))
    assert x > width * 0.75


def test_long_tags_are_cut_but_kept_in_a_tooltip():
    root = svg("XIC(A_Very_Long_Tag_Name_That_Goes_On_And_On)OTE(B);")
    assert any(t.endswith("…") for t in texts(root))
    assert any("Goes_On_And_On" in (x.text or "") for x in root.iterfind(".//s:title", NS))


def test_special_characters_are_escaped():
    etree.fromstring(to_svg(parse_rung('MOV(Arr[Idx+1],Dest);')).encode())


def test_res_is_drawn_as_a_coil_like_studio_5000():
    svg = to_svg(parse_rung("XIC(Go)RES(Fill_Count);"))
    assert "lad-box" not in svg            # not an instruction box
    assert ">RES</text>" in svg and ">Fill_Count</text>" in svg
