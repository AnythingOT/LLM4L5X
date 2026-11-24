"""Reorder the members of the UDTs in an attached export so no padding is wasted.

Text is edited in place: only the <Members> block of a reordered UDT changes (and,
in a full-program file, the L5K copy of affected tag values, see below). Every other
byte of the file, CDATA and line endings included, stays as Studio 5000 wrote it.

Tag values. An L5X stores a tag's values twice: Decorated (by member name) and L5K
(one string in member order). After a reorder the L5K string would put values in
the wrong members, so for every tag whose data contains a reordered type the L5K
copy is removed and the Decorated copy is kept. That Studio 5000 then imports the
values correctly is NOT verified yet: test one import before relying on it.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field

from core.rung import walk
from l5x.reader import Project, read_l5x
from lint.context import Context
from udt import layout
from udt.layout import HOST_PREFIX, M
from l5x.writer import EXPORT_OPTIONS
from udt.writer import host_name

_MEMBER = re.compile(r"<Member\b[^>]*?(?:/>|>.*?</Member>)", re.S)
_ATTR = re.compile(r'(\w+)="([^"]*)"')


@dataclass
class Member:
    text: str  # the original <Member .../> text, verbatim
    attrs: dict

    @property
    def name(self) -> str:
        return self.attrs.get("Name", "")

    @property
    def datatype(self) -> str:
        return self.attrs.get("DataType", "")

    @property
    def dim(self) -> int:
        try:
            return int(self.attrs.get("Dimension") or 0)
        except ValueError:
            return 0

    @property
    def is_host(self) -> bool:
        return (self.attrs.get("Hidden") == "true" and self.datatype.upper() == "SINT"
                and self.name.startswith(HOST_PREFIX))


@dataclass
class UdtPlan:
    name: str
    status: str  # reordered | optimal | skipped
    reason: str = ""
    size_now: int = 0
    size_best: int = 0
    before: list[str] = field(default_factory=list)  # member names, hosts left out
    after: list[str] = field(default_factory=list)
    instances: int | None = None  # tags and array elements of this type (None: export has no tags)
    risks: list[str] = field(default_factory=list)
    in_aoi: list[str] = field(default_factory=list)  # AOIs with a parameter or local tag of this type

    @property
    def saved(self) -> int:
        return max(0, self.size_now - self.size_best)

    @property
    def total_saved(self) -> int | None:
        return None if self.instances is None else self.saved * self.instances

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "reason": self.reason, "size_now": self.size_now,
                "size_best": self.size_best, "saved": self.saved, "instances": self.instances,
                "total_saved": self.total_saved, "risks": self.risks, "in_aoi": self.in_aoi,
                "before": self.before, "after": self.after}


@dataclass
class Analysis:
    text: str
    bom: bool
    project: Project
    target: str | None  # the Use="Target" UDT of a DataType export
    plans: dict[str, UdtPlan]
    members: dict[str, list[Member]]  # original members per UDT
    spans: dict[str, tuple[int, int]]  # (start, end) of each <DataType> element in text
    families: dict[str, str]
    sizes: dict[str, int] = field(default_factory=dict)  # current byte size of every type we can size

    @property
    def full_program(self) -> bool:
        return self.project.target_type == "Controller"


# ---------------------------------------------------------------- reading


def _datatype_spans(text: str) -> dict[str, tuple[int, int]]:
    out = {}
    for m in re.finditer(r"<DataType\b([^>]*?)(/?)>", text):
        attrs = dict(_ATTR.findall(m.group(1)))
        if m.group(2) == "/" or "Name" not in attrs:
            continue
        end = text.find("</DataType>", m.end())
        if end != -1:
            out[attrs["Name"]] = (m.start(), end + len("</DataType>"))
    return out


def _members_region(block: str) -> tuple[int, int] | None:
    a = block.find("<Members>")
    b = block.find("</Members>")
    return (a + len("<Members>"), b) if a != -1 and b != -1 else None


def _parse_members(block: str) -> list[Member]:
    reg = _members_region(block)
    if not reg:
        return []
    inner = block[reg[0]:reg[1]]
    out = []
    for m in _MEMBER.finditer(inner):
        start_tag = m.group(0).split(">", 1)[0]
        out.append(Member(m.group(0), dict(_ATTR.findall(start_tag))))
    return out


def _layout_type(m: Member) -> str:
    return "BIT" if m.datatype.upper() in ("BIT", "BOOL") and m.dim == 0 else m.datatype


def analyse(data: bytes | str) -> Analysis:
    raw = data.decode("utf-8") if isinstance(data, bytes) else data
    bom = raw.startswith("﻿")
    text = raw[1:] if bom else raw
    project = read_l5x(text.encode("utf-8"))
    spans = _datatype_spans(text)
    target = None
    m = re.search(r'<DataType\b[^>]*\bUse="Target"[^>]*\bName="([^"]+)"|<DataType\b[^>]*\bName="([^"]+)"[^>]*\bUse="Target"', text)
    if m and project.target_type == "DataType":
        target = m.group(1) or m.group(2)
    members, families = {}, {}
    for name, (a, b) in spans.items():
        block = text[a:b]
        head = dict(_ATTR.findall(block.split(">", 1)[0]))
        if head.get("Class", "User") != "User":  # System, ProductDefined, IO: Rockwell's, not editable
            continue
        families[name] = head.get("Family", "NoFamily")
        members[name] = _parse_members(block)
    aoi_sizes = {a.name: layout.size_of([M(p.name, p.datatype or "DINT") for p in a.params], {})
                 for a in project.aois.values()}
    user = set(members) | set(aoi_sizes)
    plans: dict[str, UdtPlan] = {}
    types: dict[str, list[M]] = {}
    for name, mem in members.items():
        real = [x for x in mem if not x.is_host]
        plan = UdtPlan(name, "optimal", before=[x.name for x in real])
        plans[name] = plan
        if families[name] != "NoFamily":
            plan.status, plan.reason = "skipped", f"{families[name]} type: Studio 5000 owns its layout"
            continue
        unknown = sorted({x.datatype for x in real if x.datatype.upper() not in layout.SIZE
                          and x.datatype.upper() != "BIT" and x.datatype not in user})
        if unknown:
            plan.status = "skipped"
            plan.reason = (f"uses types not in this file ({', '.join(unknown)}): their size would be a guess. "
                           "Export the whole controller.")
            continue
        types[name] = [M(x.name, _layout_type(x), x.dim) for x in real]
    # a UDT that nests one we cannot size cannot be sized either (fixed-layout families excepted)
    fixed = {n for n in members if families[n] != "NoFamily"
             and all(x.datatype.upper() in layout.SIZE for x in members[n] if not x.is_host)}
    changed = True
    while changed:
        changed = False
        for name in list(types):
            bad = sorted({m.type for m in types[name] if m.type in plans and m.type not in types and m.type not in fixed})
            if bad:
                plans[name].status = "skipped"
                plans[name].reason = f"nests {', '.join(bad)}, which cannot be analysed"
                del types[name]
                changed = True
    # sizes: every analysable UDT as it is, then every one reordered
    try:
        order = layout.dependency_order(types)
    except ValueError as e:
        for n in types:
            plans[n].status, plans[n].reason = "skipped", str(e)
        order, types = [], {}
    now = dict(aoi_sizes)
    for n in fixed:  # STRING-family types: Studio's own layout, never reordered, but nested by size
        now[n] = layout.size_of([M(x.name, _layout_type(x), x.dim) for x in members[n] if not x.is_host], {})
        plans[n].size_now = plans[n].size_best = now[n]
    best = dict(now)
    for n in order:
        now[n] = layout.size_of(types[n], now)
        new = sorted(types[n], key=lambda x: layout.sort_key(x, user))
        best[n] = layout.size_of(new, best)
        p = plans[n]
        p.size_now, p.size_best, p.after = now[n], best[n], [x.name for x in new]
        if p.after != p.before:
            p.status = "reordered"

    an = Analysis(text, bom, project, target, plans, members, spans, families, now)
    if project.target_type == "Controller":
        _count_instances(an)
        _find_risks(an)
    return an


def _elements(dims: str | None) -> int:
    n = 1
    for d in (dims or "").replace(",", " ").split():
        try:
            n *= max(int(d), 1)
        except ValueError:
            pass
    return n


def _count_instances(an: Analysis) -> None:
    """Tags of each type, arrays counted per element, plus copies nested in other UDTs."""
    direct = {n: 0 for n in an.plans}
    for t in an.project.tags.values():
        if t.datatype in direct:
            direct[t.datatype] += _elements(t.dimensions)
    total: dict[str, int] = {}

    def count(n, seen=()):
        if n in total:
            return total[n]
        c = direct.get(n, 0)
        for parent, mem in an.members.items():
            if parent in seen:
                continue
            for x in mem:
                if x.datatype == n and not x.is_host:
                    c += count(parent, seen + (n,)) * max(x.dim, 1)
        total[n] = c
        return c

    for n, p in an.plans.items():
        p.instances = count(n)


_COPY = re.compile(r"\b(COP|CPS)\s*\(\s*([^,()\s]+)\s*,\s*([^,()\s]+)", re.I)


def _find_risks(an: Analysis) -> None:
    """Things that depend on the byte layout: they break silently when members move."""
    p = an.project
    ctx = Context.build(p)
    by_upper = {n.upper(): n for n in an.plans}

    def udt_of(operand: str, owner: str) -> str | None:
        operand = re.sub(r"^\\\w+\.", "", operand.strip())  # \Program.Tag
        t = ctx.resolve_type(operand, owner)
        return by_upper.get((t or "").upper())

    def flag(name, why):
        if name and why not in an.plans[name].risks:
            an.plans[name].risks.append(why)

    for r in ctx.rungs:
        for ins in walk(r.rung.body):
            if ins.name.upper() in ("COP", "CPS"):
                for op in ins.args[:2]:
                    flag(udt_of(op, r.owner), f"{ins.name.upper()} copies bytes of {op.strip()} ({r.location})")
    for m in _COPY.finditer(ctx.usage_text):
        instr, src, dst = m.groups()
        for op in (src, dst):
            flag(udt_of(op, ""), f"{instr.upper()} in an ST/FBD routine copies bytes of {op}")
    for t in p.tags.values():
        if t.tag_type in ("Produced", "Consumed") and t.datatype in an.plans:
            flag(t.datatype, f"{t.tag_type.lower()} tag {t.name}: the other controller has its own copy of the layout")
        if t.message_local:
            owner = "" if t.scope == "controller" else t.scope
            flag(udt_of(t.message_local, owner), f"MSG {t.name} sends or receives {t.message_local} as raw bytes")
    for a in p.aois.values():
        for name in {x.datatype for x in a.params} | {x.datatype for x in a.local_tags}:
            if name in an.plans:
                an.plans[name].in_aoi.append(a.name)
    changed = True
    while changed:  # a risk on a UDT is a risk on every UDT nested inside it
        changed = False
        for parent, mem in an.members.items():
            if not an.plans[parent].risks:
                continue
            for x in mem:
                if x.datatype in an.plans and not x.is_host:
                    why = f"nested inside {parent}, which has a layout risk"
                    if why not in an.plans[x.datatype].risks:
                        an.plans[x.datatype].risks.append(why)
                        changed = True


# ---------------------------------------------------------------- rewriting


def _new_members_block(an: Analysis, name: str, eol_hint: str) -> str:
    """The <Members> inner text of `name` in the new order, original member text reused."""
    block = an.text[slice(*an.spans[name])]
    a, b = _members_region(block)
    inner = block[a:b]
    found = list(_MEMBER.finditer(inner))
    leading = inner[:found[0].start()] if found else eol_hint
    trailing = inner[found[-1].end():] if found else eol_hint
    sep = inner[found[0].end():found[1].start()] if len(found) > 1 else leading
    by_name = {x.name: x for x in an.members[name] if not x.is_host}
    out: list[str] = []
    host, bit = None, 0
    for mname in an.plans[name].after:
        x = by_name[mname]
        if x.datatype.upper() == "BIT":
            if host is None or bit == 8:
                host, bit = host_name(name, len(out)), 0
                out.append(f'<Member Name="{host}" DataType="SINT" Dimension="0" Radix="Decimal" Hidden="true" '
                           'ExternalAccess="Read/Write"/>')
            cut = x.text.index(">")  # end of the start tag (self-closing or not)
            head = re.sub(r'\bTarget="[^"]*"', f'Target="{host}"', x.text[:cut])
            head = re.sub(r'\bBitNumber="[^"]*"', f'BitNumber="{bit}"', head)
            out.append(head + x.text[cut:])
            bit += 1
        else:
            host = None
            out.append(x.text)
    return leading + sep.join(out) + trailing


def _rewritten_block(an: Analysis, name: str, selected: set[str], use: str | None = "keep") -> str:
    a, b = an.spans[name]
    block = an.text[a:b]
    if name in selected and an.plans[name].status == "reordered":
        r = _members_region(block)
        block = block[:r[0]] + _new_members_block(an, name, _eol(an.text)) + block[r[1]:]
    if use != "keep":
        head, rest = block.split(">", 1)
        head = re.sub(r'\s+Use="[^"]*"', "", head)
        if use:
            head = head.replace("<DataType", f'<DataType Use="{use}"', 1)
        block = head + ">" + rest
    return block


def _eol(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _nested_closure(an: Analysis, name: str) -> list[str]:
    """UDTs nested in `name`, recursively, nested ones first."""
    out: list[str] = []

    def visit(n):
        for x in an.members.get(n, []):
            if x.datatype in an.members and x.datatype != name and x.datatype not in out:
                visit(x.datatype)
                out.append(x.datatype)
    visit(name)
    return out


def _aoi_blocks(an: Analysis, names: set[str]) -> list[str]:
    out = []
    for n in sorted(names):
        m = re.search(r'<AddOnInstructionDefinition\b[^>]*\bName="' + re.escape(n) + r'"', an.text)
        if m:
            end = an.text.find("</AddOnInstructionDefinition>", m.end())
            if end != -1:
                blk = an.text[m.start():end + len("</AddOnInstructionDefinition>")]
                head, rest = blk.split(">", 1)
                head = re.sub(r'\s+Use="[^"]*"', "", head).replace("<AddOnInstructionDefinition",
                                                                    '<AddOnInstructionDefinition Use="Context"', 1)
                out.append(head + ">" + rest)
    return out


def single_file(an: Analysis, name: str, selected: set[str]) -> str:
    """One importable Data Type file: the UDT (new order) with the UDTs it nests as context.
    Nested UDTs that are also selected are written in their new order too."""
    eol = _eol(an.text)
    nested = _nested_closure(an, name)
    aois = {x.datatype for n in [name] + nested for x in an.members[n] if x.datatype in an.project.aois}
    sw = an.project.software_revision or "32.04"
    ctrl = an.project.controller or "Controller"
    parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             f'<RSLogix5000Content SchemaRevision="1.0" SoftwareRevision="{sw}" TargetName="{name}" TargetType="DataType" '
             f'ContainsContext="true" ExportOptions="{EXPORT_OPTIONS}">',
             f'<Controller Use="Context" Name="{ctrl}">', '<DataTypes Use="Context">',
             _rewritten_block(an, name, selected, use="Target")]
    parts += [_rewritten_block(an, n, selected, use=None) for n in nested]
    parts.append("</DataTypes>")
    blocks = _aoi_blocks(an, aois)
    if blocks:
        parts += ['<AddOnInstructionDefinitions Use="Context">', *blocks, "</AddOnInstructionDefinitions>"]
    parts += ["</Controller>", "</RSLogix5000Content>", ""]
    out = eol.join(parts)
    return ("﻿" if an.bom else "") + out


_NOT_IN_FILE_NAME = re.compile(r'[<>:"/\\|?*]')


def file_name(name: str, suffix: str = "_opt") -> str:
    """Within Studio 5000's 40-character file name habit: trim the UDT name, keep the suffix.

    Characters Windows refuses in a file name (a module-defined type is `AB:...:I:0`) become `_`.
    """
    return f"{_NOT_IN_FILE_NAME.sub('_', name)[:40 - len(suffix) - 4]}{suffix}.L5X"


def file_names(names) -> dict[str, str]:
    """One file name per UDT, never two the same: names that trim alike get ~2, ~3 in their suffix."""
    out: dict[str, str] = {}
    taken: set[str] = set()
    for n in sorted(names):
        f, k = file_name(n), 1
        while f.lower() in taken:  # Windows file names ignore case
            k += 1
            f = file_name(n, f"~{k}_opt")
        taken.add(f.lower())
        out[n] = f
    return out


def changes_text(an: Analysis, selected: set[str]) -> str:
    lines = [f"UDT reorder: {_n(len(selected), 'UDT')}. Sizes are estimates from the layout rules; check them in Studio 5000.", ""]
    for n in sorted(selected):
        p = an.plans[n]
        inst = "" if p.instances is None else f", {_n(p.instances, 'instance')}, {p.total_saved} bytes in total"
        lines.append(f"{n}: {p.size_now} -> {p.size_best} bytes ({p.saved} saved per instance{inst})")
        lines.append("  before: " + ", ".join(p.before))
        lines.append("  after:  " + ", ".join(p.after))
        for r in p.risks:
            lines.append("  LAYOUT RISK: " + r)
        if p.in_aoi:
            lines.append("  used in AOIs: " + ", ".join(p.in_aoi))
        lines.append("")
    lines.append("Reordering moves byte offsets. Anything that copies these UDTs by offset (COP/CPS, MSG, "
                 "produced/consumed tags, an HMI or SCADA reading the raw block) must be checked. "
                 "A UDT can only be changed offline; plan a download.")
    return "\r\n".join(lines) + "\r\n"


def zip_files(an: Analysis, selected: set[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, f in file_names(selected).items():
            z.writestr(f, single_file(an, n, selected).encode("utf-8"))
        z.writestr("CHANGES.txt", changes_text(an, selected).encode("utf-8"))
    return buf.getvalue()


_VALUE_EL = re.compile(r"<(Tag|LocalTag|Parameter)\b[^>]*?(?:/>|>.*?</\1>)", re.S)
_L5K = re.compile(r"[ \t]*<(Data|DefaultData) Format=\"L5K\">.*?</\1>[ \t]*(\r?\n)?", re.S)


def full_program(an: Analysis, selected: set[str]) -> tuple[str, list[str]]:
    """The whole file with the selected UDTs reordered. Returns (text, notes).
    Left out, with a note: UDTs used inside an AOI (an AOI instance keeps its local tags
    only in the L5K copy, which has to go) and UDTs whose tags were exported without
    Decorated data (their values could not be kept)."""
    if not an.full_program:
        raise ValueError("a full-program file needs a controller export")
    notes = []
    sel = {n for n in selected if an.plans[n].status == "reordered"}
    for n in sorted(sel):
        if an.plans[n].in_aoi:
            sel.discard(n)
            notes.append(f"{n} left out: used inside AOI {', '.join(an.plans[n].in_aoi)}. Use its single file instead.")
    while True:
        text, missing = _rewrite(an, sel)
        if not missing:
            break
        drop = sel & _roots_of(an, set(missing))
        notes.append("Tags with only L5K data (exported without Decorated data): "
                     + "; ".join(f"{t}: {', '.join(v[:5])}" for t, v in sorted(missing.items()))
                     + f". Left out: {', '.join(sorted(drop))}. Export again with Decorated data, or use the single files.")
        sel -= drop
    if sel:
        notes.append(f"{_n(len(sel), 'UDT')} reordered. For tags of the affected types the L5K copy of the values was "
                     "removed and the Decorated copy (by member name) kept. Test the import on a copy of the project first.")
    else:
        notes.append("No UDT was changed.")
    return ("\ufeff" if an.bom else "") + text, notes


def _affected(an: Analysis, sel: set[str]) -> set[str]:
    """The reordered UDTs and every UDT that nests one: their layouts all move."""
    out = set(sel)
    grew = True
    while grew:
        grew = False
        for parent, mem in an.members.items():
            if parent not in out and any(x.datatype in out for x in mem):
                out.add(parent)
                grew = True
    return out


def _rewrite(an: Analysis, sel: set[str]) -> tuple[str, dict[str, list[str]]]:
    text = an.text
    affected = _affected(an, sel)
    missing: dict[str, list[str]] = {}
    if affected:
        pat = re.compile(r'DataType="(' + "|".join(re.escape(a) for a in sorted(affected)) + r')"')
        pieces, last = [], 0
        for m in _VALUE_EL.finditer(text):
            chunk = m.group(0)
            hit = pat.search(chunk)
            if not hit or 'Format="L5K"' not in chunk:
                continue
            if 'Format="Decorated"' not in chunk:
                tag = dict(_ATTR.findall(chunk.split(">", 1)[0])).get("Name", "?")
                missing.setdefault(hit.group(1), []).append(tag)
                continue
            pieces += [text[last:m.start()], _L5K.sub("", chunk)]
            last = m.end()
        pieces.append(text[last:])
        text = "".join(pieces)
    if missing:
        return an.text, missing
    for n in sorted(sel, key=lambda k: an.spans[k][0], reverse=True):  # from the end: offsets stay valid
        a, b = _span_in(text, n)
        block = text[a:b]
        r = _members_region(block)
        text = text[:a] + block[:r[0]] + _new_members_block(an, n, _eol(text)) + block[r[1]:] + text[b:]
    return text, {}


def _span_in(text: str, name: str) -> tuple[int, int]:
    return _datatype_spans(text)[name]


def _roots_of(an: Analysis, types: set[str]) -> set[str]:
    """Selected UDTs that are, or are nested in, `types`."""
    out = set()
    for t in types:
        out.add(t)
        out.update(_nested_closure(an, t))
    return out


def _n(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"
