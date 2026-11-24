"""The oracle report: an unanswerable row is listed once, by Excel row with its Rung number."""
from openpyxl import Workbook

from eval.oracle_run import _where, main, run


def test_unanswerable_row_is_listed_once_with_its_rung(tmp_path, capsys):
    wb = Workbook()
    ws = wb.active
    ws.title = "Main"
    ws.append(["Rung", "Requirement", "Expected rung"])
    ws.append([1, "Turn on Lamp when Start_PB is on.", "XIC(Start_PB)OTE(Lamp);"])
    # an ONS that does not start the power path: the decompiler cannot express it
    ws.append([7, "Turn on Horn when Run is on and either Alarm rises or Test_PB is on.",
               "XIC(Run)[XIC(Alarm) ONS(Horn_ONS) ,XIC(Test_PB) ]OTE(Horn);"])
    f = tmp_path / "wb.xlsx"
    wb.save(f)
    r = run(f.read_bytes())
    assert r["no_spec"] == ["Main row 3"] and r["wrong"] == [] and r["retried"] == []
    assert _where(r["no_spec_rows"][0]) == "Main row 3 (Rung 7)"
    main([str(f)])
    out = capsys.readouterr().out
    assert "NO SPEC (decompiler cannot express): Main row 3 (Rung 7)" in out and "WRONG" not in out
