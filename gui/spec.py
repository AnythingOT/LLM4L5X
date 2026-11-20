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
from core.rung import base_tag, format_rung, is_literal, walk
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
    # every sheet goes into the same program, so tags made by one sheet are known to the next:
    # one Fill_Valve type, one L4X_ONS_1, not one per routine
    earlier: dict = {}  # name -> TagDef, created by the sheets above
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
            ev = _row(client, row, s, project_types, {**earlier, **new_tags}, catalog)
            ev.update(sheet=sheet.routine, line=row.line, ref=row.ref, request=row.request or row.logic)
            if ev["ok"]:
                ok += 1
                if row.expected:
                    ev["match"], ev["match_why"] = _matches(row.expected, ev["_rungs"],
                                                            {**earlier, **new_tags, **ev["_tags"]}, catalog)
                presets = {**(proj.presets() if proj else {}),
                           **{t.name: t.preset for t in {**earlier, **new_tags, **ev["_tags"]}.values()
                              if t.preset is not None}}
                for r in ev.pop("_rungs"):
                    rungs.append(r)
                    ev["rungs"].append({"text": format_rung(r), "ascii": format_ascii(r),
                                        "svg": to_svg(r, catalog, number=len(rungs) - 1, presets=presets)})
                new_tags.update(ev.pop("_tags"))
            else:
                failed += 1
                ev.pop("_rungs", None)
                ev.pop("_tags", None)
            ev["has_expected"] = bool(row.expected)
            verdict = ""
            if row.expected and ev["ok"]:
                verdict = ", matches expected" if ev["match"] else f", DIFFERS from expected: {ev['match_why']}"
            tries = f" ({ev['attempts']} attempts)" if ev.get("attempts", 1) > 1 else ""
            report.append(f"  row {row.line}{f' ({row.ref})' if row.ref else ''}: "
                          + ("ok, " + _n(len(ev["rungs"]), "rung") + verdict if ev["ok"] else f"FAILED: {ev['error']}")
                          + tries)
            report += [f"      sent back: {_short(e)}" for e in ev.get("retries", [])]
            report += [f"      warning: {w}" for w in ev["warnings"]]
            with job.lock:
                job.events.append(ev)
                job.done += 1
        scored = [e for e in job.events if e.get("sheet") == sheet.routine and row_has_expected(e)]
        entry = {"routine": sheet.routine, "title": sheet.title, "ok": ok, "failed": failed, "rungs": len(rungs),
                 "tags": len(new_tags), "lint": [], "file": None,
                 "expected": len(scored), "matched": sum(1 for e in scored if e.get("match"))}
        if rungs:
            types = {**project_types, **{t.name: t.datatype for t in {**earlier, **new_tags}.values()}}
            # rules across rows: one timer used by two rows, one-shot storage shared ...
            entry["lint"] = [f.to_dict() for f in lint.check_rungs(rungs, types, catalog, disabled=s["disabled_rules"])]
            entry["file"] = f"{sheet.routine}.L5X"
            # the routine carries its own new tags and those it uses from the sheets above
            used = {base_tag(a) for r in rungs for i in walk(r.body) for a in i.args if not is_literal(a)}
            carried = [t for n, t in earlier.items() if n in used and n not in new_tags]
            entry["_l5x"] = write_routine(rungs, carried + list(new_tags.values()), routine=sheet.routine,
                                          controller=s["controller"], program=s["program"],
                                          revision=s["revision"], scope=s["scope"])
        report.append(f"  {_n(ok, 'row')} built, {failed} failed, {_n(len(rungs), 'rung')}, "
                      f"{_n(len(new_tags), 'new tag')}, {_n(len(entry['lint']), 'rule finding')}")
        mine = [e for e in job.events if e.get("sheet") == sheet.routine and "attempts" in e]
        if mine:
            report.append("  " + _effort(mine))
        if entry["expected"]:
            report.append(f"  test score: {entry['matched']} of {entry['expected']} rows behave as expected "
                          f"(rows not built count as wrong)")
        report.append("")
        built.append(entry)
        earlier.update(new_tags)
        if job.cancel.is_set():
            report.append("Stopped before the end.")
            break
    scored_all = [e for e in job.events if row_has_expected(e)]
    by_model = [e for e in job.events if "attempts" in e]
    report.append("Total: " + (f"{sum(1 for e in scored_all if e.get('match'))} of {len(scored_all)} rows behave "
                               f"as expected; " if scored_all else "") + (_effort(by_model) if by_model else
                                                                         "no rows written by the model"))
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


def _short(text: str, n: int = 160) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 3] + "..."


def _effort(events) -> str:
    """How hard the model worked: a 100% score says nothing about the retries behind it."""
    tries = [e["attempts"] for e in events]
    extra = sum(t - 1 for t in tries)
    again = sum(1 for t in tries if t > 1)
    secs = sum(e.get("seconds", 0.0) for e in events)
    return (f"model: {_n(len(tries), 'row')}, {again} needed more than one attempt "
            f"({_n(extra, 'extra attempt')}), {secs:.0f} s")


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
            # a pass on the third try costs three times as long and is the first to fail on drift
            ev["attempts"] = len(r.attempts)
            ev["retries"] = [a.error for a in r.attempts if a.error]
            if r.spec is None:
                raise CompileError(f"the model could not produce valid logic: {r.error}")
            parsed, tags = r.compiled.rungs, r.compiled.tags
            ev["warnings"] += r.compiled.warnings
            # a timer or counter made by an earlier row has one preset; a row asking for another
            # cannot be met by the same tag, so say so instead of quietly keeping the old preset
            made = {t.name: t for t in new_tags.values()}
            for name, want in r.compiled.presets_asked.items():
                have = made.get(name)
                if have is not None and have.preset is not None and have.preset != want:
                    raise CompileError(f"{name} already exists with preset {have.preset} (made by an earlier row); "
                                       f"this row asks for {want}. One timer or counter has one preset: "
                                       f"give this row its own tag")
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
