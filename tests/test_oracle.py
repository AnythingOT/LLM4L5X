"""The always-correct stand-in: no check may send a right answer back."""
from eval.oracle_run import run
from eval.test_workbook import build


def test_no_correct_answer_is_sent_back(tmp_path):
    f = tmp_path / "wb.xlsx"
    build(f, seed=5)  # seed 5 has a one-shot at the start of an OR leg (Parallel, rung 5)
    r = run(f.read_bytes())
    assert r["retried"] == [], [(e["sheet"], e["line"], e.get("retries")) for e in r["retried"]]
    # every generated row must decompile and match: a NO SPEC row would hide a regression of its shape
    assert r["no_spec"] == [] and r["wrong"] == []
    assert r["expected"] > 0 and r["matched"] == r["expected"]
