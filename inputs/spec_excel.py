"""A requirements workbook: each sheet is one routine, each row one requirement (one or more rungs).

Columns (first row with a Requirement column is the header; names matched loosely):
    Rung | Requirement | Rung comment | Rung text
- Requirement: what the rung must do, in plain English (goes to the model).
- Rung text: optional neutral or ASCII rung text; when filled, it is used as written and the
  model is not asked.
- Rung comment: optional; empty = the requirement itself becomes the rung comment.
- Rung: optional reference shown in the report (e.g. URS 4.2.1).
Sheets named "How to fill", "Instructions", "README" or "Notes" are skipped.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

_COLS = {
    "ref": {"rung", "no", "no.", "#", "ref", "reference", "id", "req id", "requirement id", "urs", "step"},
    "request": {"requirement", "requirements", "request", "description", "logic description",
                "functional description", "what it does", "plain english", "english"},
    "comment": {"rung comment", "comment", "comments"},
    "logic": {"rung text", "logic", "ladder", "neutral text", "ascii text", "rung"},
}
_SKIP = {"how to fill", "instructions", "readme", "read me", "notes"}


class SpecSheetError(ValueError):
    pass


@dataclass
class Row:
    line: int  # Excel row number, for the report
    ref: str
    request: str
    comment: str
    logic: str


@dataclass
class Sheet:
    title: str  # as in Excel
    routine: str  # a valid Logix routine name made from the title
    rows: list[Row] = field(default_factory=list)


def _norm(v) -> str:
    return re.sub(r"[ \t]+", " ", str(v if v is not None else "")).strip()


def routine_name(title: str) -> str:
    """Excel sheet title -> Logix name: letters, digits and _, max 40, no leading digit, no __."""
    n = re.sub(r"[^A-Za-z0-9_]+", "_", title).strip("_")
    n = re.sub(r"_+", "_", n)[:40].rstrip("_") or "Routine"
    return n if not n[0].isdigit() else f"R_{n}"[:40]


def _cell(row, header: dict[str, int], key: str) -> str:
    i = header.get(key)
    return _norm(row[i]) if i is not None and i < len(row) else ""


def _header(cells: list[str]) -> dict[str, int] | None:
    found = {}
    for key, names in _COLS.items():
        for i, c in enumerate(cells):
            if c in names and i not in found.values():
                found[key] = i
                break
    if "request" not in found and "logic" not in found:
        return None
    return found


def read_requirements(data: bytes) -> list[Sheet]:
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001 - not an xlsx, password protected ...
        raise SpecSheetError(f"cannot read the workbook: {e}") from None
    sheets: list[Sheet] = []
    used: set[str] = set()
    for ws in wb.worksheets:
        if ws.title.strip().lower() in _SKIP:
            continue
        header = None
        rows = ws.iter_rows(values_only=True)
        for n, row in enumerate(rows, 1):
            header = _header([_norm(c).lower() for c in row])
            if header or n >= 10:
                break
        if not header:
            continue
        name = routine_name(ws.title)
        base, k = name, 2
        while name.upper() in used:  # two sheets that clean up to the same name
            name = f"{base[:37]}_{k}"
            k += 1
        used.add(name.upper())
        sheet = Sheet(ws.title, name)

        for line, row in enumerate(rows, n + 1):
            r = Row(line, *(_cell(row, header, k) for k in ("ref", "request", "comment", "logic")))
            if r.request or r.logic:
                sheet.rows.append(r)
        if sheet.rows:
            sheets.append(sheet)
    if not sheets:
        raise SpecSheetError("no sheet has a header row with a Requirement (or Rung text) column "
                             "in its first 10 rows (download the sample)")
    return sheets


def is_requirements(data: bytes) -> bool:
    """True if the workbook looks like requirements rather than a UDT sheet."""
    try:
        read_requirements(data)
        return True
    except SpecSheetError:
        return False


SAMPLE = {
    "Pump_Control": [
        ("1", "Start the pump with the start button and keep it running until the stop button is pressed "
              "or the pump faults.", "", ""),
        ("2", "Turn on the pump running lamp while the pump runs.", "Running lamp", ""),
        ("3", "When the pump has run for 10 seconds and the pressure switch is still off, latch the "
              "no-pressure alarm.", "", ""),
        ("4", "Reset the no-pressure alarm with the reset button.", "", ""),
        ("5", "", "Hand-written rung: passed through as is", "XIC(Pump_Run)XIO(Pump_Fault)OTE(Pump_Healthy);"),
    ],
    "Tank_Alarms": [
        ("1", "Raise the high level alarm when the tank level stays above 80 for 5 seconds, unless the alarm "
              "is muted.", "", ""),
        ("2", "Turn on the horn while the high level alarm is on and the horn has not been silenced.", "", ""),
        ("3", "Count tank fills on the fill complete sensor; the batch is done at 10 fills. Reset the count "
              "with the batch reset button.", "", ""),
    ],
}


def sample() -> bytes:
    """A workbook to try: two routines, one row passed through as rung text."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    wb.remove(wb.active)
    for title, rows in SAMPLE.items():
        ws = wb.create_sheet(title)
        ws.append(["Rung", "Requirement", "Rung comment", "Rung text"])
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="16233A")
        for r in rows:
            ws.append(list(r))
        for col, w in zip("ABCD", (8, 80, 30, 50)):
            ws.column_dimensions[col].width = w
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.freeze_panes = "A2"
    info = wb.create_sheet("How to fill")
    for line in [
        "Each sheet is one routine; the sheet name becomes the routine name. Each row is one requirement.",
        "Requirement: what the rung must do, in plain English. One row can become more than one rung.",
        "Rung text (optional): neutral XIC(a)OTE(b); or ASCII XIC a OTE b. Used as written; the model is not asked.",
        "Rung comment (optional): empty means the requirement becomes the rung comment.",
        "Rung (optional): your reference, shown in the report.",
        "Name tags the way they are in your project, and attach the project first so they are used.",
        "Tags created by one row are known to the rows below it, so later rows can use them by name.",
    ]:
        info.append([line])
    info.column_dimensions["A"].width = 110
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
