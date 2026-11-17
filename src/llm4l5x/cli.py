"""Command line interface.

  llm4l5x compile spec.txt -o out.L5X [--routine NAME] [--project existing.L5X]
  llm4l5x explain "IF RISE(A) THEN SET B;"
  llm4l5x rung "XIC(a)[XIC(b) ,XIO(c) ]OTE(d);"
  llm4l5x inspect project.L5X [--xref TAG] [--decompile]
  llm4l5x validate project.L5X
  llm4l5x grammar --project project.L5X [--program MainProgram] [--new-tags]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .l5x import cross_reference, read_l5x, write_routine, write_rungs
from .logicspec import SpecError, format_spec, parse_spec
from .logicspec.compiler import Compiler
from .logicspec.decompiler import try_decompile
from .logicspec.describe import describe_statement
from .logicspec.gbnf import build_gbnf
from .rung import RungSyntaxError, format_rung, parse_rung, walk
from .validate import errors, validate


def _read_text(arg: str) -> str:
    """A file path, or the LogicSpec text itself (anything containing ';')."""
    if ";" in arg or "\n" in arg:
        return arg
    return Path(arg).read_text("utf-8")


def cmd_compile(a) -> int:
    project = read_l5x(Path(a.project)) if a.project else None
    known = project.tag_types(a.program) if project else None
    comp = Compiler(known_tags=known, prefix=a.prefix, display_operands=a.display,
                    comments=not a.no_comments,
                    catalog=project.catalog() if project else None)
    res = comp.compile(parse_spec(_read_text(a.spec)))
    all_types = dict(known or {})
    all_types.update({t.name: t.datatype for t in res.tags.values()})
    issues = validate(res.rungs, all_types if project else None,
                      catalog=project.catalog() if project else None)
    for s in res.statements:
        print("#", describe_statement(s), file=sys.stderr)
    for r in res.rungs:
        print(format_rung(r))
    for w in res.warnings:
        print("warning:", w, file=sys.stderr)
    for i in issues:
        print(i, file=sys.stderr)
    if errors(issues):
        print("not written: fix the errors above", file=sys.stderr)
        return 2
    if a.output:
        kw = dict(controller=a.controller, program=a.program or "MainProgram",
                  revision=a.revision, scope=a.scope)
        xml = (write_routine(res.rungs, res.tags.values(), routine=a.routine, **kw)
               if a.routine else write_rungs(res.rungs, res.tags.values(), **kw))
        Path(a.output).write_text(xml, "utf-8")
        print(f"wrote {a.output} ({len(res.rungs)} rungs, {len(res.tags)} new tags)", file=sys.stderr)
    return 0


def cmd_explain(a) -> int:
    for s in parse_spec(_read_text(a.spec)):
        print(describe_statement(s))
    return 0


def cmd_rung(a) -> int:
    r = parse_rung(a.text)
    print(format_rung(r))
    stmts, why = try_decompile(r)
    if stmts:
        print(format_spec(stmts))
        for s in stmts:
            print("#", describe_statement(s))
    else:
        print("# not convertible:", why)
    return 0


def cmd_inspect(a) -> int:
    p = read_l5x(Path(a.file))
    if a.xref:
        refs = cross_reference(p).get(a.xref, [])
        for r in refs:
            print(f"{r.program}/{r.routine} rung {r.rung}: {r.instruction}({r.operand}) {r.role}")
        return 0
    print(json.dumps({
        "controller": p.controller,
        "software_revision": p.software_revision,
        "target_type": p.target_type,
        "tags": len(p.tags),
        "udts": sorted(p.udts),
        "aois": sorted(p.aois),
        "routines": [
            {"program": r.program, "name": r.name, "type": r.type, "rungs": len(r.rungs),
             "unparsed": sum(1 for x in r.rungs if x.rung is None)}
            for r in p.routines
        ],
    }, indent=2))
    if a.decompile:
        presets = p.presets()
        ok = total = 0
        for rt in p.routines:
            for x in rt.rungs:
                if x.rung is None:
                    continue
                total += 1
                stmts, why = try_decompile(x.rung, presets)
                head = f"{rt.program}/{rt.name} rung {x.number}"
                if stmts:
                    ok += 1
                    print(f"{head}: {format_spec(stmts)}")
                else:
                    print(f"{head}: not convertible ({why})")
        print(f"{ok}/{total} rungs convertible", file=sys.stderr)
    return 0


def cmd_validate(a) -> int:
    p = read_l5x(Path(a.file))
    cat = p.catalog()
    bad = 0
    for rt in p.routines:
        rungs = []
        for x in rt.rungs:
            if x.rung is None:
                print(f"{rt.program}/{rt.name} rung {x.number}: parse error: {x.parse_error}")
                bad += 1
            else:
                rungs.append(x.rung)
        for i in validate(rungs, p.tag_types(rt.program), catalog=cat):
            print(f"{rt.program}/{rt.name} {i}")
            bad += i.level == "error"
    return 1 if bad else 0


def cmd_grammar(a) -> int:
    tags = read_l5x(Path(a.project)).tag_types(a.program) if a.project else {}
    print(build_gbnf(tags, allow_new_tags=a.new_tags))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="llm4l5x", description="LogicSpec <-> Studio 5000 ladder")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compile", help="compile LogicSpec to rungs / L5X")
    c.add_argument("spec", help="LogicSpec text or a file containing it")
    c.add_argument("-o", "--output", help="write an L5X file")
    c.add_argument("--routine", help="write a whole routine with this name instead of rungs")
    c.add_argument("--project", help="existing L5X export: known tags, AOIs, type checks")
    c.add_argument("--program", help="program whose tags are visible (default: controller tags only)")
    c.add_argument("--controller", default="LLM4L5X")
    c.add_argument("--revision", default="32.04", help="SoftwareRevision attribute")
    c.add_argument("--scope", choices=["controller", "program"], default="controller")
    c.add_argument("--prefix", default="L4X", help="prefix for compiler-made tags")
    c.add_argument("--display", choices=["placeholder", "values"], default="placeholder",
                   help="TON(T,?,?) or TON(T,5000,0); which imports correctly is unverified")
    c.add_argument("--no-comments", action="store_true")
    c.set_defaults(fn=cmd_compile)

    e = sub.add_parser("explain", help="plain-English read-back of LogicSpec")
    e.add_argument("spec")
    e.set_defaults(fn=cmd_explain)

    r = sub.add_parser("rung", help="parse rung text, print canonical form and LogicSpec")
    r.add_argument("text")
    r.set_defaults(fn=cmd_rung)

    i = sub.add_parser("inspect", help="summarise an L5X file")
    i.add_argument("file")
    i.add_argument("--xref", metavar="TAG", help="list every reference to TAG")
    i.add_argument("--decompile", action="store_true", help="convert rungs to LogicSpec")
    i.set_defaults(fn=cmd_inspect)

    v = sub.add_parser("validate", help="check every ladder rung in an L5X file")
    v.add_argument("file")
    v.set_defaults(fn=cmd_validate)

    g = sub.add_parser("grammar", help="print a GBNF grammar for llama.cpp (experimental)")
    g.add_argument("--project")
    g.add_argument("--program")
    g.add_argument("--new-tags", action="store_true")
    g.set_defaults(fn=cmd_grammar)

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except (SpecError, RungSyntaxError, ValueError) as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
