"""Deterministic L5X writer for Rung and Routine imports.

Built with lxml so names and comments are escaped correctly. The layout
mirrors Studio 5000 exports; items marked UNVERIFIED in HANDOFF.md
section 9 (tag data formats, Use attributes) must be confirmed by importing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from lxml import etree

from core.compiler import TagDef
from core.rung import Rung, format_rung

EXPORT_OPTIONS = (
    "References NoRawData L5KData DecoratedData Context Dependencies "
    "ForceProtectedEncoding AllProjDocTrans"
)


def _cdata(parent, tag: str, text: str):
    el = etree.SubElement(parent, tag)
    el.text = etree.CDATA(text)
    return el


def _data_value(parent, dtype: str, radix: str, value: str) -> None:
    dec = etree.SubElement(parent, "Data", Format="Decorated")
    etree.SubElement(dec, "DataValue", DataType=dtype, Radix=radix, Value=value)


def _tag_element(parent, t: TagDef, use: str | None = None) -> None:
    attrs = {"Name": t.name, "TagType": "Base", "DataType": t.datatype}
    if t.datatype in ("BOOL", "DINT"):
        attrs["Radix"] = "Decimal"
    elif t.datatype == "REAL":
        attrs["Radix"] = "Float"
    attrs.update({"Constant": "false", "ExternalAccess": "Read/Write"})
    el = etree.Element("Tag", attrs)
    if use:
        el.set("Use", use)
    parent.append(el)
    if t.description:
        _cdata(el, "Description", t.description)
    if t.datatype == "BOOL":
        _cdata(el, "Data", "0").set("Format", "L5K")
        _data_value(el, "BOOL", "Decimal", "0")
    elif t.datatype == "DINT":
        _cdata(el, "Data", "0").set("Format", "L5K")
        _data_value(el, "DINT", "Decimal", "0")
    elif t.datatype == "REAL":
        _cdata(el, "Data", "0.00000000e+000").set("Format", "L5K")
        _data_value(el, "REAL", "Float", "0.0")
    elif t.datatype in ("TIMER", "COUNTER"):
        pre = int(t.preset or 0)
        # L5K layout [control word, PRE, ACC] -- UNVERIFIED, see HANDOFF.md section 9
        _cdata(el, "Data", f"[0,{pre},0]").set("Format", "L5K")
        dec = etree.SubElement(el, "Data", Format="Decorated")
        st = etree.SubElement(dec, "Structure", DataType=t.datatype)
        etree.SubElement(st, "DataValueMember", Name="PRE", DataType="DINT", Radix="Decimal", Value=str(pre))
        etree.SubElement(st, "DataValueMember", Name="ACC", DataType="DINT", Radix="Decimal", Value="0")
        bits = ("EN", "TT", "DN") if t.datatype == "TIMER" else ("CU", "CD", "DN", "OV", "UN")
        for b in bits:
            etree.SubElement(st, "DataValueMember", Name=b, DataType="BOOL", Value="0")
    else:
        raise ValueError(f"writer cannot create tags of type {t.datatype}")


def _rung_element(parent, number: int, r: Rung, use: str | None) -> None:
    attrs = {"Number": str(number), "Type": "N"}
    el = etree.Element("Rung", ({"Use": use} if use else {}) | attrs)
    parent.append(el)
    if r.comment:
        _cdata(el, "Comment", r.comment)
    _cdata(el, "Text", format_rung(r))


def _skeleton(target_type: str, controller: str, revision: str, date: datetime | None, **extra):
    stamp = (date or datetime.now()).strftime("%a %b %d %H:%M:%S %Y")
    root = etree.Element("RSLogix5000Content", {
        "SchemaRevision": "1.0",
        "SoftwareRevision": revision,
        **extra,
        "TargetType": target_type,
        "ContainsContext": "true",
        "ExportDate": stamp,
        "ExportOptions": EXPORT_OPTIONS,
    })
    ctrl = etree.SubElement(root, "Controller", Use="Context", Name=controller)
    etree.SubElement(ctrl, "DataTypes", Use="Context")
    return root, ctrl


def _tags_block(ctrl, prog, tags: Iterable[TagDef], scope: str) -> None:
    tags = list(tags)
    if scope == "controller":
        holder = etree.Element("Tags", Use="Context")
        ctrl.insert(1, holder)
    else:
        holder = etree.Element("Tags", Use="Context")
        prog.insert(0, holder)
    for t in tags:
        _tag_element(holder, t)


def _serialize(root) -> str:
    # Declaration written by hand: lxml uses single quotes, Studio 5000 exports use double.
    body = etree.tostring(root, encoding="unicode", pretty_print=True)
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + body


def write_rungs(
    rungs: list[Rung],
    tags: Iterable[TagDef] = (),
    *,
    controller: str = "LLM4L5X",
    program: str = "MainProgram",
    routine: str = "MainRoutine",
    revision: str = "32.04",
    scope: str = "controller",
    start_number: int = 0,
    date: datetime | None = None,
) -> str:
    """L5X for pasting rungs into an existing routine (TargetType="Rung")."""
    if not rungs:
        raise ValueError("no rungs to write")
    root, ctrl = _skeleton("Rung", controller, revision, date, TargetCount=str(len(rungs)))
    progs = etree.SubElement(ctrl, "Programs", Use="Context")
    prog = etree.SubElement(progs, "Program", Use="Context", Name=program)
    rts = etree.SubElement(prog, "Routines", Use="Context")
    rt = etree.SubElement(rts, "Routine", Use="Context", Name=routine)
    rll = etree.SubElement(rt, "RLLContent", Use="Context")
    for k, r in enumerate(rungs):
        _rung_element(rll, start_number + k, r, use="Target")
    _tags_block(ctrl, prog, tags, scope)
    return _serialize(root)


def write_routine(
    rungs: list[Rung],
    tags: Iterable[TagDef] = (),
    *,
    controller: str = "LLM4L5X",
    program: str = "MainProgram",
    routine: str = "GeneratedRoutine",
    revision: str = "32.04",
    scope: str = "controller",
    date: datetime | None = None,
) -> str:
    """L5X for importing a whole new ladder routine (TargetType="Routine")."""
    if not rungs:
        raise ValueError("no rungs to write")
    root, ctrl = _skeleton("Routine", controller, revision, date, TargetName=routine, TargetSubType="RLL")
    progs = etree.SubElement(ctrl, "Programs", Use="Context")
    prog = etree.SubElement(progs, "Program", Use="Context", Name=program)
    rts = etree.SubElement(prog, "Routines", Use="Context")
    rt = etree.SubElement(rts, "Routine", Use="Target", Name=routine, Type="RLL")
    rll = etree.SubElement(rt, "RLLContent")
    for k, r in enumerate(rungs):
        _rung_element(rll, k, r, use=None)
    _tags_block(ctrl, prog, tags, scope)
    return _serialize(root)
