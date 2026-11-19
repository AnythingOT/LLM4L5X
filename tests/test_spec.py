"""Requirements workbook -> routines: reading the sheet, and the background build (model stubbed)."""
import base64
import io
import time
import zipfile

import pytest
from openpyxl import Workbook

import app as gui
from gui import state as gui_state
from gui.state import SESSION
from inputs.spec_excel import SpecSheetError, read_requirements, routine_name, sample
from l5x.reader import read_l5x
from udt.excel import is_udt_sheet, template


def book(sheets: dict[str, list[list]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_sample_reads_as_two_routines():
    sheets = read_requirements(sample())
    assert [(s.routine, len(s.rows)) for s in sheets] == [("Pump_Control", 5), ("Tank_Alarms", 3)]
    hand = sheets[0].rows[4]
    assert hand.logic.startswith("XIC(Pump_Run)") and not hand.request and hand.line == 6


def test_headers_are_matched_loosely_and_blank_rows_skipped():
    data = book({"Line 3 - Conveyor": [["Title"], [], ["No.", "Functional description", "Comment"],
                                        ["1", "Run the conveyor while the start button is held.", ""],
                                        [None, None, None], ["2", "Stop it on a jam.", "Jam"]]})
    (sh,) = read_requirements(data)
    assert sh.routine == "Line_3_Conveyor" and [r.ref for r in sh.rows] == ["1", "2"]
    assert sh.rows[1].comment == "Jam" and sh.rows[1].line == 6


@pytest.mark.parametrize("title,name", [("Pump control", "Pump_control"), ("2nd floor", "R_2nd_floor"),
                                        ("a__b__", "a_b"), ("x" * 50, "x" * 40), ("!!!", "Routine")])
def test_routine_names_are_valid(title, name):
    assert routine_name(title) == name


def test_workbook_without_requirements_is_refused_and_udt_sheets_are_told_apart():
    with pytest.raises(SpecSheetError):
        read_requirements(book({"S": [["a", "b"], ["1", "2"]]}))
    assert is_udt_sheet(template()) and not is_udt_sheet(sample())


# ---------------------------------------------------------------- the build, with a stub model

REPLIES = {  # request words that appear in no few-shot example -> the stub model's answer
    "Pump_Run from Start_PB": "Pump_Run := (Start_PB OR Pump_Run) AND NOT Stop_PB;",
    "Run_Lamp from Pump_Run": "Run_Lamp := Pump_Run;",
}


class Stub:
    supports_grammar, url = False, "http://stub"

    def chat(self, messages, grammar=None, **kw):
        ask = " ".join(m["content"] for m in messages)
        return next((v for k, v in REPLIES.items() if k in ask), "this is not LogicSpec")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(gui_state, "llm", lambda s: Stub())
    gui.app.config["TESTING"] = True
    with gui.app.test_client() as c:
        yield c
    SESSION.detach()


def run(client, data):
    r = client.post("/api/project", data={"file": (io.BytesIO(data), "req.xlsx")},
                    content_type="multipart/form-data").get_json()
    assert r["kind"] == "spec_started", r
    for _ in range(200):
        v = client.get(f"/api/jobs/{r['job']}").get_json()
        if v["status"] != "running":
            return r, v
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_rows_build_in_order_and_later_rows_know_earlier_tags(client):
    data = book({"Pump": [["Rung", "Requirement", "Rung comment", "Rung text"],
                          ["1", "Latch Pump_Run from Start_PB until Stop_PB.", "", ""],
                          ["2", "Light Run_Lamp from Pump_Run.", "Lamp", ""],
                          ["3", "", "", "XIC(Pump_Run)OTE(Pump_Healthy);"]]})
    started, v = run(client, data)
    assert started["sheets"] == [{"routine": "Pump", "title": "Pump", "rows": 3, "model_rows": 2}]
    assert v["status"] == "finished" and v["done"] == 3 and all(e["ok"] for e in v["events"])
    res = v["result"]
    assert res["download"] == "Pump.L5X" and res["sheets"][0]["rungs"] == 3
    p = read_l5x(res["l5x"].encode())
    rungs = p.routines[0].rungs
    assert [r.comment for r in rungs] == ["Latch Pump_Run from Start_PB until Stop_PB.", "Lamp", None]
    assert {"Pump_Run", "Run_Lamp", "Pump_Healthy"} <= set(p.tags)
    assert p.tags["Pump_Run"].datatype == "BOOL"  # made by row 1, reused (not redefined) by rows 2 and 3


def test_a_failing_row_is_reported_and_the_rest_still_build(client):
    data = book({"A": [["Requirement"], ["Latch Pump_Run from Start_PB until Stop_PB."], ["Nonsense here."]],
                 "B": [["Requirement", "Rung text"], ["", "XIC(X)OTE(Y);"]]})
    _, v = run(client, data)
    bad = [e for e in v["events"] if not e["ok"]]
    assert len(bad) == 1 and bad[0]["line"] == 3 and "could not produce" in bad[0]["error"]
    res = v["result"]
    assert res["download"] == "Routines.zip"
    z = zipfile.ZipFile(io.BytesIO(base64.b64decode(res["zip_b64"])))
    assert sorted(z.namelist()) == ["A.L5X", "B.L5X", "Report.txt"]
    report = z.read("Report.txt").decode()
    assert "row 3: FAILED" in report and "Routine B" in report


def test_udt_sheet_still_makes_udts(client):
    r = client.post("/api/project", data={"file": (io.BytesIO(template()), "u.xlsx")},
                    content_type="multipart/form-data").get_json()
    assert r["kind"] == "udt_created"


def test_samples_download(client):
    assert client.get("/api/spec/sample").mimetype.endswith("sheet")
    assert client.get("/api/jobs/nope").status_code == 404
