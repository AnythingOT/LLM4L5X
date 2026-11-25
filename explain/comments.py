"""Write the plain-English read of each rung into the L5X as its rung comment.

Only rungs without a comment get one: a comment someone wrote is never replaced. Each added comment starts
with AUTO: so a reviewer can tell it from one a person wrote. Nothing else in the file changes: the file is
edited in place (CDATA, attribute order and layout kept), not rebuilt.
"""

from __future__ import annotations

from lxml import etree

PREFIX = "AUTO: "


def _routines(root):
    """(owner, routine element) as l5x.reader names them: the program name, or AOI:Name."""
    ctrl = root.find("Controller")
    if ctrl is None:
        return
    for prog in ctrl.findall("Programs/Program"):
        for rt in prog.findall("Routines/Routine"):
            yield prog.get("Name"), rt
    for aoi in ctrl.findall("AddOnInstructionDefinitions/AddOnInstructionDefinition"):
        for rt in aoi.findall("Routines/Routine"):
            yield f"AOI:{aoi.get('Name')}", rt


def has_comment(rung) -> bool:
    c = rung.find("Comment")
    return c is not None and bool((c.text or "").strip())


def add_rung_comments(raw: bytes, explained: dict[tuple[str, str, int], str]) -> tuple[bytes, int]:
    """explained: (owner, routine, rung number) -> English. Returns the new file and how many comments were added."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True, strip_cdata=False)
    root = etree.fromstring(raw, parser)
    added = 0
    for owner, rt in _routines(root):
        for rung in rt.findall("RLLContent/Rung"):
            text = explained.get((owner, rt.get("Name"), int(rung.get("Number", -1))))
            if not text or has_comment(rung):
                continue
            old = rung.find("Comment")
            if old is not None:  # an empty <Comment/>: fill it rather than add a second one
                rung.remove(old)
            c = etree.Element("Comment")
            c.text = etree.CDATA(PREFIX + text)
            c.tail = rung.text  # the indentation before the next element, so the layout stays as exported
            rung.insert(0, c)
            added += 1
    head = raw[: raw.index(b"<RSLogix5000Content")]  # BOM and declaration exactly as exported
    return head + etree.tostring(root, encoding="UTF-8"), added
