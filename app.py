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
from core.ascii import AsciiSyntaxError, format_ascii, looks_like_ascii, parse_ascii
from core.compiler import CompileError, Compiler, infer_tags
from core.logicspec import SpecError, format_spec, parse_spec
from core.rung import RungSyntaxError, format_rung, parse_rung
from core.validator import errors, validate, validate_project
from explain.decompiler import try_decompile
from explain.describe import describe_statement
from l5x.reader import Project, read_l5x
from l5x.writer import write_routine, write_rungs
from l5x.xref import cross_reference
import lint

app = Flask(__name__, template_folder="gui/templates", static_folder="gui/static")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB L5X upload limit

STATE: dict = {"project": None, "filename": None}

DEFAULTS = {
    "output": "routine",        # routine (Routine.L5X) | rungs (Rung.L5X)
    "routine": "GeneratedRoutine",
    "program": "MainProgram",
    "controller": "LLM4L5X",
    "revision": "32.04",
    "scope": "controller",      # controller | program
    "display": "placeholder",   # placeholder | values
    "comments": True,
    "prefix": "L4X",
    "backend": "ollama",        # ollama | llamacpp | openai
    "llm_url": "",              # empty = the backend's usual local address
    "model": "phi4-mini",
    "think": "default",         # default | off
    "rung_format": "neutral",   # neutral | ascii: how rungs are shown and copied
    "disabled_rules": [],       # lint rule codes switched off on the Rules page
}


def _settings(raw: dict | None) -> dict:
    s = dict(DEFAULTS)
    for k, v in (raw or {}).items():
        if k in s and v not in (None, ""):
            s[k] = v
    if s["output"] not in ("rungs", "routine"):
        s["output"] = "routine"
    if s["scope"] not in ("controller", "program"):
        s["scope"] = "controller"
    if s["display"] not in ("placeholder", "values"):
        s["display"] = "placeholder"
    s["comments"] = bool(s["comments"])
    if s["think"] not in ("default", "off"):
        s["think"] = "default"
    if s["backend"] not in ("ollama", "llamacpp", "openai"):
        s["backend"] = "ollama"
    if s["rung_format"] not in ("neutral", "ascii"):
        s["rung_format"] = "neutral"
    raw_rules = (raw or {}).get("disabled_rules") or []
    s["disabled_rules"] = sorted({str(c).upper() for c in raw_rules if str(c).upper() in lint.BY_CODE}) \
        if isinstance(raw_rules, list) else []
    if not s["llm_url"] and (raw or {}).get("ollama") and s["backend"] == "ollama":
        s["llm_url"] = raw["ollama"]  # settings saved by the previous version
    return s


def _llm(s: dict):
    from inputs.llm import make_client
    return make_client(s["backend"], s["llm_url"] or None, s["model"],
                       think=False if s["think"] == "off" else None)


def _project() -> Project | None:
    return STATE["project"]


def _issues_json(issues):
    return [{"level": i.level, "rung": i.rung, "message": i.message} for i in issues]


def _lint_json(rungs, types, catalog, s: dict) -> list[dict]:
    """Rung rules on new or pasted rungs (the project rules need the whole project)."""
    return [f.to_dict() for f in lint.check_rungs(rungs, types, catalog, disabled=s["disabled_rules"])]


def _l5x(out: dict, rungs, tags, s: dict) -> None:
    """Attach the download: a routine or rung export, as chosen in Settings."""
    kw = dict(controller=s["controller"], program=s["program"], revision=s["revision"], scope=s["scope"])
    if s["output"] == "routine":
        out["l5x"] = write_routine(rungs, tags, routine=s["routine"], **kw)
        out["filename"] = "Routine.L5X"
    else:
        out["l5x"] = write_rungs(rungs, tags, **kw)
        out["filename"] = "Rung.L5X"


# ---------------------------------------------------------------- pages


@app.get("/")
def index():
    return render_template("index.html", page="chat")


@app.get("/settings")
def settings_page():
    return render_template("settings.html", page="settings")


@app.get("/rules")
def rules_page():
    return render_template("rules.html", page="rules")


@app.get("/api/rules")
def rules_list():
    return jsonify(rules=[{"code": r.code, "title": r.title, "description": r.description, "severity": r.severity,
                           "scope": r.scope, "group": r.group} for r in lint.RULES])


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
        out = _project_action(head, s)
    else:
        out = _logicspec_or_rung(text, s)
    out["seconds"] = round(time.perf_counter() - t0, 3)
    return jsonify(out)


def _logicspec_or_rung(text: str, s: dict) -> dict:
    try:
        stmts = parse_spec(text)
    except SpecError as spec_err:
        proj = _project()
        catalog = proj.catalog() if proj else None
        if looks_like_ascii(text, catalog):
            try:
                return _explain_rungs(parse_ascii(text, catalog), source="ASCII", s=s)
            except AsciiSyntaxError as e:
                return {"kind": "error", "message": f"Not valid ASCII rung text: {e}"}
        rung_out = _try_rungs(text, s)
        if rung_out:
            return rung_out
        if _looks_like_logicspec(text):
            return {"kind": "error", "message": f"Not valid LogicSpec: {spec_err}",
                    "hint": "Type 'help' for the syntax, or describe the logic in plain English."}
        return _english(text, s)
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
    issues = validate(res.rungs, types if proj else None, catalog=catalog, revision=s["revision"],
                      string_types=proj.string_types if proj else None)
    out = {
        "kind": "compiled",
        "readback": [describe_statement(st) for st in res.statements],
        "rungs": [{"text": format_rung(r), "ascii": format_ascii(r), "comment": r.comment} for r in res.rungs],
        "tags": [{"name": t.name, "type": t.datatype, "preset": t.preset,
                  "auto": t.allocated} for t in res.tags.values()],
        "warnings": res.warnings,
        "issues": _issues_json(issues),
        "lint": _lint_json(res.rungs, types, catalog, s),
        "used_project": STATE["filename"],
        "l5x": None,
    }
    if not errors(issues):
        _l5x(out, res.rungs, res.tags.values(), s)
    return out


def _looks_like_logicspec(text: str) -> bool:
    """Someone typing LogicSpec (with a mistake) rather than English."""
    return bool(re.search(r":=|^\s*IF\b.*\bTHEN\b", text, flags=re.I | re.M)) and text.rstrip().endswith(";")


def _english(text: str, s: dict) -> dict:
    """Plain English -> local model -> LogicSpec -> compiled, checked rungs."""
    from inputs.llm import BACKENDS, Generator, LLMError
    proj = _project()
    client = _llm(s)
    try:
        r = Generator(client).generate(
            text,
            known_tags=proj.tag_types(s["program"]) if proj else None,
            descriptions=proj.tag_descriptions(s["program"]) if proj else None,
            catalog=proj.catalog() if proj else None,
            compiler_kw={"revision": s["revision"], "prefix": s["prefix"],
                         "display_operands": s["display"], "comments": s["comments"]},
            string_types=proj.string_types if proj else None)
    except LLMError as e:
        return {"kind": "error", "message": str(e),
                "hint": f"{BACKENDS[s['backend']]['label']}, model '{s['model'] or 'default'}' at {client.url} "
                        "(change in ⚙️ Settings)."}
    attempts = [{"spec": a.spec, "error": a.error} for a in r.attempts]
    if r.spec is None:
        return {"kind": "error", "message": f"The model could not produce valid logic: {r.error}",
                "hint": "Try rewording, or name the tags you mean.", "attempts": attempts}
    out = _compile(r.compiled.statements, s)
    if out["kind"] == "compiled":
        out.update(kind="generated", spec=r.spec, model=s["model"] or s["backend"], attempts=attempts,
                   model_seconds=r.seconds, backend=BACKENDS[s["backend"]]["label"],
                   grammar=bool(getattr(client, "supports_grammar", False)))
        out["warnings"] = r.warnings + out["warnings"]
    return out


def _try_rungs(text: str, s: dict) -> dict | None:
    """Rung text, one rung per ';'. Returns None if it does not look like rungs."""
    if "(" not in text or ";" not in text:
        return None
    parts = [p.strip() + ";" for p in text.split(";") if p.strip()]
    try:
        parsed = [parse_rung(p) for p in parts]
    except RungSyntaxError:
        return None
    return _explain_rungs(parsed, source="neutral", s=s)


def _explain_rungs(parsed, source: str, s: dict) -> dict:
    """Rung ASTs -> the other text form, LogicSpec, English, checks, and an L5X."""
    rungs = []
    proj = _project()
    presets = proj.presets() if proj else {}
    for r in parsed:
        stmts, why = try_decompile(r, presets)
        rungs.append({
            "text": format_rung(r),
            "ascii": format_ascii(r),
            "logicspec": format_spec(stmts) if stmts else None,
            "english": [describe_statement(x) for x in stmts] if stmts else [],
            "why": why,
        })
    catalog = proj.catalog() if proj else None
    all_tags = {t.name: t.datatype for t in proj.tags.values()} if proj else None
    issues = validate(parsed, all_tags, catalog=catalog, revision=proj.software_revision if proj else None,
                      string_types=proj.string_types if proj else None)
    out = {"kind": "rungs", "source": source, "rungs": rungs, "issues": _issues_json(issues),
           "lint": _lint_json(parsed, all_tags, catalog, s),
           "tags": [], "warnings": [], "l5x": None, "used_project": STATE["filename"]}
    known = proj.tag_types(s["program"]) if proj else None
    try:
        tags, warns = infer_tags(parsed, known, catalog)
    except CompileError as e:
        out["warnings"].append(f"no L5X: {e}")
        return out
    out["tags"] = [{"name": t.name, "type": t.datatype, "preset": t.preset, "auto": False} for t in tags.values()]
    out["warnings"] = warns
    if not errors(issues):
        _l5x(out, parsed, tags.values(), s)
    return out


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name) or "Generated"


# ---------------------------------------------------------------- project


def _summary(p: Project) -> dict:
    routines = [{"program": r.program, "name": r.name, "type": r.type, "rungs": len(r.rungs),
                 "unparsed": sum(1 for x in r.rungs if x.rung is None)} for r in p.routines]
    programs = sorted({r.program for r in p.routines})
    # the program new logic most likely belongs in: MainProgram, else one in a continuous task
    continuous = [n for t in p.tasks if t.type == "CONTINUOUS" for n in t.programs]
    default = "MainProgram" if "MainProgram" in programs else next(
        (n for n in continuous if n in programs), programs[0] if programs else None)
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
        "default_program": default,
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


def _project_action(action: str, s: dict) -> dict:
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
                row = {"where": f"{rt.program} / {rt.name} / Rung {x.number}", "text": x.text,
                       "ascii": format_ascii(x.rung) if x.rung is not None else None}
                if x.rung is None:
                    row["why"] = f"parse error: {x.parse_error}"
                else:
                    stmts, why = try_decompile(x.rung, presets)
                    if stmts:
                        ok += 1
                        row["logicspec"] = format_spec(stmts)
                        row["english"] = [describe_statement(st) for st in stmts]
                    else:
                        row["why"] = why
                rows.append(row)
        return {"kind": "decompiled", "rows": rows, "ok": ok, "total": len(rows),
                "filename": STATE["filename"], "target": p.target_type}
    # validate: will Studio 5000 accept it (import checks), is it good (the rules)
    rep = lint.run(p, disabled=s["disabled_rules"])
    return {"kind": "validated", "target": p.target_type, "filename": STATE["filename"],
            "import": [{"where": i.where, "level": i.level, "message": i.message} for i in validate_project(p)],
            "lint": rep.to_dict()}


def _xref(tag: str) -> dict:
    p = _project()
    if p is None:
        return {"kind": "error", "message": "'xref' needs an attached L5X. Use Attach first."}
    if not tag:
        return {"kind": "error", "message": "Usage: xref TagName"}
    refs = cross_reference(p).get(tag, [])
    return {"kind": "xref", "tag": tag, "refs": [
        {"where": f"{r.program} / {r.routine} / Rung {r.rung}", "instruction": r.instruction,
         "operand": r.operand, "role": r.role} for r in refs]}


@app.post("/api/llm/models")
def llm_models():
    """Models available on the chosen local backend, and whether it is reachable."""
    from inputs.llm import BACKENDS, LLMError
    s = _settings((request.get_json(silent=True) or {}).get("settings"))
    client = _llm(s)
    try:
        models = client.list_models()
        return jsonify(ok=True, models=models, url=client.url, backend=BACKENDS[s["backend"]]["label"],
                       grammar=bool(getattr(client, "supports_grammar", False)))
    except LLMError as e:
        return jsonify(ok=False, models=[], url=client.url, backend=BACKENDS[s["backend"]]["label"], error=str(e))


@app.get("/api/status")
def status():
    p = _project()
    return jsonify(project=STATE["filename"], programs=sorted({r.program for r in p.routines}) if p else [],
                   default_program=_summary(p)["default_program"] if p else None)


if __name__ == "__main__":
    # 127.0.0.1 = reachable only from this PC
    app.run(host="127.0.0.1", port=5000, debug=False)
