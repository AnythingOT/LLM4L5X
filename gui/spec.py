"""A requirements workbook -> one routine per sheet, row by row, in the background.

Each row goes through the same path as the chat box (the model, then the compiler and the
checks), or is read as rung text when the Rung text column is filled. Tags created by a row are
known to the rows below it. A row that fails is reported and left out; the rest still build.
"""

from __future__ import annotations

import base64
import io
import time
import zipfile
from dataclasses import replace

import lint
from core.ascii import AsciiSyntaxError, format_ascii
from core.compiler import CompileError, infer_tags
from core.rung import format_rung, is_literal, walk
from core.simulator import SimError
from core.validator import errors, validate
from eval.rung_compare import Side, compare
from explain.ladder import to_svg
from gui import jobs, state
from gui.logic import generate, parse_rung_text
from gui.state import SESSION
from inputs.llm import LLMError
from inputs.spec_excel import Sheet
from l5x.writer import write_routine


def start(sheets: list[Sheet], s: dict, filename: str) -> jobs.Job:
    total = sum(len(sh.rows) for sh in sheets)
    return jobs.start(total, lambda job: _run(job, sheets, s, filename))


def _run(job: jobs.Job, sheets: list[Sheet], s: dict, filename: str) -> dict:
    proj = SESSION.project
    project_types = dict(proj.tag_types(s["program"])) if proj else {}
    catalog = proj.catalog() if proj else None
    client = state.llm(s)
    built, report = [], [f"Requirements: {filename}", ""]
    for sheet in sheets:
        new_tags: dict = {}  # name -> TagDef, created by this sheet's rows
        rungs: list = []
        ok = failed = 0
        report.append(f"Routine {sheet.routine} (sheet {sheet.title})")
        for row in sheet.rows:
            if job.cancel.is_set():
                break
            with job.lock:
                job.label = f"{sheet.routine}: row {row.line}"
            ev = _row(client, row, s, project_types, new_tags, catalog)
            ev.update(sheet=sheet.routine, line=row.line, ref=row.ref, request=row.request or row.logic)
            if ev["ok"]:
                ok += 1
                if row.expected:
                    ev["match"], ev["match_why"] = _matches(row.expected, ev["_rungs"], {**new_tags, **ev["_tags"]}, catalog)
                for r in ev.pop("_rungs"):
                    rungs.append(r)
                    ev["rungs"].append({"text": format_rung(r), "ascii": format_ascii(r),
                                        "svg": to_svg(r, catalog, number=len(rungs) - 1)})
                new_tags.update(ev.pop("_tags"))
            else:
                failed += 1
                ev.pop("_rungs", None)
                ev.pop("_tags", None)
            ev["has_expected"] = bool(row.expected)
            verdict = ""
            if row.expected and ev["ok"]:
                verdict = ", matches expected" if ev["match"] else f", DIFFERS from expected: {ev['match_why']}"
            report.append(f"  row {row.line}{f' ({row.ref})' if row.ref else ''}: "
                          + ("ok, " + _n(len(ev["rungs"]), "rung") + verdict if ev["ok"] else f"FAILED: {ev['error']}"))
            with job.lock:
                job.events.append(ev)
                job.done += 1
        scored = [e for e in job.events if e.get("sheet") == sheet.routine and row_has_expected(e)]
        entry = {"routine": sheet.routine, "title": sheet.title, "ok": ok, "failed": failed, "rungs": len(rungs),
                 "tags": len(new_tags), "lint": [], "file": None,
                 "expected": len(scored), "matched": sum(1 for e in scored if e.get("match"))}
        if rungs:
            types = {**project_types, **{t.name: t.datatype for t in new_tags.values()}}
            # rules across rows: one timer used by two rows, one-shot storage shared ...
            entry["lint"] = [f.to_dict() for f in lint.check_rungs(rungs, types, catalog, disabled=s["disabled_rules"])]
            entry["file"] = f"{sheet.routine}.L5X"
            entry["_l5x"] = write_routine(rungs, list(new_tags.values()), routine=sheet.routine,
                                          controller=s["controller"], program=s["program"],
                                          revision=s["revision"], scope=s["scope"])
        report.append(f"  {_n(ok, 'row')} built, {failed} failed, {_n(len(rungs), 'rung')}, "
                      f"{_n(len(new_tags), 'new tag')}, {_n(len(entry['lint']), 'rule finding')}")
        if entry["expected"]:
            report.append(f"  test score: {entry['matched']} of {entry['expected']} rows behave as expected "
                          f"(rows not built count as wrong)")
        report.append("")
        built.append(entry)
        if job.cancel.is_set():
            report.append("Stopped before the end.")
            break
    files = {e["file"]: e.pop("_l5x") for e in built if e["file"]}
    out = {"kind": "spec_done", "filename": filename, "sheets": built, "cancelled": job.cancel.is_set()}
    if len(files) == 1 and not job.cancel.is_set() and all(e["failed"] == 0 for e in built):
        ((name, text),) = files.items()
        out.update(download=name, l5x=text)
    elif files:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, text in files.items():
                z.writestr(name, text.encode("utf-8"))
            z.writestr("Report.txt", "\r\n".join(report).encode("utf-8"))
        out.update(download="Routines.zip", zip_b64=base64.b64encode(buf.getvalue()).decode("ascii"))
    return out


def _row(client, row, s, project_types, new_tags, catalog) -> dict:
    """One row -> {ok, error, warnings, rungs: [], _rungs, _tags, seconds, spec}."""
    t0 = time.perf_counter()
    ev = {"ok": False, "error": None, "warnings": [], "rungs": [], "seconds": 0.0}
    known = {**project_types, **{t.name: t.datatype for t in new_tags.values()}}
    try:
        if row.logic:
            parsed = parse_rung_text(row.logic)
            if parsed is None:
                raise CompileError("Rung text is neither neutral (XIC(a)OTE(b);) nor ASCII (XIC a OTE b)")
            tags, warns = infer_tags(parsed, known, catalog)
            ev["warnings"] += warns
        else:
            r = generate(client, row.request, s, more_tags={t.name: t.datatype for t in new_tags.values()})
            ev["warnings"] += r.warnings
            ev["spec"] = r.spec
            if r.spec is None:
                raise CompileError(f"the model could not produce valid logic: {r.error}")
            parsed, tags = r.compiled.rungs, r.compiled.tags
            ev["warnings"] += r.compiled.warnings
    except (CompileError, AsciiSyntaxError, LLMError) as e:
        ev["error"] = str(e)
        return _done(ev, t0)
    clash = [f"{t.name} is {known[t.name]} above, {t.datatype} here" for t in tags.values()
             if t.name in known and known[t.name].upper() != t.datatype.upper()]
    if clash:
        ev["error"] = "tag type clash: " + "; ".join(clash)
        return _done(ev, t0)
    types = {**known, **{t.name: t.datatype for t in tags.values()}}
    issues = validate(parsed, types, catalog=catalog, revision=s["revision"])
    if errors(issues):
        ev["error"] = "; ".join(f"rung {i.rung + 1}: {i.message}" for i in errors(issues))
        return _done(ev, t0)
    comment = row.comment or (row.request if not row.logic else None)
    if comment:
        parsed = [replace(parsed[0], comment=comment), *parsed[1:]]
    ev.update(ok=True, _rungs=parsed, _tags={n: t for n, t in tags.items() if n not in project_types})
    return _done(ev, t0)


def row_has_expected(ev: dict) -> bool:
    return bool(ev.get("has_expected"))


def _presets(rungs, tags: dict) -> dict[str, int]:
    """Timer/counter presets: from the tags, and from literal operands (TON(T,5000,0))."""
    out = {t.name: int(t.preset) for t in tags.values() if getattr(t, "preset", None)}
    for r in rungs:
        for ins in walk(r.body):
            if ins.name.upper() in ("TON", "TOF", "RTO", "CTU", "CTD") and len(ins.args) > 1 and is_literal(ins.args[1]):
                out[ins.args[0]] = int(float(ins.args[1]))
    return out


def _matches(expected_text: str, got, tags: dict, catalog) -> tuple[bool, str]:
    """Does the built row behave like the expected rung text? Run both in the scan simulator."""
    want = parse_rung_text(expected_text)
    if want is None:
        return False, "the Expected cell is not valid rung text"
    try:
        return compare(Side(want, _presets(want, {})), Side(list(got), _presets(got, tags)), catalog=catalog)
    except SimError as e:
        return False, f"cannot simulate: {e}"


def _done(ev: dict, t0: float) -> dict:
    ev["seconds"] = round(time.perf_counter() - t0, 2)
    return ev


def _n(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"
