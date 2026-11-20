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
    tag_type: str = "Base"  # Base / Alias / Produced / Consumed
    external_access: str | None = None
    comments: dict[str, str] = field(default_factory=dict)  # operand ("[0].3", ".Fault") -> text
    tag_class: str = "Standard"  # Standard / Safety
    remote_tag: str | None = None  # consumed tags: the producer's tag
    decorated_presets: dict[str, int] | None = None  # TIMER: {"" or "[n]": PRE} from Decorated data
    message_type: str | None = None
    message_local: str | None = None  # MSG configuration: the local element it reads or writes

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
    program: str  # program name, or "AOI:<name>" for Add-On Instruction logic
    rungs: list[RungInfo] = field(default_factory=list)
    protected: bool = False  # source/license protected: logic not readable
    usage_text: str = ""  # ST/FBD/SFC: identifier-bearing text (counts as tag usage, not analysed)

    @property
    def is_ladder(self) -> bool:
        return self.type.upper() == "RLL" and not self.usage_text


@dataclass
class ProgramInfo:
    name: str
    main_routine: str | None
    fault_routine: str | None
    children: list[str] = field(default_factory=list)
    program_class: str = "Standard"  # GuardLogix: Safety / Standard (Class attribute)


@dataclass
class TaskInfo:
    name: str
    type: str  # CONTINUOUS / PERIODIC / EVENT
    period: float | None  # ms
    watchdog: float | None  # ms
    programs: list[str] = field(default_factory=list)


@dataclass
class IOTag:
    suffix: str  # "I", "O", "I1" ...
    kind: str  # input / output
    comments: dict[str, str]  # OPERAND (upper case, e.g. ".DATA.3") -> text
    data_members: list[str]  # field-data members: "Data", "Ch0Data", "Ch00.Data"


@dataclass
class ModuleInfo:
    name: str
    catalog: str  # without series: 1756-IB16
    catalog_full: str
    parent: str | None
    slot: str | None
    ekey: str | None  # CompatibleModule / ExactMatch / Disabled; None if not exported
    upstream_type: str | None  # port type towards the parent: ICP (backplane), Ethernet ...
    io_tags: list[IOTag] = field(default_factory=list)


@dataclass
class MemberInfo:
    name: str
    datatype: str
    dimension: int
    hidden: bool
    description: str | None


@dataclass
class DataTypeInfo:
    name: str
    family: str | None
    description: str | None
    members: list[MemberInfo]
    use: str | None = None  # "Target" in a single-UDT export
    data_class: str | None = None  # User (or missing) for a UDT; ProductDefined, IO, System are Rockwell's

    @property
    def is_user(self) -> bool:
        return self.data_class in (None, "User")


@dataclass
class AOIParam:
    name: str
    datatype: str
    usage: str  # Input Output InOut
    required: bool
    visible: bool
    description: str | None = None


@dataclass
class AOIInfo:
    name: str
    description: str | None
    params: list[AOIParam]
    local_tags: list[TagInfo] = field(default_factory=list)
    routines: list[RoutineInfo] = field(default_factory=list)

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
    string_types: set[str] = field(default_factory=lambda: {"STRING"})  # STRING + custom string types
    protected_aois: set[str] = field(default_factory=set)  # source-protected: parameters unknown
    # --- project structure (used by the lint rules)
    programs: list[ProgramInfo] = field(default_factory=list)
    tasks: list[TaskInfo] = field(default_factory=list)
    modules: list[ModuleInfo] = field(default_factory=list)
    datatypes: dict[str, DataTypeInfo] = field(default_factory=dict)  # user types incl. string types
    major_fault_program: str | None = None  # None: attribute not in the export
    power_loss_program: str | None = None
    safety_tag_map: list[tuple[str, str]] = field(default_factory=list)
    has_forces: bool = False
    processor: str | None = None

    @property
    def is_full_export(self) -> bool:
        return self.target_type == "Controller"

    def tag_types(self, program: str | None = None) -> dict[str, str]:
        """Visible tags from a program's point of view: controller tags plus that program's."""
        out = {t.name: t.datatype for k, t in self.tags.items() if t.scope == "controller"}
        if program:
            out.update({t.name: t.datatype for t in self.tags.values() if t.scope == program})
        return out

    def tag_descriptions(self, program: str | None = None) -> dict[str, str]:
        out = {t.name: t.description for t in self.tags.values() if t.scope == "controller" and t.description}
        if program:
            out.update({t.name: t.description for t in self.tags.values() if t.scope == program and t.description})
        return out

    def presets(self) -> dict[str, int]:
        return {t.name: t.preset for t in self.tags.values() if t.preset is not None}

    def catalog(self, base: Catalog | None = None) -> Catalog:
        """Builtin catalog extended with this project's AOIs."""
        cat = (base or default_catalog()).copy()
        for name in self.protected_aois:
            if name not in self.aois:  # operands unknown: accept any number after the instance
                cat.add(Instruction(name, "output", (Operand("instance", name, "struct"),),
                                    "Source-protected Add-On Instruction", variadic=True, source="aoi"))
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


def _decorated_presets(t) -> dict[str, int] | None:
    """PRE of a TIMER tag (or of each element of a TIMER array) from its Decorated data."""
    if not (t.get("DataType") or "").upper().startswith("TIMER"):
        return None
    data = next((d for d in t.findall("Data") if d.get("Format") == "Decorated"), None)
    if data is None:
        return None

    def pre(struct):
        for m in struct.findall("DataValueMember"):
            if (m.get("Name") or "").upper() == "PRE":
                try:
                    return int(float(m.get("Value", "0")))
                except ValueError:
                    return None
        return None

    out: dict[str, int] = {}
    if data.find("Structure") is not None:
        out[""] = pre(data.find("Structure"))
    for el in data.findall("Array/Element"):
        if el.find("Structure") is not None:
            out[el.get("Index", "")] = pre(el.find("Structure"))
    return {k: v for k, v in out.items() if v is not None} or None


def _tags(holder, scope: str, path: str = "Tag") -> list[TagInfo]:
    out = []
    if holder is None:
        return out
    for t in holder.findall(path):
        l5k = None
        for d in t.findall("Data"):
            if d.get("Format") == "L5K":
                l5k = _text(d)
        consume = t.find("ConsumeInfo")
        mp = t.find(".//MessageParameters")
        out.append(TagInfo(
            name=t.get("Name"),
            datatype=t.get("DataType") or ("ALIAS" if t.get("TagType") == "Alias" else ""),
            scope=scope,
            description=_desc(t),
            dimensions=t.get("Dimensions"),
            alias_for=t.get("AliasFor"),
            l5k=l5k,
            tag_type=t.get("TagType") or "Base",
            external_access=t.get("ExternalAccess"),
            comments={c.get("Operand"): (_text(c) or "") for c in t.findall("Comments/Comment") if c.get("Operand")},
            tag_class=t.get("Class") or "Standard",
            remote_tag=consume.get("RemoteTag") if consume is not None else None,
            decorated_presets=_decorated_presets(t),
            message_type=mp.get("MessageType") if mp is not None else None,
            message_local=mp.get("LocalElement") if mp is not None else None,
        ))
    return out


_USAGE_ATTRS = ("Operand", "Routine", "Tag", "Name", "ArrayIndex", "Expression")


def _usage_text(rt) -> str:
    """Identifier-bearing text of an ST/FBD/SFC routine: its references count as tag usage."""
    parts = []
    for el in rt.iter():
        if el.tag == "Line" and el.text:
            parts.append(el.text)
        for k in _USAGE_ATTRS:
            if el.get(k):
                parts.append(el.get(k))
        if el.tag in ("Expression", "Condition", "Action") and el.text:
            parts.append(el.text)
    return "\n".join(parts)


def _routines(holder, owner: str) -> list[RoutineInfo]:
    out = []
    for rt in holder.findall("Routines/Routine"):
        rtype = rt.get("Type") or "RLL"
        non_rll = rtype.upper() != "RLL" or any(rt.find(c) is not None for c in ("FBDContent", "SFCContent", "STContent"))
        info = RoutineInfo(rt.get("Name"), rtype, owner, protected=rt.find("EncryptionInfo") is not None,
                           usage_text=_usage_text(rt) if non_rll else "")
        for r in rt.findall("RLLContent/Rung"):
            text = _text(r.find("Text")) or ""
            comment = _text(r.find("Comment"))
            try:
                parsed, err = parse_rung(text, comment), None
            except RungSyntaxError as e:
                parsed, err = None, str(e)
            info.rungs.append(RungInfo(int(r.get("Number", len(info.rungs))), text, comment, parsed, err))
        out.append(info)
    for enc in holder.findall("Routines/EncodedData"):  # source-protected routine
        out.append(RoutineInfo(enc.get("Name") or "?", enc.get("Type") or "?", owner, protected=True))
    return out


def _io_data_members(io) -> list[str]:
    """Field-data members of a module I/O tag; status, fault and config members are left out."""
    data = next((d for d in io.findall("Data") if d.get("Format") == "Decorated"), None)
    st = data.find("Structure") if data is not None else None
    if st is None:
        return []
    out = [m.get("Name") for m in st.findall("DataValueMember")
           if (m.get("Name") or "").lower() == "data" or re.fullmatch(r"(?i)ch\d+data", m.get("Name") or "")]
    for sm in st.findall("StructureMember"):
        n = sm.get("Name") or ""
        if re.fullmatch(r"(?i)ch\d+", n) and any((d.get("Name") or "").lower() == "data" for d in sm.findall("DataValueMember")):
            out.append(n + ".Data")
    return out


def _modules(ctrl) -> list[ModuleInfo]:
    out = []
    for m in ctrl.findall("Modules/Module"):
        cat = m.get("CatalogNumber") or ""
        slot = next((p.get("Address") for p in m.findall("Ports/Port") if (p.get("Type") or "") in ("ICP", "")), None)
        upstream = next((p.get("Type") for p in m.findall("Ports/Port") if (p.get("Upstream") or "").lower() == "true"), None)
        ekey = m.find("EKey")
        ios = []
        for io in list(m.iter("InputTag")) + list(m.iter("OutputTag")):
            ios.append(IOTag(
                io.get("Suffix") or ("I" if io.tag == "InputTag" else "O"),
                "input" if io.tag == "InputTag" else "output",
                {(c.get("Operand") or "").upper(): (_text(c) or "") for c in io.findall("Comments/Comment")},
                _io_data_members(io),
            ))
        out.append(ModuleInfo(m.get("Name") or "", cat.split("/")[0].strip(), cat, m.get("ParentModule"),
                              slot, ekey.get("State") if ekey is not None else None, upstream, ios))
    return out


def _float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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
    datatypes: dict[str, DataTypeInfo] = {}
    aois: dict[str, AOIInfo] = {}
    string_types: set[str] = {"STRING"}
    protected: set[str] = set()
    programs: list[ProgramInfo] = []
    tasks: list[TaskInfo] = []
    modules: list[ModuleInfo] = []
    safety_map: list[tuple[str, str]] = []
    if ctrl is not None:
        for t in _tags(ctrl.find("Tags"), "controller"):
            tags[t.name] = t
        for dt in ctrl.findall("DataTypes/DataType"):
            if dt.get("Family") == "StringFamily":
                string_types.add(dt.get("Name"))
            udts[dt.get("Name")] = [
                (m.get("Name"), m.get("DataType")) for m in dt.findall("Members/Member")
                if m.get("Hidden") != "true"
            ]
            if dt.get("Class", "User") != "System":
                members = []
                for m in dt.findall("Members/Member"):
                    try:
                        dim = int(m.get("Dimension") or 0)
                    except ValueError:
                        dim = 0
                    members.append(MemberInfo(m.get("Name") or "", m.get("DataType") or "", dim,
                                              m.get("Hidden") == "true", _desc(m)))
                datatypes[dt.get("Name")] = DataTypeInfo(dt.get("Name"), dt.get("Family"), _desc(dt), members, dt.get("Use"),
                                                       dt.get("Class"))
        for a in ctrl.findall("AddOnInstructionDefinitions/AddOnInstructionDefinition"):
            params = [
                AOIParam(
                    p.get("Name"), p.get("DataType"), p.get("Usage"),
                    p.get("Required") == "true", p.get("Visible") == "true", _desc(p),
                )
                for p in a.findall("Parameters/Parameter")
            ]
            name = a.get("Name")
            aois[name] = AOIInfo(name, _desc(a), params, _tags(a.find("LocalTags"), f"AOI:{name}", "LocalTag"),
                                 _routines(a, f"AOI:{name}"))
        for enc in ctrl.findall("AddOnInstructionDefinitions/EncodedData"):
            if enc.get("Type") == "AddOnInstructionDefinition" and enc.get("Name"):
                protected.add(enc.get("Name"))
        for prog in ctrl.findall("Programs/Program"):
            pname = prog.get("Name")
            programs.append(ProgramInfo(pname, prog.get("MainRoutineName"), prog.get("FaultRoutineName"),
                                        [c.get("Name") for c in prog.findall("ChildPrograms/ChildProgram")],
                                        prog.get("Class") or "Standard"))
            for t in _tags(prog.find("Tags"), pname):
                tags[f"{pname}/{t.name}"] = t
            routines += _routines(prog, pname)
        for t in ctrl.findall("Tasks/Task"):
            tasks.append(TaskInfo(t.get("Name") or "", (t.get("Type") or "").upper(), _float(t.get("Period")),
                                  _float(t.get("Watchdog")),
                                  [sp.get("Name") for sp in t.findall("ScheduledPrograms/ScheduledProgram")]))
        modules = _modules(ctrl)
        sm = ctrl.find(".//SafetyTagMap")
        if sm is not None and (sm.text or "").strip():
            for entry in sm.text.split(","):
                a, _, b = entry.partition("=")
                if a.strip() and b.strip():
                    safety_map.append((a.strip(), b.strip()))
    forced = ctrl is not None and any(ft.find("Tag") is not None for ft in ctrl.iter("ForcedTags"))
    return Project(
        controller=ctrl.get("Name") if ctrl is not None else None,
        software_revision=root.get("SoftwareRevision"),
        target_type=root.get("TargetType"),
        tags=tags,
        routines=routines,
        udts=udts,
        aois=aois,
        string_types=string_types,
        protected_aois=protected,
        programs=programs,
        tasks=tasks,
        modules=modules,
        datatypes=datatypes,
        major_fault_program=ctrl.get("MajorFaultProgram") if ctrl is not None else None,
        power_loss_program=ctrl.get("PowerLossProgram") if ctrl is not None else None,
        safety_tag_map=safety_map,
        has_forces=forced,
        processor=ctrl.get("ProcessorType") if ctrl is not None else None,
    )
