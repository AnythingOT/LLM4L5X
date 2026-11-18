"""Command line interface. Run from the repo root: python cli.py <command> ...

  python cli.py compile spec.txt -o out.L5X [--routine NAME] [--project existing.L5X]
  python cli.py explain "IF RISE(A) THEN SET B;"
  python cli.py rung "XIC(a)[XIC(b) ,XIO(c) ]OTE(d);"
  python cli.py rung "XIC a BST XIC b NXB XIO c BND OTE d"
  python cli.py inspect project.L5X [--xref TAG] [--decompile]
  python cli.py validate project.L5X
  python cli.py survey folder_of_L5X_exports
  python cli.py ask "run the pump from start, stop with stop" [--project plant.L5X] [--model phi4-mini]
  python cli.py eval eval/requests.yaml --model phi4-mini
  python cli.py grammar --project project.L5X [--program MainProgram] [--new-tags]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from l5x.reader import read_l5x
from l5x.writer import write_routine, write_rungs
from l5x.xref import cross_reference
from core.logicspec import SpecError, format_spec, parse_spec
from core.compiler import Compiler
from explain.decompiler import try_decompile
from explain.describe import describe_statement
from inputs.gbnf import build_gbnf
from core.ascii import AsciiSyntaxError, format_ascii, looks_like_ascii, parse_ascii
from core.rung import RungSyntaxError, format_rung, parse_rung, walk
from core.validator import errors, validate


def _read_text(arg: str) -> str:
    """A file path, or the LogicSpec text itself (anything containing ';')."""
    if ";" in arg or "\n" in arg:
        return arg
    return Path(arg).read_text("utf-8")


def cmd_compile(a) -> int:
    project = read_l5x(Path(a.project)) if a.project else None
    known = project.tag_types(a.program) if project else None
    revision = a.revision or (project.software_revision if project else None) or "32.04"
    comp = Compiler(known_tags=known, prefix=a.prefix, display_operands=a.display,
                    comments=not a.no_comments, revision=revision,
                    catalog=project.catalog() if project else None)
    res = comp.compile(parse_spec(_read_text(a.spec)))
    all_types = dict(known or {})
    all_types.update({t.name: t.datatype for t in res.tags.values()})
    issues = validate(res.rungs, all_types if project else None,
                      catalog=project.catalog() if project else None, revision=revision,
                      string_types=project.string_types if project else None)
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
                  revision=revision, scope=a.scope)
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
    """Neutral or ASCII rung text in; neutral, ASCII and LogicSpec out."""
    text = _read_text(a.text) if not looks_like_ascii(a.text) else a.text
    cat = read_l5x(Path(a.project)).catalog() if a.project else None
    if looks_like_ascii(text, cat):
        rungs = parse_ascii(text, cat)
    else:
        rungs = [parse_rung(p.strip() + ";") for p in text.split(";") if p.strip()]
    for r in rungs:
        print("neutral:", format_rung(r))
        print("ascii:  ", format_ascii(r))
        stmts, why = try_decompile(r)
        if stmts:
            print("spec:   ", format_spec(stmts).replace("\n", "\n         "))
            for s in stmts:
                print("        #", describe_statement(s))
        else:
            print("spec:    not convertible:", why)
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
        for i in validate(rungs, p.tag_types(rt.program), catalog=cat, revision=p.software_revision, string_types=p.string_types):
            print(f"{rt.program}/{rt.name} {i}")
            bad += i.level == "error"
    return 1 if bad else 0


def _client(a):
    from inputs.llm import OllamaClient
    return OllamaClient(model=a.model, url=a.ollama, think=False if a.no_think else None)


def cmd_ask(a) -> int:
    """Plain English -> LogicSpec (local model) -> rungs, optionally L5X."""
    from inputs.llm import Generator, LLMError
    project = read_l5x(Path(a.project)) if a.project else None
    revision = a.revision or (project.software_revision if project else None) or "32.04"
    try:
        r = Generator(_client(a)).generate(
            a.request,
            known_tags=project.tag_types(a.program) if project else None,
            descriptions=project.tag_descriptions(a.program) if project else None,
            catalog=project.catalog() if project else None,
            compiler_kw={"revision": revision},
            string_types=project.string_types if project else None)
    except LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    for i, at in enumerate(r.attempts, 1):
        print(f"# attempt {i}: {at.error or 'ok'}", file=sys.stderr)
    if r.spec is None:
        print(f"error: {r.error}", file=sys.stderr)
        return 1
    print(r.spec)
    for s in r.compiled.statements:
        print("#", describe_statement(s))
    for t in r.compiled.texts:
        print(t)
    for w in r.warnings + r.compiled.warnings:
        print("warning:", w, file=sys.stderr)
    print(f"# {r.seconds}s with {a.model}", file=sys.stderr)
    if a.output:
        kw = dict(controller=a.controller, program=a.program or "MainProgram", revision=revision, scope=a.scope)
        Path(a.output).write_text(write_rungs(r.compiled.rungs, r.compiled.tags.values(), **kw), "utf-8")
        print(f"wrote {a.output}", file=sys.stderr)
    return 0


def cmd_eval(a) -> int:
    from eval.run import report, run_eval
    def progress(n, total, row):
        print(f"[{n}/{total}] {'ok ' if row.ok else 'BAD'} {row.seconds:5.1f}s  {row.request[:70]}", file=sys.stderr)
    rows = run_eval(a.file, _client(a), limit=a.limit, progress=progress)
    print(report(rows, a.model))
    return 0


def cmd_survey(a) -> int:
    from explain.survey import survey
    print(survey(a.folder).report())
    return 0


def cmd_grammar(a) -> int:
    tags = read_l5x(Path(a.project)).tag_types(a.program) if a.project else {}
    print(build_gbnf(tags, allow_new_tags=a.new_tags))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python cli.py", description="LogicSpec <-> Studio 5000 ladder")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compile", help="compile LogicSpec to rungs / L5X")
    c.add_argument("spec", help="LogicSpec text or a file containing it")
    c.add_argument("-o", "--output", help="write an L5X file")
    c.add_argument("--routine", help="write a whole routine with this name instead of rungs")
    c.add_argument("--project", help="existing L5X export: known tags, AOIs, type checks")
    c.add_argument("--program", help="program whose tags are visible (default: controller tags only)")
    c.add_argument("--controller", default="LLM4L5X")
    c.add_argument("--revision", help="target version, e.g. 36.00: picks GT/MOVE (v36+) or GRT/MOV "
                   "(older); default: the --project's version, else 32.04")
    c.add_argument("--scope", choices=["controller", "program"], default="controller")
    c.add_argument("--prefix", default="L4X", help="prefix for compiler-made tags")
    c.add_argument("--display", choices=["placeholder", "values"], default="placeholder",
                   help="TON(T,?,?) or TON(T,5000,0); which imports correctly is unverified")
    c.add_argument("--no-comments", action="store_true")
    c.set_defaults(fn=cmd_compile)

    e = sub.add_parser("explain", help="plain-English read-back of LogicSpec")
    e.add_argument("spec")
    e.set_defaults(fn=cmd_explain)

    r = sub.add_parser("rung", help="neutral or ASCII rung text -> neutral, ASCII and LogicSpec")
    r.add_argument("text", help='e.g. "XIC(a)OTE(b);" or "XIC a OTE b" (several: ; or one per line)')
    r.add_argument("--project", help="L5X whose AOIs are needed to read ASCII text")
    r.set_defaults(fn=cmd_rung)

    i = sub.add_parser("inspect", help="summarise an L5X file")
    i.add_argument("file")
    i.add_argument("--xref", metavar="TAG", help="list every reference to TAG")
    i.add_argument("--decompile", action="store_true", help="convert rungs to LogicSpec")
    i.set_defaults(fn=cmd_inspect)

    v = sub.add_parser("validate", help="check every ladder rung in an L5X file")
    v.add_argument("file")
    v.set_defaults(fn=cmd_validate)

    def llm_args(p):
        p.add_argument("--model", default="phi4-mini", help="Ollama model name (default phi4-mini)")
        p.add_argument("--ollama", default="http://127.0.0.1:11434", help="Ollama address")
        p.add_argument("--no-think", action="store_true", help="ask thinking models (Qwen3 etc.) not to think")

    ak = sub.add_parser("ask", help="plain English -> LogicSpec -> rungs, with a local model via Ollama")
    ak.add_argument("request")
    ak.add_argument("--project", help="existing L5X: the model uses its real tags")
    ak.add_argument("--program")
    ak.add_argument("--revision")
    ak.add_argument("--controller", default="LLM4L5X")
    ak.add_argument("--scope", choices=["controller", "program"], default="controller")
    ak.add_argument("-o", "--output", help="write a rungs L5X file")
    llm_args(ak)
    ak.set_defaults(fn=cmd_ask)

    ev = sub.add_parser("eval", help="score a model on English requests with expected LogicSpec")
    ev.add_argument("file", nargs="?", default="eval/requests.yaml")
    ev.add_argument("--limit", type=int)
    llm_args(ev)
    ev.set_defaults(fn=cmd_eval)

    sv = sub.add_parser("survey", help="check parser/catalog/decompiler against a folder of L5X exports")
    sv.add_argument("folder")
    sv.set_defaults(fn=cmd_survey)

    g = sub.add_parser("grammar", help="print a GBNF grammar for llama.cpp (experimental)")
    g.add_argument("--project")
    g.add_argument("--program")
    g.add_argument("--new-tags", action="store_true")
    g.set_defaults(fn=cmd_grammar)

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except (SpecError, RungSyntaxError, AsciiSyntaxError, ValueError) as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
