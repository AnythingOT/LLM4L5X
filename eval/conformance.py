"""Does our simulator behave like the controller? The same small programs, on both, step by step.

Each case is a few rungs with their own tags, and steps: write some inputs, wait, record some tags. The
cases run on our simulator and on Logix Emulate (through pylogix); every recorded value is compared.
A difference is a simulator bug to fix, or a documented limit. This is the simulator's validation record.

On the PC with Emulate:
  1. python -m eval.conformance --l5x Conformance.L5X --revision 33   (your Studio 5000 version)
  2. In Studio 5000, in the Emulate project's MainProgram: Import Routine, choose Conformance.L5X
     (it brings its tags), and add a rung JSR(LLM4L5X_Conformance,0) to MainRoutine. Download, Run.
  3. python -m eval.conformance --emulate 127.0.0.1 --slot 2 --report conformance_report.md
     (slot: the Emulate controller's slot in RSLinx / the chassis monitor). Takes about two minutes.
Send conformance_report.md back; its results go into tests/TEST_STATUS.md.

Without Emulate (in CI):  python -m eval.conformance --sim   runs the cases on the simulator only.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.compiler import TagDef
from core.rung import parse_rung
from core.simulator import _V36
from testcases.backend import SimBackend

ROUTINE = "LLM4L5X_Conformance"
TIME_TOLERANCE_MS = 150.0  # timer accumulators on Emulate: polling and scan time blur the edges


@dataclass
class Step:
    writes: dict
    wait_ms: float
    record: list[str]


@dataclass
class Case:
    name: str
    covers: str
    rungs: list[str]
    tags: dict[str, tuple[str, object]]  # name -> (data type, initial value or preset)
    steps: list[Step]
    timing: set[str] = field(default_factory=set)  # recorded tags compared with TIME_TOLERANCE_MS


def _seq(inputs: str, values: list, record: list[str], wait: float = 100.0) -> list[Step]:
    return [Step({inputs: v}, wait, record) for v in values]


CASES = [
    Case("bits", "XIC XIO OTE", ["XIC(CF_A)XIO(CF_B)OTE(CF_Q);"],
         {"CF_A": ("BOOL", 0), "CF_B": ("BOOL", 0), "CF_Q": ("BOOL", 0)},
         [Step({"CF_A": a, "CF_B": b}, 100, ["CF_Q"]) for a, b in ((0, 0), (1, 0), (1, 1), (0, 1))]),
    Case("latch", "OTL OTU, both true in one scan", ["XIC(CL_Set)OTL(CL_Q);", "XIC(CL_Rst)OTU(CL_Q);"],
         {"CL_Set": ("BOOL", 0), "CL_Rst": ("BOOL", 0), "CL_Q": ("BOOL", 0)},
         [Step({"CL_Set": 1}, 100, ["CL_Q"]), Step({"CL_Set": 0}, 100, ["CL_Q"]),
          Step({"CL_Set": 1, "CL_Rst": 1}, 100, ["CL_Q"]), Step({"CL_Rst": 0}, 100, ["CL_Q"]),
          Step({"CL_Set": 0, "CL_Rst": 1}, 100, ["CL_Q"])]),
    Case("edges", "ONS OSR OSF (counted, a one-scan pulse cannot be polled)",
         ["XIC(CE_In)ONS(CE_S1)ADD(CE_N1,1,CE_N1);", "XIC(CE_In)OSR(CE_S2,CE_Up);",
          "XIC(CE_Up)ADD(CE_N2,1,CE_N2);", "XIC(CE_In)OSF(CE_S3,CE_Dn);", "XIC(CE_Dn)ADD(CE_N3,1,CE_N3);"],
         {"CE_In": ("BOOL", 0), "CE_S1": ("BOOL", 0), "CE_S2": ("BOOL", 0), "CE_S3": ("BOOL", 0),
          "CE_Up": ("BOOL", 0), "CE_Dn": ("BOOL", 0), "CE_N1": ("DINT", 0), "CE_N2": ("DINT", 0), "CE_N3": ("DINT", 0)},
         _seq("CE_In", [1, 0, 1, 1, 0], ["CE_N1", "CE_N2", "CE_N3"])),
    Case("ton", "TON", ["XIC(CT_In)TON(CT_T,?,?);"], {"CT_In": ("BOOL", 0), "CT_T": ("TIMER", 1000)},
         [Step({"CT_In": 1}, 400, ["CT_T.EN", "CT_T.TT", "CT_T.DN", "CT_T.ACC"]),
          Step({}, 1000, ["CT_T.EN", "CT_T.TT", "CT_T.DN", "CT_T.ACC"]),
          Step({"CT_In": 0}, 100, ["CT_T.EN", "CT_T.TT", "CT_T.DN", "CT_T.ACC"])], {"CT_T.ACC"}),
    Case("tof", "TOF", ["XIC(CO_In)TOF(CO_T,?,?);"], {"CO_In": ("BOOL", 0), "CO_T": ("TIMER", 1000)},
         [Step({"CO_In": 1}, 100, ["CO_T.EN", "CO_T.TT", "CO_T.DN", "CO_T.ACC"]),
          Step({"CO_In": 0}, 400, ["CO_T.EN", "CO_T.TT", "CO_T.DN", "CO_T.ACC"]),
          Step({}, 1000, ["CO_T.EN", "CO_T.TT", "CO_T.DN", "CO_T.ACC"])], {"CO_T.ACC"}),
    Case("rto", "RTO RES", ["XIC(CR_In)RTO(CR_T,?,?);", "XIC(CR_Rst)RES(CR_T);"],
         {"CR_In": ("BOOL", 0), "CR_Rst": ("BOOL", 0), "CR_T": ("TIMER", 1000)},
         [Step({"CR_In": 1}, 400, ["CR_T.DN", "CR_T.ACC"]), Step({"CR_In": 0}, 300, ["CR_T.DN", "CR_T.ACC"]),
          Step({"CR_In": 1}, 900, ["CR_T.DN", "CR_T.ACC"]), Step({"CR_In": 0, "CR_Rst": 1}, 100, ["CR_T.DN", "CR_T.ACC"])],
         {"CR_T.ACC"}),
    Case("counters", "CTU CTD, done, overflow and underflow bits",
         ["XIC(CC_Up)CTU(CC_C,?,?);", "XIC(CC_Dn)CTD(CC_C,?,?);"],
         {"CC_Up": ("BOOL", 0), "CC_Dn": ("BOOL", 0), "CC_C": ("COUNTER", 2)},
         [Step({"CC_Up": v}, 100, ["CC_C.ACC", "CC_C.DN", "CC_C.CU"]) for v in (1, 0, 1, 0, 1)]
         + [Step({"CC_Dn": v}, 100, ["CC_C.ACC", "CC_C.DN", "CC_C.OV", "CC_C.UN"]) for v in (1, 0, 1, 0, 1, 0, 1, 0, 1)]),
    Case("compare", "EQU NEQ GRT LES GEQ LEQ LIM (also inverted limits), DINT and REAL",
         ["EQU(CM_A,CM_B)OTE(CM_Eq);", "NEQ(CM_A,CM_B)OTE(CM_Ne);", "GRT(CM_A,CM_B)OTE(CM_Gt);",
          "LES(CM_A,CM_B)OTE(CM_Lt);", "GEQ(CM_A,CM_R)OTE(CM_Ge);", "LEQ(CM_A,CM_R)OTE(CM_Le);",
          "LIM(10,CM_A,20)OTE(CM_In);", "LIM(20,CM_A,10)OTE(CM_Out);"],
         {"CM_A": ("DINT", 0), "CM_B": ("DINT", 0), "CM_R": ("REAL", 0.0), **{f"CM_{x}": ("BOOL", 0) for x in
                                                                             ("Eq", "Ne", "Gt", "Lt", "Ge", "Le", "In", "Out")}},
         [Step({"CM_A": a, "CM_B": b, "CM_R": r}, 100, [f"CM_{x}" for x in ("Eq", "Ne", "Gt", "Lt", "Ge", "Le", "In", "Out")])
          for a, b, r in ((5, 5, 5.0), (15, 5, 15.5), (25, 30, 24.9), (10, 11, 10.0), (20, 20, 20.0))]),
    Case("math", "ADD SUB MUL DIV MOV: integer division, REAL to DINT rounding",
         ["ADD(CA_X,CA_Y,CA_Add);", "SUB(CA_X,CA_Y,CA_Sub);", "MUL(CA_X,CA_Y,CA_Mul);", "DIV(CA_X,CA_Y,CA_Div);",
          "DIV(CA_X,CA_Y,CA_DivR);", "MOV(CA_R,CA_Round);", "MUL(CA_R,2,CA_Dbl);"],
         {"CA_X": ("DINT", 0), "CA_Y": ("DINT", 1), "CA_R": ("REAL", 0.0), "CA_Add": ("DINT", 0), "CA_Sub": ("DINT", 0),
          "CA_Mul": ("DINT", 0), "CA_Div": ("DINT", 0), "CA_DivR": ("REAL", 0.0), "CA_Round": ("DINT", 0), "CA_Dbl": ("REAL", 0.0)},
         [Step({"CA_X": x, "CA_Y": y, "CA_R": r}, 100, ["CA_Add", "CA_Sub", "CA_Mul", "CA_Div", "CA_DivR", "CA_Round", "CA_Dbl"])
          for x, y, r in ((7, 2, 2.5), (-7, 2, 3.5), (9, 4, -2.5), (100, 7, 7.6), (1, 3, -0.4))]),
    Case("cpt", "CPT precedence, MOD, **, functions, a REAL expression into a DINT",
         ["CPT(CX_D1,CX_A+CX_B*3);", "CPT(CX_D2,(CX_A+CX_B)*3);", "CPT(CX_D3,CX_A MOD CX_B);", "CPT(CX_D4,CX_A/CX_B);",
          "CPT(CX_R1,CX_A**2);", "CPT(CX_D5,CX_A/2.0);", "CPT(CX_R2,SQR(ABS(CX_A)));", "CPT(CX_D6,CX_A AND 6);"],
         {"CX_A": ("DINT", 0), "CX_B": ("DINT", 1), **{f"CX_D{k}": ("DINT", 0) for k in range(1, 7)},
          "CX_R1": ("REAL", 0.0), "CX_R2": ("REAL", 0.0)},
         [Step({"CX_A": a, "CX_B": b}, 100, [f"CX_D{k}" for k in range(1, 7)] + ["CX_R1", "CX_R2"])
          for a, b in ((7, 2), (-7, 2), (9, 4), (5, 3))]),
    Case("cmp", "CMP expressions", ["CMP(CP_A*2>CP_B)OTE(CP_Q1);", "CMP(CP_A=CP_B AND CP_A>0)OTE(CP_Q2);"],
         {"CP_A": ("DINT", 0), "CP_B": ("DINT", 0), "CP_Q1": ("BOOL", 0), "CP_Q2": ("BOOL", 0)},
         [Step({"CP_A": a, "CP_B": b}, 100, ["CP_Q1", "CP_Q2"]) for a, b in ((3, 5), (3, 6), (4, 4), (0, 0))]),
    Case("branches", "parallel legs, nested, an output inside a branch",
         ["[XIC(CB_A) ,XIC(CB_B) [XIC(CB_C) ,XIO(CB_D) ] ]OTE(CB_Q);", "XIC(CB_A)[OTE(CB_P) ,XIC(CB_B) OTE(CB_R) ];"],
         {**{f"CB_{x}": ("BOOL", 0) for x in "ABCDQPR"}},
         [Step({"CB_A": a, "CB_B": b, "CB_C": c, "CB_D": d}, 100, ["CB_Q", "CB_P", "CB_R"])
          for a, b, c, d in ((0, 0, 0, 0), (0, 1, 0, 0), (0, 1, 0, 1), (0, 1, 1, 1), (1, 0, 0, 0), (1, 1, 0, 0))]),
]


# ------------------------------------------------------------------ running


def _initial(case: Case) -> dict:
    """What every tag of a case is set to before it runs: inputs and results back to their start values."""
    out = {}
    for name, (dtype, v) in case.tags.items():
        if dtype in ("TIMER", "COUNTER"):
            out[f"{name}.PRE"] = v
            for m in ("ACC", "DN", "EN", "TT", "CU", "CD", "OV", "UN") if dtype == "COUNTER" else ("ACC", "DN", "EN", "TT"):
                out[f"{name}.{m}"] = 0
        else:
            out[name] = v
    return out


def run_case(case: Case, backend) -> list[list[object]]:
    for tag, v in _initial(case).items():
        backend.write(tag, v)
    backend.advance(100)
    seen = []
    for st in case.steps:
        for tag, v in st.writes.items():
            backend.write(tag, v)
        backend.advance(st.wait_ms)
        seen.append([backend.read(t) for t in st.record])
    return seen


def sim_backend(case: Case) -> SimBackend:
    rungs = [parse_rung(t) for t in case.rungs]
    types = {n: d for n, (d, _) in case.tags.items()}
    return SimBackend(rungs, _initial(case), None, 1.0, types=types)  # 1 ms scans: as close to a fast continuous task as useful


def run_all(make_backend) -> dict:
    return {c.name: run_case(c, make_backend(c)) for c in CASES}


def _same(tag: str, a, b, case: Case) -> bool:
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    if tag in case.timing:
        return abs(float(a) - float(b)) <= TIME_TOLERANCE_MS
    if isinstance(a, float) or isinstance(b, float):
        return math.isclose(float(a), float(b), rel_tol=1e-6, abs_tol=1e-6)
    return int(a) == int(b)


def compare(sim: dict, real: dict) -> list[dict]:
    """One row per case: how many values agree, and each difference with its step."""
    rows = []
    for c in CASES:
        diffs, total = [], 0
        for k, (st, a_vals, b_vals) in enumerate(zip(c.steps, sim.get(c.name, []), real.get(c.name, []))):
            for tag, a, b in zip(st.record, a_vals, b_vals):
                total += 1
                if not _same(tag, a, b, c):
                    diffs.append({"step": k + 1, "tag": tag, "simulator": a, "emulate": b})
        rows.append({"case": c.name, "covers": c.covers, "values": total, "differ": len(diffs), "diffs": diffs})
    return rows


def report(rows: list[dict], where: str) -> str:
    same = sum(r["values"] - r["differ"] for r in rows)
    total = sum(r["values"] for r in rows)
    lines = [f"# Simulator conformance: {where}", "",
             f"{same} of {total} recorded values agree ({len(CASES)} cases; timer accumulators within "
             f"{TIME_TOLERANCE_MS:.0f} ms).", "", "| Case | Covers | Values | Differ |", "|---|---|---|---|"]
    lines += [f"| {r['case']} | {r['covers']} | {r['values']} | {r['differ']} |" for r in rows]
    for r in rows:
        for d in r["diffs"]:
            lines.append(f"- {r['case']} step {d['step']}: {d['tag']} simulator {d['simulator']!r}, emulate {d['emulate']!r}")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ the routine to import


def routine_l5x(revision: str = "33.00") -> str:
    from l5x.writer import write_routine
    major = int(float(revision))
    new_names = {v: k for k, v in _V36.items()} if major >= 36 else {}  # v36 and later: EQ, MOVE ...
    rungs = []
    for c in CASES:
        for t in c.rungs:
            for old, new in new_names.items():
                t = re.sub(rf"\b{old}\(", f"{new}(", t)
            rungs.append(parse_rung(t))
    tags = []
    for c in CASES:
        for name, (dtype, v) in c.tags.items():
            tags.append(TagDef(name, dtype, preset=int(v) if dtype in ("TIMER", "COUNTER") else None,
                               description=f"conformance case {c.name}"))
    return write_routine(rungs, tags, routine=ROUTINE, revision=f"{major}.00")


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare the simulator with Logix Emulate, instruction by instruction.")
    ap.add_argument("--l5x", type=Path, help="write the routine to import into the Emulate project")
    ap.add_argument("--revision", default="33", help="Studio 5000 major version for --l5x (default 33)")
    ap.add_argument("--sim", action="store_true", help="run the cases on the simulator only")
    ap.add_argument("--emulate", metavar="IP", help="run on Logix Emulate at this address and compare")
    ap.add_argument("--slot", type=int, default=2, help="the Emulate controller's slot (default 2)")
    ap.add_argument("--report", type=Path, default=Path("conformance_report.md"))
    a = ap.parse_args()
    if a.l5x:
        a.l5x.write_text(routine_l5x(a.revision), encoding="utf-8")
        print(f"{a.l5x}: routine {ROUTINE} with {sum(len(c.rungs) for c in CASES)} rungs. Import it, JSR it, download, run.")
    sim = run_all(sim_backend) if (a.sim or a.emulate) else None
    if a.sim and not a.emulate:
        print(json.dumps(sim, indent=1))
    if a.emulate:
        from testcases.emulate import EmulateBackend
        be = EmulateBackend(a.emulate, a.slot)
        try:
            missing = [t for c in CASES for t in c.tags if not be.has(t)]
            if missing:
                raise SystemExit(f"Emulate does not have {len(missing)} of the tags (first: {missing[0]}). "
                                 f"Import {ROUTINE} and download first.")
            real = run_all(lambda c: be)
        finally:
            be.close()
        text = report(compare(sim, real), f"Logix Emulate at {a.emulate}, slot {a.slot}")
        a.report.write_text(text, encoding="utf-8")
        print(text)


if __name__ == "__main__":
    main()
