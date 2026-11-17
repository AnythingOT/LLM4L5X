"""LLM4L5X local web GUI.

Run from the repo root:   python app.py
Then open:                 http://127.0.0.1:5000

Single-user local tool: the attached project lives in memory and is
forgotten when the server stops. Nothing is sent anywhere.
"""

from __future__ import annotations

import re
import time

from flask import Flask, jsonify, render_template, request

from core.catalog import major_version
from core.compiler import CompileError, Compiler
from core.logicspec import SpecError, format_spec, parse_spec
from core.rung import RungSyntaxError, format_rung, parse_rung
from core.validator import errors, validate
from explain.decompiler import try_decompile
from explain.describe import describe_statement
from l5x.reader import Project, read_l5x
from l5x.writer import write_routine, write_rungs
from l5x.xref import cross_reference

app = Flask(__name__, template_folder="gui/templates", static_folder="gui/static")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB L5X upload limit

STATE: dict = {"project": None, "filename": None}

DEFAULTS = {
    "output": "rungs",          # rungs | routine
    "routine": "GeneratedRoutine",
    "program": "MainProgram",
    "controller": "LLM4L5X",
    "revision": "32.04",
    "scope": "controller",      # controller | program
    "display": "placeholder",   # placeholder | values
    "comments": True,
    "prefix": "L4X",
}


def _settings(raw: dict | None) -> dict:
    s = dict(DEFAULTS)
    for k, v in (raw or {}).items():
        if k in s and v not in (None, ""):
            s[k] = v
    if s["output"] not in ("rungs", "routine"):
        s["output"] = "rungs"
    if s["scope"] not in ("controller", "program"):
        s["scope"] = "controller"
    if s["display"] not in ("placeholder", "values"):
        s["display"] = "placeholder"
    s["comments"] = bool(s["comments"])
    return s


def _project() -> Project | None:
    return STATE["project"]


def _issues_json(issues):
    return [{"level": i.level, "rung": i.rung, "message": i.message} for i in issues]


# ---------------------------------------------------------------- pages


@app.get("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------- chat input


@app.post("/api/process")
def process():
    """One endpoint for the chat box: a command, LogicSpec, or rung text."""
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    s = _settings(data.get("settings"))
    t0 = time.perf_counter()
    if not text:
        return jsonify(kind="error", message="Nothing to process.")

    cmd = text.split(None, 1)
    head = cmd[0].lower()
    if head in ("help", "?"):
        out = {"kind": "help"}
    elif head == "xref":
        out = _xref(cmd[1].strip() if len(cmd) > 1 else "")
    elif head in ("decompile", "validate", "summary") and len(cmd) == 1:
        out = _project_action(head)
    else:
        out = _logicspec_or_rung(text, s)
    out["seconds"] = round(time.perf_counter() - t0, 3)
    return jsonify(out)


def _logicspec_or_rung(text: str, s: dict) -> dict:
    try:
        stmts = parse_spec(text)
    except SpecError as spec_err:
        rung_out = _try_rungs(text)
        if rung_out:
            return rung_out
        return {"kind": "error", "message": f"Not valid LogicSpec: {spec_err}",
                "hint": "Type 'help' for the LogicSpec syntax, or paste rung text like XIC(a)OTE(b);"}
    return _compile(stmts, s)


def _compile(stmts, s: dict) -> dict:
    proj = _project()
    program = s["program"]
    known = proj.tag_types(program) if proj else None
    catalog = proj.catalog() if proj else None
    try:
        res = Compiler(known_tags=known, prefix=s["prefix"], display_operands=s["display"],
                       comments=s["comments"], catalog=catalog, revision=s["revision"]).compile(stmts)
    except CompileError as e:
        return {"kind": "error", "message": str(e)}
    types = dict(known or {})
    types.update({t.name: t.datatype for t in res.tags.values()})
    issues = validate(res.rungs, types if proj else None, catalog=catalog, revision=s["revision"])
    out = {
        "kind": "compiled",
        "readback": [describe_statement(st) for st in res.statements],
        "rungs": [{"text": format_rung(r), "comment": r.comment} for r in res.rungs],
        "tags": [{"name": t.name, "type": t.datatype, "preset": t.preset,
                  "auto": t.allocated} for t in res.tags.values()],
        "warnings": res.warnings,
        "issues": _issues_json(issues),
        "used_project": STATE["filename"],
        "l5x": None,
    }
    if not errors(issues):
        kw = dict(controller=s["controller"], program=program, revision=s["revision"], scope=s["scope"])
        if s["output"] == "routine":
            out["l5x"] = write_routine(res.rungs, res.tags.values(), routine=s["routine"], **kw)
            out["filename"] = f"{_safe(s['routine'])}_Routine.L5X"
        else:
            out["l5x"] = write_rungs(res.rungs, res.tags.values(), **kw)
            out["filename"] = f"{_safe(s['routine'])}_Rungs.L5X"
    return out


def _try_rungs(text: str) -> dict | None:
    """Rung text, one rung per ';'. Returns None if it does not look like rungs."""
    if "(" not in text or ";" not in text:
        return None
    parts = [p.strip() + ";" for p in text.split(";") if p.strip()]
    rungs = []
    try:
        parsed = [parse_rung(p) for p in parts]
    except RungSyntaxError:
        return None
    proj = _project()
    presets = proj.presets() if proj else {}
    for r in parsed:
        stmts, why = try_decompile(r, presets)
        rungs.append({
            "text": format_rung(r),
            "logicspec": format_spec(stmts) if stmts else None,
            "english": [describe_statement(x) for x in stmts] if stmts else [],
            "why": why,
        })
    catalog = proj.catalog() if proj else None
    all_tags = {t.name: t.datatype for t in proj.tags.values()} if proj else None
    issues = validate(parsed, all_tags, catalog=catalog, revision=proj.software_revision if proj else None)
    return {"kind": "rungs", "rungs": rungs, "issues": _issues_json(issues)}


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name) or "Generated"


# ---------------------------------------------------------------- project


def _summary(p: Project) -> dict:
    routines = [{"program": r.program, "name": r.name, "type": r.type, "rungs": len(r.rungs),
                 "unparsed": sum(1 for x in r.rungs if x.rung is None)} for r in p.routines]
    programs = sorted({r.program for r in p.routines})
    return {
        "kind": "project",
        "filename": STATE["filename"],
        "controller": p.controller,
        "revision": p.software_revision,
        "target": p.target_type,
        "tags": len(p.tags),
        "udts": sorted(p.udts),
        "aois": sorted(p.aois),
        "programs": programs,
        "routines": routines,
        "revision_major": major_version(p.software_revision),
    }


@app.post("/api/project")
def attach_project():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(kind="error", message="No file received.")
    if not f.filename.lower().endswith(".l5x"):
        return jsonify(kind="error", message="Attach an .L5X export from Studio 5000.")
    try:
        p = read_l5x(f.read())
    except Exception as e:  # lxml / format errors -> show the user, keep running
        return jsonify(kind="error", message=f"Could not read {f.filename}: {e}")
    STATE["project"], STATE["filename"] = p, f.filename
    return jsonify(_summary(p))


@app.delete("/api/project")
def detach_project():
    STATE["project"], STATE["filename"] = None, None
    return jsonify(kind="info", message="Project detached. New tags will no longer be checked against it.")


def _project_action(action: str) -> dict:
    p = _project()
    if p is None:
        return {"kind": "error", "message": f"'{action}' needs an attached L5X. Use Attach first."}
    if action == "summary":
        return _summary(p)
    if action == "decompile":
        presets = p.presets()
        rows, ok = [], 0
        for rt in p.routines:
            for x in rt.rungs:
                row = {"where": f"{rt.program}/{rt.name} rung {x.number}", "text": x.text}
                if x.rung is None:
                    row["why"] = f"parse error: {x.parse_error}"
                else:
                    stmts, why = try_decompile(x.rung, presets)
                    if stmts:
                        ok += 1
                        row["logicspec"] = format_spec(stmts)
                    else:
                        row["why"] = why
                rows.append(row)
        return {"kind": "decompiled", "rows": rows, "ok": ok, "total": len(rows)}
    # validate
    cat = p.catalog()
    rows = []
    for rt in p.routines:
        good = []
        for x in rt.rungs:
            if x.rung is None:
                rows.append({"where": f"{rt.program}/{rt.name} rung {x.number}", "level": "error",
                             "message": f"parse error: {x.parse_error}"})
            else:
                good.append(x.rung)
        for i in validate(good, p.tag_types(rt.program), catalog=cat, revision=p.software_revision):
            rows.append({"where": f"{rt.program}/{rt.name} rung {i.rung}", "level": i.level, "message": i.message})
    return {"kind": "validated", "rows": rows}


def _xref(tag: str) -> dict:
    p = _project()
    if p is None:
        return {"kind": "error", "message": "'xref' needs an attached L5X. Use Attach first."}
    if not tag:
        return {"kind": "error", "message": "Usage: xref TagName"}
    refs = cross_reference(p).get(tag, [])
    return {"kind": "xref", "tag": tag, "refs": [
        {"where": f"{r.program}/{r.routine} rung {r.rung}", "instruction": r.instruction,
         "operand": r.operand, "role": r.role} for r in refs]}


@app.get("/api/status")
def status():
    p = _project()
    return jsonify(project=STATE["filename"], programs=sorted({r.program for r in p.routines}) if p else [])


if __name__ == "__main__":
    # 127.0.0.1 = reachable only from this PC
    app.run(host="127.0.0.1", port=5000, debug=False)
