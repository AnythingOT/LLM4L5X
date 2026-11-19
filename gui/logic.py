"""Logic in the chat box: plain English (through the model), LogicSpec, or rung text (neutral or ASCII)."""

from __future__ import annotations

import re

import lint
from core.ascii import AsciiSyntaxError, format_ascii, looks_like_ascii, parse_ascii
from core.compiler import CompileError, Compiler, infer_tags
from core.logicspec import SpecError, format_spec, parse_spec
from core.rung import RungSyntaxError, format_rung, parse_rung
from core.validator import errors, validate
from explain.decompiler import try_decompile
from explain.describe import describe_statement
from explain.ladder import to_svg
from gui import state
from gui.state import SESSION
from inputs.llm import Generator, LLMError
from l5x.writer import write_routine, write_rungs


def handle(text: str, s: dict) -> dict:
    try:
        stmts = parse_spec(text)
    except SpecError as spec_err:
        catalog = SESSION.project.catalog() if SESSION.project else None
        if looks_like_ascii(text, catalog):
            try:
                return _explain(parse_ascii(text, catalog), "ASCII", s)
            except AsciiSyntaxError as e:
                return {"kind": "error", "message": f"Not valid ASCII rung text: {e}"}
        rungs = _neutral_rungs(text)
        if rungs is not None:
            return _explain(rungs, "neutral", s)
        if _looks_like_logicspec(text):
            return {"kind": "error", "message": f"Not valid LogicSpec: {spec_err}",
                    "hint": "Type 'help' for the syntax, or describe the logic in plain English."}
        return _english(text, s)
    return _compile(stmts, s)


# ---------------------------------------------------------------- building blocks


def _issues(issues) -> list[dict]:
    return [{"level": i.level, "rung": i.rung, "message": i.message} for i in issues]


def _lint(rungs, types, catalog, s: dict) -> list[dict]:
    """Rung rules on new or pasted rungs (the project rules need the whole project)."""
    return [f.to_dict() for f in lint.check_rungs(rungs, types, catalog, disabled=s["disabled_rules"])]


def _attach_l5x(out: dict, rungs, tags, s: dict) -> None:
    """The download: a routine or rung export, as chosen in Settings."""
    kw = dict(controller=s["controller"], program=s["program"], revision=s["revision"], scope=s["scope"])
    if s["output"] == "routine":
        out.update(l5x=write_routine(rungs, tags, routine=s["routine"], **kw), filename="Routine.L5X")
    else:
        out.update(l5x=write_rungs(rungs, tags, **kw), filename="Rung.L5X")


def _looks_like_logicspec(text: str) -> bool:
    """Someone typing LogicSpec (with a mistake) rather than English."""
    return bool(re.search(r":=|^\s*IF\b.*\bTHEN\b", text, flags=re.I | re.M)) and text.rstrip().endswith(";")


def _neutral_rungs(text: str):
    """Neutral rung text, one rung per ';'; None if it does not look like rungs."""
    if "(" not in text or ";" not in text:
        return None
    try:
        return [parse_rung(p.strip() + ";") for p in text.split(";") if p.strip()]
    except RungSyntaxError:
        return None


# ---------------------------------------------------------------- the three inputs


def _compile(stmts, s: dict) -> dict:
    """LogicSpec -> rungs, tags, read-back, checks and an L5X."""
    proj = SESSION.project
    known = proj.tag_types(s["program"]) if proj else None
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
        "rungs": [{"text": format_rung(r), "ascii": format_ascii(r), "comment": r.comment,
                   "svg": to_svg(r, catalog, number=n)} for n, r in enumerate(res.rungs)],
        "tags": [{"name": t.name, "type": t.datatype, "preset": t.preset, "auto": t.allocated}
                 for t in res.tags.values()],
        "warnings": res.warnings,
        "issues": _issues(issues),
        "lint": _lint(res.rungs, types, catalog, s),
        "used_project": SESSION.filename,
        "l5x": None,
    }
    if not errors(issues):
        _attach_l5x(out, res.rungs, res.tags.values(), s)
    return out


def _english(text: str, s: dict) -> dict:
    """Plain English -> local model -> LogicSpec -> compiled, checked rungs."""
    proj = SESSION.project
    client = state.llm(s)
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
        return {"kind": "error", "message": str(e), "hint": state.llm_hint(s, client)}
    attempts = [{"spec": a.spec, "error": a.error} for a in r.attempts]
    if r.spec is None:
        return {"kind": "error", "message": f"The model could not produce valid logic: {r.error}",
                "hint": "Try rewording, or name the tags you mean.", "attempts": attempts}
    out = _compile(r.compiled.statements, s)
    if out["kind"] == "compiled":
        out.update(kind="generated", spec=r.spec, attempts=attempts, model_seconds=r.seconds,
                   **state.model_info(s, client))
        out["warnings"] = r.warnings + out["warnings"]
    return out


def _explain(parsed, source: str, s: dict) -> dict:
    """Rung ASTs -> the other text form, LogicSpec, English, checks, and an L5X."""
    proj = SESSION.project
    presets = proj.presets() if proj else {}
    catalog = proj.catalog() if proj else None
    rungs = []
    for n, r in enumerate(parsed):
        stmts, why = try_decompile(r, presets)
        rungs.append({"text": format_rung(r), "ascii": format_ascii(r), "svg": to_svg(r, catalog, number=n),
                      "logicspec": format_spec(stmts) if stmts else None,
                      "english": [describe_statement(x) for x in stmts] if stmts else [], "why": why})
    all_tags = {t.name: t.datatype for t in proj.tags.values()} if proj else None
    issues = validate(parsed, all_tags, catalog=catalog, revision=proj.software_revision if proj else None,
                      string_types=proj.string_types if proj else None)
    out = {"kind": "rungs", "source": source, "rungs": rungs, "issues": _issues(issues),
           "lint": _lint(parsed, all_tags, catalog, s),
           "tags": [], "warnings": [], "l5x": None, "used_project": SESSION.filename}
    try:
        tags, warns = infer_tags(parsed, proj.tag_types(s["program"]) if proj else None, catalog)
    except CompileError as e:
        out["warnings"].append(f"no L5X: {e}")
        return out
    out["tags"] = [{"name": t.name, "type": t.datatype, "preset": t.preset, "auto": False} for t in tags.values()]
    out["warnings"] = warns
    if not errors(issues):
        _attach_l5x(out, parsed, tags.values(), s)
    return out
