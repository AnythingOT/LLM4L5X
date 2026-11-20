"""Requirements workbook -> routines: reading the sheet, and the background build (model stubbed)."""
import base64
import io
import time
import zipfile

import pytest
from openpyxl import Workbook

import app as gui
from gui import jobs, state as gui_state
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


def test_expected_column_scores_rows_by_behaviour(client):
    data = book({"T": [["Requirement", "Expected rung"],
                       ["Latch Pump_Run from Start_PB until Stop_PB.", "[XIC(Pump_Run) ,XIC(Start_PB) ]XIO(Stop_PB)OTE(Pump_Run);"],
                       ["Light Run_Lamp from Pump_Run.", "XIO(Pump_Run)OTE(Run_Lamp);"],
                       ["Nonsense here.", "XIC(A)OTE(B);"]]})
    _, v = run(client, data)
    e = v["events"]
    assert e[0]["match"] is True                      # same behaviour, branch legs in another order
    assert e[1]["match"] is False and e[1]["match_why"]
    assert "match" not in e[2] and not e[2]["ok"]     # not built: counts as wrong
    (sheet,) = v["result"]["sheets"]
    assert (sheet["expected"], sheet["matched"]) == (3, 1)
    z = zipfile.ZipFile(io.BytesIO(base64.b64decode(v["result"]["zip_b64"]))) if "zip_b64" in v["result"] else None
    assert z is None or "test score: 1 of 3" in z.read("Report.txt").decode()


def test_test_workbook_has_every_structure_and_an_expected_rung_per_row(tmp_path):
    from eval.test_workbook import build
    out = tmp_path / "t.xlsx"
    counts = build(out, seed=1, rows=4)
    assert set(counts) == {"Series", "Parallel", "Nested", "Multi_output", "Referenced"}
    sheets = read_requirements(out.read_bytes())
    assert all(r.expected for s in sheets for r in s.rows)
    assert {s.routine for s in sheets} == set(counts)


def test_test_workbook_gives_each_tag_one_owner(tmp_path):
    # the sheets become routines of one program: a tag written on two sheets would be one
    # timer with two owners and two presets, so the expected answers could not all hold
    from core.catalog import default_catalog
    from core.rung import parse_rung
    from eval.rung_compare import Side, _refs
    from eval.test_workbook import build
    out = tmp_path / "t.xlsx"
    counts = build(out, seed=3, rows=12)
    assert counts["Multi_output"] == 12  # the name pools are big enough to fill every sheet
    owner = {}  # tag -> sheet that writes it (Referenced latches and unlatches one alarm on purpose)
    for sh in read_requirements(out.read_bytes()):
        for r in sh.rows:
            rungs = [parse_rung(t) for t in r.expected.splitlines()]
            for w in {x.split(".")[0].split("[")[0] for x in _refs(Side(rungs, {}), default_catalog())[2]}:
                assert owner.setdefault(w, sh.title) == sh.title, f"{w} written on {owner[w]} and {sh.title}"


def test_a_row_asking_another_preset_for_an_earlier_timer_fails_clearly(monkeypatch):
    class Two:
        supports_grammar, url = False, "http://stub"

        def chat(self, messages, grammar=None, **kw):
            ask = messages[-1]["content"]
            return ("IF Go_Cmd THEN ON_DELAY_TIMER(Wait_TMR, 5s);" if "5 second" in ask
                    else "IF Run_Cmd THEN ON_DELAY_TIMER(Wait_TMR, 2s);")

    monkeypatch.setattr(gui_state, "llm", lambda s: Two())
    data = book({"A": [["Requirement"], ["Run Wait_TMR for 5 seconds while Go_Cmd is on."]],
                 "B": [["Requirement"], ["Run Wait_TMR for 2 seconds while Run_Cmd is on."]]})
    from gui.spec import _run
    from gui.state import settings
    job = jobs.Job("t", 2)
    out = _run(job, read_requirements(data), settings({}), "req.xlsx")
    bad = [e for e in job.events if not e["ok"]]
    assert len(bad) == 1 and bad[0]["sheet"] == "B"
    assert "already exists with preset 5000" in bad[0]["error"] and "asks for 2000" in bad[0]["error"]
    report = zipfile.ZipFile(io.BytesIO(base64.b64decode(out["zip_b64"]))).read("Report.txt").decode()
    assert "FAILED: Wait_TMR already exists" in report


def test_sheets_share_one_tag_table(monkeypatch):
    # all sheets go into one program: a tag made on sheet A keeps its type on sheet B,
    # and the one-shot on each sheet gets its own storage bit
    class Edge:
        supports_grammar, url = False, "http://stub"

        def chat(self, messages, grammar=None, **kw):
            ask = messages[-1]["content"]
            return ("IF RISE(Go_Cmd) THEN SET Fill_Valve;" if "Go_Cmd" in ask
                    else "IF RISE(Fill_Valve) THEN SET Lamp_Out;")

    monkeypatch.setattr(gui_state, "llm", lambda s: Edge())
    data = book({"A": [["Requirement"], ["Pulse Fill_Valve when Go_Cmd turns on."]],
                 "B": [["Requirement"], ["Latch Lamp_Out when Fill_Valve turns on."]]})
    from gui.spec import _run
    from gui.state import settings
    from inputs.spec_excel import read_requirements
    out = _run(jobs.Job("t", 2), read_requirements(data), settings({}), "req.xlsx")
    z = zipfile.ZipFile(io.BytesIO(base64.b64decode(out["zip_b64"])))
    a, b = read_l5x(z.read("A.L5X")), read_l5x(z.read("B.L5X"))
    ons_a = {n for n in a.tags if n.startswith("L4X_ONS")}
    ons_b = {n for n in b.tags if n.startswith("L4X_ONS")} - ons_a
    assert ons_a and ons_b                          # B made a new bit, not a second L4X_ONS_1
    assert b.tags["Fill_Valve"].datatype == "BOOL"  # carried from sheet A
    assert "Go_Cmd" not in b.tags                   # A's tag that B does not use stays out


def test_sheets_known_tags_are_passed_on(monkeypatch):
    seen = []
    import gui.spec as spec_mod
    real = spec_mod._row

    def spy(client, row, s, project_types, new_tags, catalog):
        seen.append(set(new_tags))
        return real(client, row, s, project_types, new_tags, catalog)

    monkeypatch.setattr(spec_mod, "_row", spy)
    data = book({"A": [["Rung text"], ["XIC(Go)OTE(Fill_Valve);"]],
                 "B": [["Rung text"], ["XIC(Fill_Valve)OTE(Lamp);"]]})
    from gui.state import settings
    from inputs.spec_excel import read_requirements
    spec_mod._run(jobs.Job("t", 2), read_requirements(data), settings({}), "req.xlsx")
    assert "Fill_Valve" in seen[1]


@pytest.mark.parametrize("seed", [1, 4, 5, 7])  # seeds whose last suite sheet used to come up short
def test_test_workbook_fills_every_sheet(tmp_path, seed):
    from eval.test_workbook import build
    counts = build(tmp_path / "t.xlsx", seed=seed, rows=12)
    assert all(v == 12 for v in counts.values()), counts


def test_test_workbook_refuses_a_missing_or_empty_corpus(tmp_path):
    from eval.test_workbook import build
    with pytest.raises(SystemExit, match="no such folder"):
        build(tmp_path / "t.xlsx", corpus=tmp_path / "nope")
    with pytest.raises(SystemExit, match="no .L5X files"):
        build(tmp_path / "t.xlsx", corpus=tmp_path)


@pytest.mark.parametrize("text, why", [
    ("[XIC(B) ,XIC(B) ][OTE(B) ,OTU(B) ];", "ERR010"),          # a parser's test sample, not logic
    ("XIC(A)[OTE(Lamp) ,OTU(Lamp) ];", "turned on and off in the same rung"),
    ("XIC(A)[TON(T1,100,0) ,TON(T1,100,0) ];", "ERR"),
])
def test_real_world_skips_rungs_no_sentence_would_ask_for(text, why):
    from core.rung import parse_rung
    from eval.test_workbook import nonsense
    assert why in (nonsense(parse_rung(text)) or "")


@pytest.mark.parametrize("text", [
    "[XIC(Start) ,XIC(Motor) ]XIO(Stop)OTE(Motor);",               # seal-in reads its own output: real logic
    "[XIC(A) ,XIC(B) ]OTL(Alarm);",
])
def test_real_world_keeps_ordinary_rungs(text):
    from core.rung import parse_rung
    from eval.test_workbook import nonsense
    assert nonsense(parse_rung(text)) is None


def test_report_shows_how_many_attempts_each_row_took(monkeypatch):
    class Flaky(Stub):  # wrong once for Run_Lamp, then right
        seen = 0

        def chat(self, messages, grammar=None, **kw):
            if "Run_Lamp from Pump_Run" in " ".join(m["content"] for m in messages):
                Flaky.seen += 1
                if Flaky.seen == 1:
                    return "this is not LogicSpec"
            return super().chat(messages, grammar, **kw)

    monkeypatch.setattr(gui_state, "llm", lambda s: Flaky())
    gui.app.config["TESTING"] = True
    data = book({"A": [["Requirement", "Expected rung"],
                       ["Latch Pump_Run from Start_PB until Stop_PB.", "[XIC(Pump_Run) ,XIC(Start_PB) ]XIO(Stop_PB)OTE(Pump_Run);"],
                       ["Light Run_Lamp from Pump_Run.", "XIC(Pump_Run)OTE(Run_Lamp);"]],
                 "B": [["Requirement", "Rung text"], ["", "XIC(X)OTE(Y);"]]})
    with gui.app.test_client() as c:
        _, v = run(c, data)
    SESSION.detach()
    lamp = v["events"][1]
    assert (v["events"][0]["attempts"], lamp["attempts"]) == (1, 2) and lamp["match"]
    report = zipfile.ZipFile(io.BytesIO(base64.b64decode(v["result"]["zip_b64"]))).read("Report.txt").decode()
    assert "row 2: ok, 1 rung, matches expected\r\n" in report            # first try: nothing added
    assert "row 3: ok, 1 rung, matches expected (2 attempts)" in report
    assert "sent back: " in report
    assert "model: 2 rows, 1 needed more than one attempt (1 extra attempt)" in report
    assert "Total: 2 of 2 rows behave as expected; model: 2 rows, 1 needed more than one attempt" in report
