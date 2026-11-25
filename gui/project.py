"""The attached L5X: summary, plain-English read of every rung, validation, cross reference."""

from __future__ import annotations

from core.ascii import format_ascii
from core.catalog import major_version
from core.logicspec import format_spec
from core.validator import validate_project
from explain.comments import add_rung_comments
from explain.decompiler import try_decompile
from explain.describe import describe_statement
from gui.state import SESSION
import lint


def summary() -> dict:
    p = SESSION.project
    programs = sorted({r.program for r in p.routines})
    return {
        "kind": "project",
        "filename": SESSION.filename,
        "controller": p.controller,
        "revision": p.software_revision,
        "revision_major": major_version(p.software_revision),
        "target": p.target_type,
        "tags": len(p.tags),
        "udts": sorted(n for n, d in p.datatypes.items() if d.is_user),  # not Rockwell's ALARM_*, module types
        "aois": sorted(p.aois),
        "programs": programs,
        "default_program": default_program(),
        "routines": [{"program": r.program, "name": r.name, "type": r.type, "rungs": len(r.rungs),
                      "unparsed": sum(1 for x in r.rungs if x.rung is None)} for r in p.routines],
    }


def default_program() -> str | None:
    """Where new logic most likely belongs: MainProgram, else a program of the continuous task."""
    p = SESSION.project
    if p is None:
        return None
    programs = sorted({r.program for r in p.routines})
    continuous = [n for t in p.tasks if t.type == "CONTINUOUS" for n in t.programs]
    if "MainProgram" in programs:
        return "MainProgram"
    return next((n for n in continuous if n in programs), programs[0] if programs else None)


def decompile() -> dict:
    p = SESSION.project
    presets = p.presets()
    rows, ok = [], 0
    for rt in p.routines:
        for x in rt.rungs:
            row = {"where": f"{rt.program} / {rt.name} / Rung {x.number}", "number": x.number, "text": x.text,
                   "ascii": format_ascii(x.rung) if x.rung is not None else None,
                   "comment": (x.comment or "").strip() or None, "key": [rt.program, rt.name, x.number]}
            if x.rung is None:
                row["why"] = f"parse error: {x.parse_error}"
            else:
                stmts, why = try_decompile(x.rung, presets)
                if stmts:
                    ok += 1
                    row.update(logicspec=format_spec(stmts), english=[describe_statement(st) for st in stmts])
                else:
                    row["why"] = why
            rows.append(row)
    return {"kind": "decompiled", "rows": rows, "ok": ok, "total": len(rows),
            "filename": SESSION.filename, "target": p.target_type,
            "commented": sum(1 for r in rows if r["comment"]),
            "can_comment": sum(1 for r in rows if not r["comment"] and r.get("english"))}


def commented_l5x() -> tuple[bytes, str, int]:
    """The attached file with the English read written into every rung that has no comment."""
    explained = {tuple(r["key"]): " ".join(r["english"]) for r in decompile()["rows"]
                 if r.get("english") and not r["comment"]}
    body, added = add_rung_comments(SESSION.raw, explained)
    stem = SESSION.filename.rsplit(".", 1)[0]
    return body, f"{stem}_commented.L5X", added


def validate(s: dict) -> dict:
    """Will Studio 5000 accept it (import checks), and is it good (the rules)."""
    p = SESSION.project
    return {"kind": "validated", "target": p.target_type, "filename": SESSION.filename,
            "import": [{"where": i.where, "level": i.level, "message": i.message} for i in validate_project(p)],
            "lint": lint.run(p, disabled=s["disabled_rules"]).to_dict()}


def xref(tag: str) -> dict:
    if not tag:
        return {"kind": "error", "message": "Usage: xref TagName"}
    return {"kind": "xref", "tag": tag, "refs": [
        {"where": f"{r.program} / {r.routine} / Rung {r.rung}", "instruction": r.instruction,
         "operand": r.operand, "role": r.role} for r in SESSION.xref().get(tag, [])]}
