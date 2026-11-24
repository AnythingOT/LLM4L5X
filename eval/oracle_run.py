"""Stand-in "always-correct" model: run a test workbook with each row answered by its expected rung.

    python -m eval.oracle_run LLM4L5X_test_seed3_v3.xlsx

Every answer is right by construction, so anything that goes wrong is the tool's fault: a check that
sends a correct answer back, a compile or simulation difference, a row the decompiler cannot express.
Run it after changing a check, the compiler or the simulator, before trusting a real-model score.
RETRIED must be 0; rows listed under NO SPEC are rows the decompiler cannot turn back into LogicSpec,
not tool failures (none known in generated workbooks).
"""

from __future__ import annotations

import argparse
import sys

from core.logicspec import format_spec
from core.rung import parse_rung
from eval.test_workbook import presets_of
from explain.decompiler import try_decompile
from gui import jobs, spec, state
from inputs.spec_excel import read_requirements


class Oracle:
    supports_grammar, url = False, "oracle"

    def __init__(self, answers: dict[str, str]):
        self.answers = answers

    def chat(self, messages, grammar=None, **kw):
        for m in reversed(messages):
            if m["content"] in self.answers:
                return self.answers[m["content"]]
        raise KeyError("request not found in the workbook")


def answers_of(sheets) -> tuple[dict[str, str], list[str]]:
    out, missing = {}, []
    for sh in sheets:
        for r in sh.rows:
            if r.request and r.expected:
                rungs = [parse_rung(t) for t in r.expected.splitlines() if t.strip()]
                pre = presets_of(rungs)
                stm = []
                for x in rungs:
                    s, _ = try_decompile(x, pre)
                    stm += s or []
                out[r.request] = format_spec(stm)
                if not out[r.request]:
                    missing.append(f"{sh.routine} row {r.line}")
    return out, missing


def run(data: bytes, revision: str = "37.00") -> dict:
    sheets = read_requirements(data)
    answers, missing = answers_of(sheets)
    oracle = Oracle(answers)
    saved = state.llm
    state.llm = lambda s: oracle
    try:
        job = jobs.Job("oracle", 99)
        out = spec._run(job, sheets, state.settings({"revision": revision}), "oracle")
    finally:
        state.llm = saved
    # a row with no answer is sent back by design (an empty reply): only a right answer sent back is a failure
    def unanswerable(e: dict) -> bool:
        return f"{e['sheet']} row {e['line']}" in missing

    retried = [e for e in job.events if e.get("attempts", 1) > 1 and not unanswerable(e)]
    # a NO SPEC row fails by design (it got an empty reply): list it once, under NO SPEC, not again as WRONG
    wrong = [e for e in job.events if (not e.get("ok") or not e.get("match", True)) and not unanswerable(e)]
    return {"matched": sum(e["matched"] for e in out["sheets"]), "expected": sum(e["expected"] for e in out["sheets"]),
            "sheets": [(e["routine"], e["matched"], e["expected"]) for e in out["sheets"]],
            "no_spec": missing, "no_spec_rows": [e for e in job.events if unanswerable(e)],
            "retried": retried, "wrong": wrong}


def _where(e: dict) -> str:
    """Excel row, as in Report.txt, with the workbook's own Rung number beside it."""
    return f"{e['sheet']} row {e['line']}" + (f" (Rung {e['ref']})" if e.get("ref") else "")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("workbook")
    a = ap.parse_args(argv)
    r = run(open(a.workbook, "rb").read())
    for name, m, n in r["sheets"]:
        print(f"{name}: {m}/{n}")
    for e in r["no_spec_rows"]:
        print("NO SPEC (decompiler cannot express):", _where(e))
    for e in r["wrong"]:
        print("  WRONG", _where(e), e.get("error") or e.get("match_why"))
    for e in r["retried"]:
        print("  RETRIED", _where(e), (e.get("retries") or [""])[0][:120])
    print(f"TOTAL {r['matched']}/{r['expected']}  RETRIED {len(r['retried'])}")
    return 1 if r["retried"] else 0


if __name__ == "__main__":
    sys.exit(main())
