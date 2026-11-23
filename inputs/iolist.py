"""An I/O list: every field signal, its tag, its address and what it is.

Read from Excel with loosely matched headers (Tag | Description | Address | Type | Device ...). It
checks what an engineer would check before commissioning: one tag per signal, one signal per
address, inputs on input addresses, valid Logix names, analog ranges present. It groups signals into
devices and proposes plant models for the ones it recognises (pump with run feedback, valve with
limit switches), so a test plant can start from the I/O list instead of being typed again.

Addresses are only used as written: a missing address is reported, never invented, because the
right form depends on the module (Local:3:I.Data.5 for a digital card, Local:4:I.Ch2Data for many
analog cards).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

_COLS = {
    "tag": {"tag", "tag name", "tagname", "signal", "signal name", "mapped tag", "name", "logix tag"},
    "desc": {"description", "desc", "signal description", "service", "function"},
    "address": {"address", "io address", "i/o address", "plc address", "logix address", "channel address"},
    "type": {"type", "signal type", "io type", "i/o type", "di/do", "kind"},
    "device": {"device", "equipment", "equipment tag", "loop", "instrument", "loop tag"},
    "lo": {"range low", "range lo", "min", "eu min", "low", "lrv"},
    "hi": {"range high", "range hi", "max", "eu max", "high", "urv"},
    "units": {"units", "unit", "eu", "engineering units"},
    "contact": {"contact", "no/nc", "nc/no", "normally"},
}
_TYPES = {
    "DI": {"di", "digital input", "discrete input", "input", "i", "bool input", "binary input"},
    "DO": {"do", "digital output", "discrete output", "output", "o", "bool output", "binary output"},
    "AI": {"ai", "analog input", "analogue input"},
    "AO": {"ao", "analog output", "analogue output"},
}
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,39}$")


class IOListError(ValueError):
    pass


@dataclass
class Point:
    line: int
    tag: str
    desc: str = ""
    address: str = ""
    type: str = ""  # DI DO AI AO
    device: str = ""
    lo: float | None = None
    hi: float | None = None
    units: str = ""
    nc: bool = False  # normally closed contact (fail-safe: 1 = healthy)


@dataclass
class Device:
    name: str
    points: list[Point] = field(default_factory=list)
    kind: str = ""  # pump | valve | "" (not recognised)
    plant: dict = field(default_factory=dict)  # proposed plant model entry


@dataclass
class IOList:
    points: list[Point] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    devices: list[Device] = field(default_factory=list)

    def by_tag(self) -> dict[str, Point]:
        return {p.tag: p for p in self.points}


def _norm(v) -> str:
    return re.sub(r"\s+", " ", str(v)).strip() if v is not None else ""


def _num(v) -> float | None:
    try:
        return float(v) if _norm(v) != "" else None
    except ValueError:
        return None


def _signal_type(text: str, address: str) -> str:
    t = text.lower().strip()
    for k, names in _TYPES.items():
        if t in names:
            return k
    a = address.upper()
    if ":I." in a or ":I:" in a:
        return "DI"  # analog inputs need a Type: an address alone cannot tell
    if ":O." in a or ":O:" in a:
        return "DO"
    return ""


def _check_name(tag: str) -> str | None:
    if not _NAME.match(tag):
        return "is not a valid Logix name (letter or _ first, then letters, digits, _; at most 40)"
    if "__" in tag or tag.endswith("_"):
        return "has a double or trailing underscore, which Logix does not allow"
    return None


def _device_of(p: Point) -> str:
    return p.device or (p.tag.split("_", 1)[0] if "_" in p.tag else "")


_RUN = re.compile(r"(run|running|rng|fb|feedback|on)$", re.I)
_CMD = re.compile(r"(cmd|command|start|run_cmd|out)$", re.I)
_OL = re.compile(r"(ol|overload|trip|flt|fault)$", re.I)
_OPEN_LS = re.compile(r"(zso|zo|opened|open_ls|ls_open|is_open|open_fb)$", re.I)
_CLOSED_LS = re.compile(r"(zsc|zc|closed|closed_ls|ls_closed|is_closed|closed_fb)$", re.I)
_OPEN_CMD = re.compile(r"(open|open_cmd|opn|sov_open)$", re.I)
_CLOSE_CMD = re.compile(r"(close|close_cmd|cls)$", re.I)


def _suffix(tag: str, dev: str) -> str:
    return tag[len(dev) + 1:] if tag.startswith(dev + "_") else tag


def _recognise(d: Device) -> None:
    """Pump: one DO command (+ run feedback, overload). Valve: open (+ close) DO and limit switches.
    Conservative: anything else stays unrecognised and is listed, not guessed."""
    do = [p for p in d.points if p.type == "DO"]
    di = [p for p in d.points if p.type == "DI"]
    s = {p.tag: _suffix(p.tag, d.name) for p in d.points}
    opn = [p for p in do if _OPEN_CMD.search(s[p.tag])]
    if opn and len(do) <= 2:
        cls = [p for p in do if _CLOSE_CMD.search(s[p.tag])]
        if len(do) == len(opn) + len(cls) and len(opn) == 1 and len(cls) <= 1:
            d.kind = "valve"
            d.plant = {"name": d.name, "type": "valve", "open_cmd": opn[0].tag}
            if cls:
                d.plant["close_cmd"] = cls[0].tag
            for key, rx in (("open_ls", _OPEN_LS), ("closed_ls", _CLOSED_LS)):
                hit = [p for p in di if rx.search(s[p.tag])]
                if len(hit) == 1:
                    d.plant[key] = hit[0].tag
            return
    if len(do) == 1 and (_CMD.search(s[do[0].tag]) or not di):
        d.kind = "pump"
        d.plant = {"name": d.name, "type": "pump", "cmd": do[0].tag}
        for key, rx in (("running", _RUN), ("overload", _OL)):
            hit = [p for p in di if rx.search(s[p.tag])]
            if len(hit) == 1:
                d.plant[key] = hit[0].tag


def read_iolist(data: bytes) -> IOList:
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:  # not an xlsx at all
        raise IOListError(f"not an Excel workbook: {e}") from None
    out = IOList()
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        header, start = None, 0
        for n, row in enumerate(rows[:15]):
            cells = [_norm(c).lower() for c in row]
            h = {k: cells.index(c) for k, names in _COLS.items() for c in cells if c in names}
            if "tag" in h and ("address" in h or "type" in h):
                header, start = h, n + 1
                break
        if not header:
            continue
        for line, row in enumerate(rows[start:], start + 1):
            def cell(k, row=row, header=header):
                i = header.get(k)
                return _norm(row[i]) if i is not None and i < len(row) else ""
            tag = cell("tag")
            if not tag:
                continue
            addr = cell("address")
            p = Point(line, tag, cell("desc"), addr, _signal_type(cell("type"), addr), cell("device"),
                      _num(cell("lo")), _num(cell("hi")), cell("units"), cell("contact").upper() in ("NC", "N/C"))
            out.points.append(p)
            where = f"{ws.title} row {line}"
            if (why := _check_name(tag)) is not None:
                out.errors.append(f"{where}: {tag} {why}")
            if not p.type:
                out.errors.append(f"{where}: {tag} has no signal type (DI, DO, AI or AO)")
            if not addr:
                out.warnings.append(f"{where}: {tag} has no address (it will not be mapped until it has one)")
            elif (p.type in ("DI", "AI") and ":O" in addr.upper()) or (p.type in ("DO", "AO") and ":I" in addr.upper()):
                out.errors.append(f"{where}: {tag} is {p.type} but {addr} is an "
                                  f"{'output' if ':O' in addr.upper() else 'input'} address")
            if not p.desc:
                out.warnings.append(f"{where}: {tag} has no description")
            if p.type in ("AI", "AO") and (p.lo is None or p.hi is None):
                out.warnings.append(f"{where}: {tag} is analog with no range (Range low / Range high)")
            elif p.lo is not None and p.hi is not None and p.lo >= p.hi:
                out.errors.append(f"{where}: {tag} range low {p.lo:g} is not below range high {p.hi:g}")
    if not out.points:
        raise IOListError("no sheet has a header row with a Tag column and an Address or Type column")
    seen: dict[str, Point] = {}
    for p in out.points:
        k = p.tag.upper()  # Logix names are not case sensitive
        if k in seen:
            out.errors.append(f"{p.tag} appears twice (rows {seen[k].line} and {p.line}): one tag per signal")
        seen[k] = p
    used: dict[str, Point] = {}
    for p in out.points:
        k = p.address.upper().replace(" ", "")
        if k and k in used:
            out.errors.append(f"{p.address} is used by {used[k].tag} and {p.tag}: one signal per address")
        if k:
            used[k] = p
    groups: dict[str, Device] = {}
    for p in out.points:
        name = _device_of(p)
        if name:
            groups.setdefault(name, Device(name)).points.append(p)
    for d in groups.values():
        _recognise(d)
    out.devices = list(groups.values())
    return out


def plant_yaml(iol: IOList) -> str:
    """Plant file for the recognised devices; unrecognised ones are listed as comments to fill in."""
    lines = ["# Proposed from the I/O list: check the delays before trusting a test", "devices:"]
    for d in iol.devices:
        if d.plant:
            body = ", ".join(f"{k}: {v}" for k, v in d.plant.items())
            lines.append(f"  - {{{body}}}")
    rest = [d.name for d in iol.devices if not d.plant]
    if rest:
        lines.append(f"# not recognised, add by hand if they need simulating: {', '.join(rest)}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- mapping routines

SIM_MODE = "Sim_Mode"
CALLS = ("XIO(Sim_Mode)JSR(MAP_IN,0);  first rung of MainRoutine: field inputs, skipped in simulation",
         "JSR(MAP_OUT,0);  last rung of MainRoutine: field outputs, forced off in simulation")


@dataclass
class Mapping:
    map_in: list = field(default_factory=list)  # Rungs: raw input -> mapped tag
    map_out: list = field(default_factory=list)  # Rungs: mapped tag -> raw output
    tags: list = field(default_factory=list)  # TagDefs: mapped tags + Sim_Mode
    skipped: list[str] = field(default_factory=list)  # points with no address


def mapping(iol: IOList) -> Mapping:
    """Logic uses only mapped tags; two routines connect them to the field.

    MAP_IN is called with XIO(Sim_Mode)JSR(MAP_IN,0): while it is not scanned it writes nothing, so a
    plant model (or a test) owns the mapped inputs. An OTE inside it would write 0 every scan in
    simulation instead. MAP_OUT always runs and forces every physical output off in Sim_Mode, so a
    simulation on real hardware cannot move a field device. Analog values are moved as they arrive:
    scale on the card or add the scaling in MAP_IN by hand.
    """
    from core.compiler import TagDef
    from core.rung import parse_rung
    if iol.errors:
        raise IOListError(f"fix the I/O list first ({len(iol.errors)} errors), e.g. {iol.errors[0]}")
    m = Mapping()
    m.tags.append(TagDef(SIM_MODE, "BOOL", description="1 = simulation: field inputs not read, outputs off"))
    for p in iol.points:
        if not p.address:
            m.skipped.append(p.tag)
            continue
        analog = p.type in ("AI", "AO")
        rng = f" {p.lo:g}..{p.hi:g} {p.units}".rstrip() if p.lo is not None and p.hi is not None else ""
        m.tags.append(TagDef(p.tag, "REAL" if analog else "BOOL", description=(p.desc + rng).strip() or None))
        note = f"{p.desc or p.tag} ({p.address}){' NC: 1 = healthy' if p.nc else ''}"
        if p.type == "DI":
            text, target = f"XIC({p.address})OTE({p.tag});", m.map_in
        elif p.type == "AI":
            text, target = f"MOV({p.address},{p.tag});", m.map_in
        elif p.type == "DO":
            text, target = f"XIC({p.tag})XIO({SIM_MODE})OTE({p.address});", m.map_out
        else:
            text, target = (f"[XIO({SIM_MODE}) MOV({p.tag},{p.address}) ,XIC({SIM_MODE}) CLR({p.address}) ];",
                            m.map_out)
        target.append(parse_rung(text, note))
    return m


def mapping_l5x(iol: IOList, **routine_kw) -> dict[str, str]:
    """{"MAP_IN.L5X": ..., "MAP_OUT.L5X": ...}; each routine carries the tags it uses."""
    from core.rung import base_tag, is_literal, walk
    from l5x.writer import write_routine
    m = mapping(iol)
    out = {}
    for name, rungs in (("MAP_IN", m.map_in), ("MAP_OUT", m.map_out)):
        if rungs:
            used = {base_tag(a) for r in rungs for i in walk(r.body) for a in i.args if not is_literal(a)}
            out[f"{name}.L5X"] = write_routine(rungs, [t for t in m.tags if t.name in used], routine=name,
                                               **routine_kw)
    return out
