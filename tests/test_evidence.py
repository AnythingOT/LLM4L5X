"""Test evidence: requirements from the instruction sheet, traceability, run records, the PDF report."""
import io
from datetime import datetime, timezone

import pytest
from openpyxl import Workbook

from core.compiler import TagDef
from core.rung import Rung, parse_rung
from l5x.writer import write_routine
from testcases import parse_scenarios, run_scenarios
from testcases.backend import SimBackend
from testcases.evidence import (RunStore, code_fingerprint, fingerprint, requirements_from_workbook,
                               rungs_by_requirement, run_record)

ROWS = [  # Req ID, requirement, rung
    ("R1", "Run Pump_Run from Start_PB until Stop_PB.", "[XIC(Start_PB) ,XIC(Pump_Run) ]XIO(Stop_PB)OTE(Pump_Run);"),
    ("R2", "Lamp follows Pump_Run.", "XIC(Pump_Run)OTE(Lamp);"),
    ("R2", "Horn follows Pump_Run too.", "XIC(Pump_Run)OTE(Horn);"),
    ("", "Beacon follows Lamp.", "XIC(Lamp)OTE(Beacon);"),        # no Req ID: a requirement of its own
    ("INFRA", "Map the inputs.", "XIC(In_1)OTE(Map_1);"),           # serves no requirement
    ("R9", "Not built at all.", None),                              # in the workbook, no rung
]
TESTS = """SCENARIO TC-01 "start holds" REQ R1
  SET Start_PB = 1
  WAIT 50
  SET Start_PB = 0
  EXPECT Pump_Run == 1 within_ms 100 hold

SCENARIO TC-02 "lamp and horn" REQ R2
  SET Start_PB = 1
  EXPECT Lamp == 1 within_ms 100
  EXPECT Horn == 0

SCENARIO TC-03 "no requirement"
  EXPECT Beacon == 0

SCENARIO TC-04 "a requirement the workbook does not have" REQ R77
  EXPECT Lamp == 0
"""


def workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Pump"
    ws.append(["Rung", "Req ID", "Requirement"])
    for n, (req, text, _) in enumerate(ROWS, 1):
        ws.append([n, req, text])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def program() -> bytes:
    """The generated routine: each rung's comment carries its Req IDs, as a requirements run writes it."""
    rungs = []
    for req, text, rung in ROWS:
        if rung is None:
            continue
        comment = text if req in ("", "INFRA") else f"[{req}] {text}"
        rungs.append(Rung(parse_rung(rung).body, comment))
    rungs.append(parse_rung("XIC(Extra_In)OTE(Extra_Out);"))  # a rung nobody asked for
    return write_routine(rungs, [TagDef("Pump_Run", "BOOL")], routine="Pump").encode()


def results():
    from core.rung import parse_rung as pr
    from l5x.reader import read_l5x
    rungs = [g.rung for rt in read_l5x(program()).routines for g in rt.rungs]
    return run_scenarios(parse_scenarios(TESTS), lambda: SimBackend([r or pr(";") for r in rungs]))


NOW = datetime(2026, 11, 24, 9, 30, tzinfo=timezone.utc)


def record(**kw):
    args = dict(program=[("Pump.L5X", program())], devices="", tests=TESTS, results=results(),
                requirements=("Requirements.xlsx", workbook()), now=NOW)
    args.update(kw)
    return run_record(**args)


def test_requirements_come_from_the_instruction_sheet():
    reqs = {r.id: r for r in requirements_from_workbook(workbook())}
    assert list(reqs) == ["R1", "R2", "Pump row 5", "R9"]  # INFRA serves none
    assert reqs["R2"].text == "Lamp follows Pump_Run. Horn follows Pump_Run too." and reqs["R2"].rows == [
        "Pump row 3", "Pump row 4"]
    assert reqs["Pump row 5"].from_row and reqs["Pump row 5"].text == "Beacon follows Lamp."


def test_rungs_are_traced_by_the_req_ids_in_their_comments():
    by_req, orphans = rungs_by_requirement([program()], requirements_from_workbook(workbook()))
    assert by_req["R1"] == ["Pump rung 0"] and by_req["R2"] == ["Pump rung 1", "Pump rung 2"]
    assert by_req["Pump row 5"] == ["Pump rung 3"]  # no Req ID: matched by its requirement text
    assert orphans == ["Pump rung 4", "Pump rung 5"]  # the INFRA rung and the extra one serve no requirement


def test_the_matrix_and_its_gaps():
    rec = record()
    status = {m["id"]: m["status"] for m in rec["matrix"]}
    # TC-02 fails (Horn follows Pump_Run); R77 is not in the workbook and no rung implements it
    assert status == {"R1": "Pass", "R2": "Fail", "Pump row 5": "No test", "R9": "Not built, no test",
                      "R77": "Not built"}
    g = rec["gaps"]
    assert g["no_test"] == ["Pump row 5", "R9"] and g["not_built"] == ["R9"]
    assert g["unknown_requirement"] == ["R77"] and g["tests_without_requirement"] == ["TC-03"]
    assert g["rungs_without_requirement"] == ["Pump rung 4", "Pump rung 5"]
    assert rec["summary"] == {"test_cases": 4, "passed": 3, "failed": 1, "requirements": 5,
                              "requirements_passed": 1}


def test_every_step_is_evidence_with_what_was_read_and_when():
    tc1 = next(r for r in record()["results"] if r["id"] == "TC-01")
    exp = tc1["steps"][-1]
    assert exp["action"] == "EXPECT" and exp["passed"] is True and exp["actual"] == 1  # a bit reads as 1, not True
    assert exp["t_ms"] == 150 and "held 100 ms" in exp["message"]


def test_the_record_names_exactly_what_was_tested():
    rec = record()
    kinds = {i["kind"]: i for i in rec["inputs"]}
    assert set(kinds) == {"program", "requirements", "device models", "test cases"}
    assert len(rec["tool"]["code_sha256"]) == 64 and rec["tool"]["code_sha256"] == code_fingerprint()
    assert rec["id"] == "20261124-093000-" + fingerprint(rec)[:8]
    # any change to an input is a different run
    changed = record(tests=TESTS.replace("within_ms 100 hold", "within_ms 90 hold"))
    assert fingerprint(changed) != fingerprint(rec) and changed["id"] != rec["id"]
    assert fingerprint(record()) == fingerprint(rec)  # and nothing else does


def test_a_run_is_written_once_and_never_replaced(tmp_path):
    store = RunStore(tmp_path)
    rec = record()
    first = store.save(rec)
    second = store.save(dict(rec, id=rec["id"]))  # the same run again in the same second
    assert first != second and second.name.endswith("-2.json") and first.read_text() != ""
    assert [r["id"] for r in store.list()] == [second.stem, first.stem]
    assert store.get("../../etc/passwd") is None and store.get("nope") is None


def test_the_pdf_report_is_made_from_the_record_and_marked_no_changes():
    from testcases.report_pdf import build_pdf
    pdf = build_pdf(record())
    assert pdf.startswith(b"%PDF") and b"/Encrypt" in pdf  # permissions: print and copy yes, modify no
    assert len(pdf) > 3000


@pytest.fixture
def web(tmp_path):
    import app as gui
    from gui import ENERGIZE
    gui.app.config["TESTING"] = True
    gui.app.config["RUNS"] = RunStore(tmp_path / "runs")
    ENERGIZE.clear()
    with gui.app.test_client() as c:
        yield c
    ENERGIZE.clear()


def test_tests_page_keeps_evidence_and_serves_the_report(web):
    up = web.post("/api/energize/load", data={"files": [(io.BytesIO(program()), "Pump.L5X")]},
                  content_type="multipart/form-data")
    assert up.status_code == 200
    bad = web.post("/api/tests/requirements", data={"file": (io.BytesIO(b"no excel"), "x.xlsx")},
                   content_type="multipart/form-data")
    assert bad.status_code == 400
    ok = web.post("/api/tests/requirements", data={"file": (io.BytesIO(workbook()), "Req.xlsx")},
                  content_type="multipart/form-data").get_json()
    assert ok == {"name": "Req.xlsx", "count": 4}
    assert web.get("/api/energize/state").get_json()["requirements"] == ok
    web.post("/api/tests/save", json={"tests": TESTS})
    run = web.post("/api/tests/run").get_json()
    assert (run["passed"], run["total"]) == (3, 4) and run["gaps"]["not_built"] == ["R9"]
    runs = web.get("/api/tests/runs").get_json()["runs"]
    assert [r["id"] for r in runs] == [run["run_id"]] and runs[0]["program"] == ["Pump.L5X"]
    pdf = web.get(f"/api/tests/runs/{run['run_id']}/report.pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF") and "attachment" in pdf.headers[
        "Content-Disposition"]
    rec = web.get(f"/api/tests/runs/{run['run_id']}/record.json").get_json()
    assert rec["id"] == run["run_id"] and fingerprint(rec).startswith(run["run_id"].split("-")[2])
    assert web.get("/api/tests/runs/nope/report.pdf").status_code == 404
