"""The always-correct stand-in: no check may send a right answer back."""
from eval.oracle_run import run
from eval.test_workbook import build


def test_no_correct_answer_is_sent_back(tmp_path):
    f = tmp_path / "wb.xlsx"
    build(f, seed=3, rows=4)
    r = run(f.read_bytes())
    assert r["retried"] == [], [(e["sheet"], e["line"], e.get("retries")) for e in r["retried"]]
    assert r["expected"] > 0 and r["matched"] >= r["expected"] - len(r["no_spec"])
