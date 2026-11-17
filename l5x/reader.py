"""Read an L5X export into plain Python structures.

Secure parsing: no entity resolution, no network. Only ladder (RLL)
routines yield rungs; other routine types are listed but not parsed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from core.catalog import Catalog, Instruction, Operand, default_catalog
from core.rung import Rung, RungSyntaxError, parse_rung


@dataclass
class TagInfo:
    name: str
    datatype: str
    scope: str  # "controller" or program name
    description: str | None = None
    dimensions: str | None = None
    alias_for: str | None = None
    l5k: str | None = None

    @property
    def preset(self) -> int | None:
        """PRE from L5K data of a TIMER/COUNTER: [ctrl,PRE,ACC] (layout unverified)."""
        if self.datatype in ("TIMER", "COUNTER") and self.l5k:
            m = re.match(r"\s*\[\s*-?\d+\s*,\s*(-?\d+)\s*,", self.l5k)
            if m:
                return int(m.group(1))
        return None


@dataclass
class RungInfo:
    number: int
    text: str
    comment: str | None
    rung: Rung | None  # None when the text failed to parse
    parse_error: str | None = None


@dataclass
class RoutineInfo:
    name: str
    type: str
    program: str
    rungs: list[RungInfo] = field(default_factory=list)


@dataclass
class AOIParam:
    name: str
    datatype: str
    usage: str  # Input Output InOut
    required: bool
    visible: bool


@dataclass
class AOIInfo:
    name: str
    description: str | None
    params: list[AOIParam]

    def call_operands(self) -> list[AOIParam]:
        """Parameters that appear in the rung call after the instance tag.

        Required parameters, in definition order, excluding EnableIn/EnableOut.
        Confirmed on public exports (e.g. IO_Module_Status(inst,Module_In,Status)).
        """
        return [p for p in self.params if p.required and p.name not in ("EnableIn", "EnableOut")]


@dataclass
class Project:
    controller: str | None
    software_revision: str | None
    target_type: str | None
    tags: dict[str, TagInfo]  # key: "Tag" for controller scope, "Program/Tag" for program scope
    routines: list[RoutineInfo]
    udts: dict[str, list[tuple[str, str]]]  # name -> [(member, datatype)]
    aois: dict[str, AOIInfo]

    def tag_types(self, program: str | None = None) -> dict[str, str]:
        """Visible tags from a program's point of view: controller tags plus that program's."""
        out = {t.name: t.datatype for k, t in self.tags.items() if t.scope == "controller"}
        if program:
            out.update({t.name: t.datatype for t in self.tags.values() if t.scope == program})
        return out

    def presets(self) -> dict[str, int]:
        return {t.name: t.preset for t in self.tags.values() if t.preset is not None}

    def catalog(self, base: Catalog | None = None) -> Catalog:
        """Builtin catalog extended with this project's AOIs."""
        cat = (base or default_catalog()).copy()
        for a in self.aois.values():
            ops = [Operand("instance", a.name, "struct")]
            for p in a.call_operands():
                role = {"Input": "read", "Output": "write"}.get(p.usage, "struct")
                # MODULE parameters take a module name, which is not a tag
                ops.append(Operand(p.name, "NAME" if (p.datatype or "").upper() == "MODULE" else "ANY", role))
            cat.add(Instruction(a.name, "output", tuple(ops), a.description or "", source="aoi"))
        return cat


def _text(el) -> str | None:
    if el is None:
        return None
    t = "".join(el.itertext()).strip()
    return t or None


def _desc(el) -> str | None:
    return _text(el.find("Description"))


def _tags(holder, scope: str) -> list[TagInfo]:
    out = []
    if holder is None:
        return out
    for t in holder.findall("Tag"):
        l5k = None
        for d in t.findall("Data"):
            if d.get("Format") == "L5K":
                l5k = _text(d)
        out.append(TagInfo(
            name=t.get("Name"),
            datatype=t.get("DataType") or ("ALIAS" if t.get("TagType") == "Alias" else ""),
            scope=scope,
            description=_desc(t),
            dimensions=t.get("Dimensions"),
            alias_for=t.get("AliasFor"),
            l5k=l5k,
        ))
    return out


def read_l5x(source: str | bytes | Path) -> Project:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True, remove_blank_text=True)
    if isinstance(source, Path) or (isinstance(source, str) and not source.lstrip().startswith("<")):
        root = etree.parse(str(source), parser).getroot()
    else:
        data = source.encode("utf-8") if isinstance(source, str) else source
        root = etree.fromstring(data, parser)
    if root.tag != "RSLogix5000Content":
        raise ValueError(f"not an L5X file (root element {root.tag})")
    ctrl = root.find("Controller")
    tags: dict[str, TagInfo] = {}
    routines: list[RoutineInfo] = []
    udts: dict[str, list[tuple[str, str]]] = {}
    aois: dict[str, AOIInfo] = {}
    if ctrl is not None:
        for t in _tags(ctrl.find("Tags"), "controller"):
            tags[t.name] = t
        for dt in ctrl.findall("DataTypes/DataType"):
            udts[dt.get("Name")] = [
                (m.get("Name"), m.get("DataType")) for m in dt.findall("Members/Member")
                if m.get("Hidden") != "true"
            ]
        for a in ctrl.findall("AddOnInstructionDefinitions/AddOnInstructionDefinition"):
            params = [
                AOIParam(
                    p.get("Name"), p.get("DataType"), p.get("Usage"),
                    p.get("Required") == "true", p.get("Visible") == "true",
                )
                for p in a.findall("Parameters/Parameter")
            ]
            aois[a.get("Name")] = AOIInfo(a.get("Name"), _desc(a), params)
        for prog in ctrl.findall("Programs/Program"):
            pname = prog.get("Name")
            for t in _tags(prog.find("Tags"), pname):
                tags[f"{pname}/{t.name}"] = t
            for rt in prog.findall("Routines/Routine"):
                info = RoutineInfo(rt.get("Name"), rt.get("Type") or "RLL", pname)
                for r in rt.findall("RLLContent/Rung"):
                    text = _text(r.find("Text")) or ""
                    comment = _text(r.find("Comment"))
                    try:
                        parsed, err = parse_rung(text, comment), None
                    except RungSyntaxError as e:
                        parsed, err = None, str(e)
                    info.rungs.append(RungInfo(int(r.get("Number", len(info.rungs))), text, comment, parsed, err))
                routines.append(info)
    return Project(
        controller=ctrl.get("Name") if ctrl is not None else None,
        software_revision=root.get("SoftwareRevision"),
        target_type=root.get("TargetType"),
        tags=tags,
        routines=routines,
        udts=udts,
        aois=aois,
    )
