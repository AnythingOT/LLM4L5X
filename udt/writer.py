"""Write new UDTs as Studio 5000 DataType exports (Import Data Type), members in the
order that wastes no padding. BOOL members become BIT members packed into hidden
SINT hosts, named the way Studio 5000 names them: ZZZZZZZZZZ + the first 10
characters of the UDT name + the host's position in the member list."""

from __future__ import annotations

from datetime import datetime

from lxml import etree

from udt import layout
from udt.layout import M
from udt.model import UdtDef, UdtMember, dependency_order

EXPORT_OPTIONS = "References NoRawData L5KData DecoratedData Context Dependencies ForceProtectedEncoding AllProjDocTrans"
_STRUCT = {"STRING", "TIMER", "COUNTER", "CONTROL", "MESSAGE"}


def host_name(udt: str, index: int) -> str:
    return f"{layout.HOST_PREFIX}{udt[:10]}{index}"


def radix(datatype: str, is_struct: bool) -> str:
    t = datatype.upper()
    if is_struct or t in _STRUCT:
        return "NullType"
    return "Float" if t in ("REAL", "LREAL") else "Decimal"


def ordered(u: UdtDef, user_types: set[str]) -> list[UdtMember]:
    """Members in the no-padding order (see udt.layout.sort_key)."""
    return sorted(u.members, key=lambda m: layout.sort_key(M(m.name, m.datatype, m.dim), user_types))


def sizes(udts: list[UdtDef], known_sizes: dict[str, int] | None = None, optimal: bool = True) -> dict[str, int]:
    """Byte size of each UDT (as written: optimal order unless optimal=False)."""
    out = dict(known_sizes or {})
    user = {u.name for u in udts} | set(out)
    for u in dependency_order(udts):
        mem = ordered(u, user) if optimal else u.members
        out[u.name] = layout.size_of([M(m.name, "BIT" if (m.datatype.upper() == "BOOL" and not m.dim) else m.datatype, m.dim)
                                      for m in mem], out)
    return out


def _desc(parent, text: str) -> None:
    if text:
        d = etree.SubElement(parent, "Description")
        d.text = etree.CDATA(text)


def datatype_element(u: UdtDef, user_types: set[str], use: str | None = None) -> etree._Element:
    attrs = ({"Use": use} if use else {}) | {"Name": u.name, "Family": "NoFamily", "Class": "User"}
    dt = etree.Element("DataType", attrs)
    _desc(dt, u.description)
    members = etree.SubElement(dt, "Members")
    host, bit = None, 0
    for m in ordered(u, user_types):
        t = m.datatype.upper()
        if t == "BOOL" and not m.dim:
            if host is None or bit == 8:
                host, bit = host_name(u.name, len(members)), 0
                etree.SubElement(members, "Member", Name=host, DataType="SINT", Dimension="0", Radix="Decimal",
                                 Hidden="true", ExternalAccess="Read/Write")
            el = etree.SubElement(members, "Member", Name=m.name, DataType="BIT", Dimension="0", Radix="Decimal",
                                  Hidden="false", Target=host, BitNumber=str(bit), ExternalAccess="Read/Write")
            bit += 1
        else:
            host = None
            native = t in layout.SIZE
            el = etree.SubElement(members, "Member", Name=m.name, DataType=t if native else m.datatype,
                                  Dimension=str(m.dim), Radix=radix(m.datatype, not native), Hidden="false",
                                  ExternalAccess="Read/Write")
        _desc(el, m.description)
    nested = sorted({m.datatype for m in u.members if m.datatype in user_types})
    if nested:
        deps = etree.SubElement(dt, "Dependencies")
        for n in nested:
            etree.SubElement(deps, "Dependency", Type="DataType", Name=n)
    return dt


def write_udt(target: UdtDef, batch: list[UdtDef], controller: str = "LLM4L5X", revision: str = "32.04",
              project_types: set[str] = frozenset(), date: datetime | None = None) -> str:
    """One importable file: the target UDT plus, as context, every UDT of the batch it nests."""
    by = {u.name: u for u in batch}
    user = set(by) | set(project_types)
    need, stack = [], [target.name]
    while stack:  # nested UDTs from the same batch, recursively
        for m in by[stack.pop()].members:
            if m.datatype in by and m.datatype not in need and m.datatype != target.name:
                need.append(m.datatype)
                stack.append(m.datatype)
    date = date or datetime.now()
    root = etree.Element("RSLogix5000Content", {
        "SchemaRevision": "1.0", "SoftwareRevision": revision, "TargetName": target.name, "TargetType": "DataType",
        "ContainsContext": "true", "ExportDate": date.strftime("%a %b %d %H:%M:%S %Y"), "ExportOptions": EXPORT_OPTIONS})
    ctrl = etree.SubElement(root, "Controller", Use="Context", Name=controller)
    dts = etree.SubElement(ctrl, "DataTypes", Use="Context")
    dts.append(datatype_element(target, user, use="Target"))
    for u in dependency_order([by[n] for n in need]):
        dts.append(datatype_element(u, user))
    etree.indent(root, space="")
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            + etree.tostring(root, encoding="unicode") + "\n")
