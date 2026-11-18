"""Run the instruction suite and write a report.

    python cli.py suite --self-test                 # compiler vs reference, no model
    python cli.py suite --model phi4-mini --per 2   # English -> model -> rungs, scored
    python cli.py suite --model phi4-mini --excel suite_phi4.xlsx

Self-test: compiles each expected LogicSpec and checks the rungs behave like the
independently built reference rungs. This tests the compiler, and checks the
suite itself (every expected rung must validate and survive the neutral and
ASCII round trips).

Model run: asks the model for each English request with the case's tags offered
as project tags, then compares the resulting rungs' behaviour with the
reference. The old string EXACT is reported alongside for comparison.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass

from core.ascii import format_ascii, parse_ascii_rung
from core.compiler import CompileError, Compiler
from core.logicspec import SpecError, parse_spec
from core.rung import format_rung, parse_rung
from core.validator import errors, validate
from eval.rung_compare import Side, compare
from eval.suite import Case


@dataclass
class Outcome:
    case: Case
    got_spec: str | None
    got_rungs: list[str]
    ok: bool
    exact: bool
    reason: str
    attempts: int = 0
    seconds: float = 0.0
    replies: str = ""  # raw model replies, all attempts


def _check_case(case: Case, version: int) -> list[str]:
    """Problems with the suite's own expected answer (should be none)."""
    problems = []
    rungs = [parse_rung(t) for t in case.rungs]
    for t, r in zip(case.rungs, rungs):
        if format_rung(r) != t:
            problems.append(f"neutral round trip changed {t}")
        if format_rung(parse_ascii_rung(format_ascii(r))) != t:
            problems.append(f"ASCII round trip changed {t}")
    types = dict(case.tags)
    types.update({k: ("TIMER" if "TMR" in k else "COUNTER") for k in case.presets})
    types.update({f"REF_ONS_{i}": "BOOL" for i in range(1, 10)})
    for i in errors(validate(rungs, types, revision=f"{version}.00")):
        problems.append(f"expected rung invalid: {i.message}")
    return problems


def _presets(compiled) -> dict[str, int]:
    return {t.name: t.preset for t in compiled.tags.values() if t.preset is not None}


def self_test(cases: list[Case], version: int, progress=None) -> list[Outcome]:
    out = []
    for n, c in enumerate(cases, 1):
        problems = _check_case(c, version)
        try:
            res = Compiler(known_tags=c.tags, revision=f"{version}.00", comments=False).compile(parse_spec(c.spec))
            got = [format_rung(r) for r in res.rungs]
            ok, why = compare(Side([parse_rung(t) for t in c.rungs], c.presets), Side(res.rungs, _presets(res)),
                              seed=n)
        except (SpecError, CompileError) as e:
            got, ok, why = [], False, f"compile error: {e}"
        if problems:
            ok, why = False, "; ".join(problems)
        o = Outcome(c, c.spec, got, ok, got == c.rungs, why)
        out.append(o)
        if progress:
            progress(n, len(cases), o)
    return out


def model_run(cases: list[Case], client, version: int, progress=None) -> list[Outcome]:
    from inputs.llm import Generator
    gen = Generator(client)
    out = []
    for n, c in enumerate(cases, 1):
        t0 = time.perf_counter()
        r = gen.generate(c.english, known_tags=c.tags, compiler_kw={"revision": f"{version}.00", "comments": False})
        replies = "\n---\n".join(f"#{i + 1}: {a.reply.strip()}" + (f"\n  -> {a.error}" if a.error else "")
                                 for i, a in enumerate(r.attempts))
        if r.compiled is None:
            o = Outcome(c, None, [], False, False, r.error or "no answer", len(r.attempts),
                        round(time.perf_counter() - t0, 2), replies)
        else:
            got = [format_rung(x) for x in r.compiled.rungs]
            ok, why = compare(Side([parse_rung(t) for t in c.rungs], c.presets),
                              Side(r.compiled.rungs, _presets(r.compiled)), seed=n)
            o = Outcome(c, r.spec, got, ok, got == c.rungs, why, len(r.attempts), r.seconds, replies)
        out.append(o)
        if progress:
            progress(n, len(cases), o)
    return out


def summary(outcomes: list[Outcome], title: str) -> str:
    def rate(items):
        ok = sum(o.ok for o in items)
        return f"{ok:4d}/{len(items):<4d} {100 * ok / max(1, len(items)):5.1f}%"

    by_st, by_feat = defaultdict(list), defaultdict(list)
    for o in outcomes:
        by_st[o.case.structure].append(o)
        by_feat[o.case.feature].append(o)
    lines = [title,
             f"behaviour match: {rate(outcomes)}",
             f"text EXACT:      {sum(o.exact for o in outcomes):4d}/{len(outcomes):<4d} "
             f"(the old Excel method; equivalent answers count as wrong)"]
    secs = [o.seconds for o in outcomes if o.seconds]
    if secs:
        lines.append(f"time:            avg {sum(secs) / len(secs):.1f}s, max {max(secs):.1f}s per request")
    lines.append("\nby structure:")
    lines += [f"  {k:13s} {rate(v)}" for k, v in by_st.items()]
    lines.append("by instruction:")
    lines += [f"  {k:13s} {rate(v)}" for k, v in by_feat.items()]
    bad = [o for o in outcomes if not o.ok]
    if bad:
        lines.append(f"\nfirst failures ({min(len(bad), 8)} of {len(bad)}):")
        for o in bad[:8]:
            lines += [f"- {o.case.id}: {o.case.english}", f"    expected: {' | '.join(o.case.rungs)}",
                      f"    got:      {' | '.join(o.got_rungs) or '-'}", f"    why:      {o.reason}"]
    return "\n".join(lines)


def write_excel(outcomes: list[Outcome], path: str, title: str) -> None:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Results"
    head = ["ID", "Instruction", "Structure", "Question (English)", "Expected LogicSpec", "Expected rungs",
            "Got LogicSpec", "Got rungs", "Attempts", "Seconds", "Match (behaviour)", "EXACT (old)", "Why not",
            "Model replies (raw)"]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True)
    green, red = PatternFill("solid", start_color="C6EFCE"), PatternFill("solid", start_color="FFC7CE")
    for o in outcomes:
        ws.append([o.case.id, o.case.feature, o.case.structure, o.case.english, o.case.spec,
                   "\n".join(o.case.rungs), o.got_spec or "", "\n".join(o.got_rungs), o.attempts, o.seconds,
                   "TRUE" if o.ok else "FALSE", "TRUE" if o.exact else "FALSE", o.reason, o.replies])
        ws.cell(ws.max_row, 11).fill = green if o.ok else red
    widths = [20, 10, 12, 60, 45, 55, 45, 55, 9, 9, 10, 10, 60, 70]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    s = wb.create_sheet("Summary")
    for line in summary(outcomes, title).splitlines():
        s.append([line])
    s.column_dimensions["A"].width = 120
    wb.save(path)
