"""The test report as a PDF, made from a run record (testcases/evidence.py) and nothing else.

The PDF is marked "no changes" for PDF readers (they honour it; an editing tool need not). What makes the
report trustworthy is that every page prints the record's SHA-256: the report can be checked against the
record kept in runs/, and a changed report or record no longer matches.
"""

from __future__ import annotations

import io
import secrets
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from testcases.evidence import fingerprint

INK = colors.HexColor("#16233a")
MUTED = colors.HexColor("#6b7a90")
LINE = colors.HexColor("#d8dee7")
PASS = colors.HexColor("#1d7f4a")
FAIL = colors.HexColor("#be3a32")
WARN = colors.HexColor("#a86a0b")

_ss = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=_ss["Heading1"], fontSize=17, textColor=INK, spaceAfter=4)
H2 = ParagraphStyle("h2", parent=_ss["Heading2"], fontSize=12.5, textColor=INK, spaceBefore=10, spaceAfter=4)
H3 = ParagraphStyle("h3", parent=_ss["Heading3"], fontSize=10.5, textColor=INK, spaceBefore=8, spaceAfter=2)
BODY = ParagraphStyle("body", parent=_ss["BodyText"], fontSize=9, leading=12, textColor=INK, alignment=TA_LEFT)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=7.5, leading=9.5, textColor=MUTED)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=8, leading=10)
MONO = ParagraphStyle("mono", parent=CELL, fontName="Courier", fontSize=7.5, leading=9.5)

_STATUS = {"Pass": PASS, "Fail": FAIL}


def _p(text, style=CELL) -> Paragraph:
    return Paragraph(escape(str(text)), style)


def _verdict(text: str) -> Paragraph:
    c = _STATUS.get(text, WARN)
    return Paragraph(f'<font color="{c.hexval()}"><b>{escape(text)}</b></font>', CELL)


def _table(rows, widths, head=True) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1 if head else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
             ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
             ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
    if head:
        style += [("TEXTCOLOR", (0, 0), (-1, 0), MUTED), ("LINEBELOW", (0, 0), (-1, 0), 0.8, MUTED)]
    t.setStyle(TableStyle(style))
    return t


def _head(cells) -> list:
    return [Paragraph(f"<b>{escape(c)}</b>", SMALL) for c in cells]


def build_pdf(record: dict) -> bytes:
    fp = fingerprint(record)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
        title=f"Test report {record['id']}", author="LLM4L5X", subject="Test run evidence",
        encrypt=StandardEncryption("", ownerPassword=secrets.token_hex(16), canPrint=1, canModify=0,
                                   canCopy=1, canAnnotate=0))
    width = A4[0] - 32 * mm
    s = record["summary"]
    story = [Paragraph("Test report", H1),
             Paragraph(f"Run {escape(record['id'])}, {escape(record['created'])}", SMALL), Spacer(1, 6)]

    # ---- summary: what this is, and what it is not
    if not s["test_cases"]:
        verdict, colour = "No test cases ran", WARN
    elif s["failed"]:
        verdict, colour = f"{s['failed']} of {s['test_cases']} test cases fail", FAIL
    else:
        verdict, colour = "All test cases pass", PASS
    story += [Paragraph("Summary", H2), _table([
        [_p("Result"), Paragraph(f'<font color="{colour.hexval()}"><b>{escape(verdict)}</b></font>', CELL)],
        [_p("Test cases"), _p(f"{s['passed']} pass, {s['failed']} fail, of {s['test_cases']}")],
        [_p("Requirements"), _p(f"{s['requirements_passed']} of {s['requirements']} pass (see the matrix)")],
        [_p("Ran on"), _p(f"{record['target']['name']}, scan {record['target']['scan_ms']:g} ms")],
        [_p("What this is"), _p(record["target"]["note"] + " Engineering evidence from an open-source tool: "
                                "not a validated record under any regulation.")],
    ], [32 * mm, width - 32 * mm], head=False)]

    # ---- inputs and fingerprints
    rows = [_head(["Input", "Name", "SHA-256"])]
    for i in record["inputs"]:
        rows.append([_p(i["kind"]), _p(i["name"] or "-"), _p(i["sha256"], MONO)])
    rows.append([_p("tool code"), _p(record["tool"]["name"]), _p(record["tool"]["code_sha256"], MONO)])
    story += [Paragraph("What was tested", H2),
              Paragraph("A change to any of these makes a different run.", SMALL),
              _table(rows, [30 * mm, 52 * mm, width - 82 * mm])]

    # ---- traceability matrix
    rows = [_head(["Requirement", "Text", "Rungs", "Test cases", "Result"])]
    for m in record["matrix"]:
        tests = ", ".join(f"{t['id']} {'pass' if t['passed'] else 'FAIL'}" for t in m["tests"]) or "-"
        rows.append([_p(m["id"]), _p(m["text"] or "-"), _p(", ".join(m["rungs"]) or "-"), _p(tests),
                     _verdict(m["status"])])
    story += [Paragraph("Traceability matrix", H2),
              _table(rows, [24 * mm, width - 24 * mm - 34 * mm - 34 * mm - 22 * mm, 34 * mm, 34 * mm, 22 * mm])
              if len(rows) > 1 else Paragraph("No requirements: no requirements workbook and no Req IDs.", BODY)]

    # ---- gaps
    g = record["gaps"]
    lines = [("Requirements with no test case", g.get("no_test")),
             ("Requirements with no rung", g.get("not_built")),
             ("Requirement IDs not in the requirements workbook", g.get("unknown_requirement")),
             ("Test cases tied to no requirement", g.get("tests_without_requirement")),
             ("Rungs that serve no requirement", g.get("rungs_without_requirement"))]
    story.append(Paragraph("Gaps", H2))
    if any(v for _, v in lines):
        story.append(_table([[_p(k), _p(", ".join(v))] for k, v in lines if v], [62 * mm, width - 62 * mm],
                            head=False))
    else:
        story.append(Paragraph("None.", BODY))

    # ---- test cases, step by step
    story += [PageBreak(), Paragraph("Test cases", H2)]
    for r in record["results"]:
        head = Paragraph(f"{escape(r['id'])} {escape(r['title'] or '')}"
                         + (f"  <font color='{MUTED.hexval()}' size='8'>{escape(', '.join(r['reqs']))}</font>"
                            if r["reqs"] else ""), H3)
        body = [head, _verdict("Pass" if r["passed"] else "Fail")]
        if r["error"]:
            body.append(_p(f"Could not run: {r['error']}"))
        rows = [_head(["Line", "Phase", "Step", "Actual", "At (ms)", "Result"])]
        for st in r["steps"]:
            res = "" if st["passed"] is None else ("pass" if st["passed"] else "FAIL")
            step = st["text"] + (f"  ({st['message']})" if st["message"] else "")
            rows.append([_p(st["line"] or "", SMALL), _p(st["phase"].lower(), SMALL), _p(step, MONO),
                         _p("" if st["actual"] is None else st["actual"], MONO), _p(f"{st['t_ms']:g}", SMALL),
                         _verdict(res.capitalize()) if res else _p("")])
        if len(rows) > 1:
            body.append(_table(rows, [10 * mm, 16 * mm, width - 10 * mm - 16 * mm - 22 * mm - 16 * mm - 14 * mm,
                                      22 * mm, 16 * mm, 14 * mm]))
        # a short test case stays on one page; a long one may break across pages
        story += [KeepTogether(body)] if len(rows) < 25 else body

    # ---- sign-off (paper)
    story += [Spacer(1, 14), Paragraph("Checked by", H2), _table([
        [_p("Prepared by"), _p("Name ____________________"), _p("Date __________"), _p("Signature ______________")],
        [_p("Reviewed by"), _p("Name ____________________"), _p("Date __________"), _p("Signature ______________")],
    ], [26 * mm, 58 * mm, 36 * mm, width - 120 * mm], head=False)]

    def page(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(16 * mm, 9 * mm, f"Run {record['id']}   Record SHA-256 {fp}")
        canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f"Page {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=page, onLaterPages=page)
    return buf.getvalue()
