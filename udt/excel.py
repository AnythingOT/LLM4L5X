"""UDTs from an Excel sheet: one row per member.

Columns (first row is the header, names matched loosely):
    UDT | UDT description | Member | Data type | Description
A blank UDT cell means "same UDT as the row above". Data type is DINT, REAL[10],
BOOL[32], or the name of another UDT in the sheet or the attached project.
"""

from __future__ import annotations

import io
import re

from udt.model import NATIVE, UdtDef, UdtError, UdtMember

_COLS = {
    "udt": {"udt", "udt name", "data type name", "datatype name", "type name", "structure"},
    "udt_desc": {"udt description", "udt desc", "type description", "structure description"},
    "member": {"member", "member name", "field", "name", "tag"},
    "type": {"data type", "datatype", "type"},
    "desc": {"description", "member description", "comment", "desc"},
}
TEMPLATE_ROWS = [
    ("Motor_Status", "Status of one motor", "Running", "BOOL", "Motor is running"),
    ("", "", "Faulted", "BOOL", "Motor has a fault"),
    ("", "", "Speed", "REAL", "Speed, rpm"),
    ("", "", "Fault_Code", "DINT", "Last fault code"),
    ("", "", "Alarms", "BOOL[32]", "Alarm bits"),
    ("Line_Status", "Status of a line of motors", "Motors", "Motor_Status[4]", "The line's motors"),
    ("", "", "Line_Running", "BOOL", "Every motor is running"),
]


def _norm(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _find_header(ws):
    """(header columns, row iterator positioned after it) or (None, None)."""
    rows = ws.iter_rows(values_only=True)
    for n, row in enumerate(rows, 1):
        cells = [_norm(c).lower() for c in row]
        found = {k: cells.index(next(c for c in cells if c in names)) for k, names in _COLS.items()
                 if any(c in names for c in cells)}
        if {"udt", "member", "type"} <= set(found):
            return found, n, rows
        if n > 10:
            break
    return None, 0, None


def _open(data: bytes):
    from openpyxl import load_workbook
    try:
        return load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001 - not an xlsx, password protected ...
        raise UdtError(f"cannot read the workbook: {e}") from None


def is_udt_sheet(data: bytes) -> bool:
    """True if a sheet of the workbook has the UDT / Member / Data type header."""
    try:
        return any(_find_header(ws)[0] for ws in _open(data).worksheets)
    except UdtError:
        return False


def read_excel(data: bytes) -> list[UdtDef]:
    wb = _open(data)
    ws = next((s for s in wb.worksheets if s.title.lower() in ("udts", "udt")), wb.worksheets[0])
    header, start, rows = _find_header(ws)
    if header is None:
        raise UdtError("no header row with UDT, Member and Data type columns in the first 10 rows "
                       "(download the template)")
    udts: list[UdtDef] = []
    def cell(row, key):
        i = header.get(key)
        return _norm(row[i]) if i is not None and i < len(row) else ""

    for n, row in enumerate(rows, start + 1):
        name, member, dtype = cell(row, "udt"), cell(row, "member"), cell(row, "type")
        if not (name or member or dtype):
            continue
        if name and (not udts or udts[-1].name != name):
            if any(u.name == name for u in udts):
                raise UdtError(f"row {n}: rows of UDT {name} must be together")
            udts.append(UdtDef(name, cell(row, "udt_desc")))
        elif not udts:
            raise UdtError(f"row {n}: the first row needs a UDT name")
        if cell(row, "udt_desc") and not udts[-1].description:
            udts[-1].description = cell(row, "udt_desc")
        if not member:
            continue
        m = re.fullmatch(r"([A-Za-z_]\w*)\s*(?:\[\s*(\d+)\s*\])?", dtype)
        if not m:
            raise UdtError(f"row {n}: data type '{dtype}' is not like DINT, REAL[10] or a UDT name")
        t = m.group(1).upper() if m.group(1).upper() in NATIVE else m.group(1)
        udts[-1].members.append(UdtMember(member, t, int(m.group(2) or 0), cell(row, "desc")))
    if not udts:
        raise UdtError("the sheet has no UDT rows")
    return udts


def template() -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "UDTs"
    ws.append(["UDT", "UDT description", "Member", "Data type", "Description"])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1A3A5C")
    for r in TEMPLATE_ROWS:
        ws.append(list(r))
    for col, w in zip("ABCDE", (18, 30, 18, 18, 36)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    info = wb.create_sheet("How to fill")
    for line in [
        "One row per member. Rows of one UDT stay together; leave UDT empty to continue the UDT above.",
        "Data type: BOOL, SINT, INT, DINT, LINT, REAL, LREAL, STRING, TIMER, COUNTER, CONTROL, add [n] for an array,",
        "or the name of another UDT in this sheet or in the attached project. BOOL arrays: a multiple of 32.",
        "Names: letters, digits and _, up to 40 characters, not starting with a digit, no __ and no _ at the end.",
        "Member order does not matter: LLM4L5X writes the members in the order that wastes no memory.",
    ]:
        info.append([line])
    info.column_dimensions["A"].width = 110
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
