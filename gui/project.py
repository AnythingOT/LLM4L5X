"""The attached L5X: summary, plain-English read of every rung, validation, cross reference."""

from __future__ import annotations

from core.ascii import format_ascii
from core.catalog import major_version
from core.logicspec import format_spec
from core.validator import validate_project
from explain.comments import add_rung_comments
from explain.decompiler import try_decompile
from core.describe import describe_statement
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


# ------------------------------------------------------------------ the explorer

def tree() -> dict:
    """The attached file as the explorer shows it: controller, tasks with their programs, programs with
    their routines, tags, UDTs, AOIs and the I/O tree. Names only: an item is read when it is opened."""
    p = SESSION.project
    if p is None:
        return {"attached": False}
    by_program: dict[str, list[dict]] = {}
    for rt in p.routines:
        if rt.program.startswith("AOI:"):
            continue
        by_program.setdefault(rt.program, []).append({"name": rt.name, "type": rt.type, "rungs": len(rt.rungs),
                                                      "protected": rt.protected})
    programs = [{"name": pr.name, "main": pr.main_routine, "safety": pr.program_class == "Safety",
                 "routines": by_program.pop(pr.name, [])} for pr in p.programs]
    programs += [{"name": name, "main": None, "safety": False, "routines": rts} for name, rts in by_program.items()]
    scoped: dict[str, int] = {}
    for key in p.tags:
        scope = key.split("/", 1)[0] if "/" in key else ""
        scoped[scope] = scoped.get(scope, 0) + 1
    return {
        "attached": True, "filename": SESSION.filename, "controller": p.controller, "processor": p.processor,
        "revision": p.software_revision, "target": p.target_type,
        "tasks": [{"name": t.name, "type": t.type, "period": t.period, "programs": t.programs} for t in p.tasks],
        "programs": programs,
        "tags": {"controller": scoped.get("", 0), "programs": {k: v for k, v in scoped.items() if k}},
        "udts": sorted(n for n, d in p.datatypes.items() if d.is_user),
        "aois": sorted(set(p.aois) | set(p.protected_aois)),
        "modules": [{"name": m.name, "catalog": m.catalog, "parent": m.parent, "slot": m.slot} for m in p.modules],
    }


def routine(program: str, name: str) -> dict:
    """One routine as the editor shows it: each rung's comment, its English read, its text."""
    rows = [r for r in decompile()["rows"] if r["key"][0] == program and r["key"][1] == name]
    if not rows and not any(rt.program == program and rt.name == name for rt in SESSION.project.routines):
        raise KeyError(f"{program} / {name} is not in the attached file")
    return {"kind": "routine", "program": program, "name": name, "rows": rows}


def item(kind: str, name: str) -> dict:
    """A UDT, an AOI, a module or a tag list, for an editor tab."""
    p = SESSION.project
    if kind == "udt":
        d = p.datatypes.get(name)
        if d is None:
            raise KeyError(f"UDT {name} is not in the attached file")
        return {"kind": "udt", "name": name, "description": d.description,
                "members": [{"name": m.name, "type": m.datatype, "dimension": m.dimension,
                             "description": m.description} for m in d.members if not m.hidden]}
    if kind == "aoi":
        a = p.aois.get(name)
        if a is None:
            if name in p.protected_aois:
                return {"kind": "aoi", "name": name, "protected": True, "params": [], "rows": []}
            raise KeyError(f"AOI {name} is not in the attached file")
        rows = [r for r in decompile()["rows"] if r["key"][0] == f"AOI:{name}"]
        return {"kind": "aoi", "name": name, "description": a.description, "protected": False,
                "params": [{"name": x.name, "type": x.datatype, "usage": x.usage, "required": x.required,
                            "description": x.description} for x in a.params],
                "locals": [{"name": t.name, "type": t.datatype} for t in a.local_tags], "rows": rows}
    if kind == "module":
        m = next((m for m in p.modules if m.name == name), None)
        if m is None:
            raise KeyError(f"module {name} is not in the attached file")
        return {"kind": "module", "name": name, "catalog": m.catalog_full or m.catalog, "parent": m.parent,
                "slot": m.slot, "ekey": m.ekey, "port": m.upstream_type,
                "io": [{"tag": f"{m.name}:{t.suffix}", "kind": t.kind, "comments": len(t.comments)} for t in m.io_tags]}
    if kind == "tags":
        scope = name  # "" for controller scope, else the program
        rows = []
        for key, t in p.tags.items():
            in_scope = ("/" not in key) if not scope else key.startswith(f"{scope}/")
            if in_scope:
                rows.append({"name": t.name, "type": t.datatype, "dims": t.dimensions, "alias": t.alias_for,
                             "description": t.description, "class": t.tag_class})
        return {"kind": "tags", "scope": scope or "Controller", "tags": sorted(rows, key=lambda r: r["name"].upper())}
    raise KeyError(f"unknown item kind {kind}")
