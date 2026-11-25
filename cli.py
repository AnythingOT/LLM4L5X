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
from core.describe import describe_statement
from generate.gbnf import build_gbnf
from core.ascii import AsciiSyntaxError, format_ascii, looks_like_ascii, parse_ascii
from core.rung import RungSyntaxError, format_rung, parse_rung
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
    """Import checks (will Studio 5000 accept it) plus the lint rules (is it good)."""
    import lint
    from core.validator import validate_project
    if a.rules:
        for r in lint.RULES:
            print(f"{r.code}  {r.severity:8s} {r.scope:7s} {r.title}")
        return 0
    if not a.file:
        print("validate: give an .L5X file (or --rules)", file=sys.stderr)
        return 2
    p = read_l5x(Path(a.file))
    issues = validate_project(p)
    print(f"Import checks: {sum(i.level == 'error' for i in issues)} error(s), "
          f"{sum(i.level == 'warning' for i in issues)} warning(s)")
    for i in issues:
        print(f"  [{i.level}] {i.where}: {i.message}")
    prof = None
    if a.profile:
        from lint.profile import load_profile
        prof = load_profile(open(a.profile, encoding="utf-8").read())
    rep = lint.run(p, disabled=[c.strip() for c in (a.disable or "").split(",") if c.strip()], profile=prof)
    c = rep.counts()
    print(f"\nRules: {c['critical']} critical, {c['error']} error, {c['warning']} warning, {c['info']} info"
          + (f" ({len(rep.suppressed)} suppressed by lint:disable)" if rep.suppressed else ""))
    for f in rep.findings:
        print(f"  {f.code} {f.location}: {f.message}")
    for code, why in sorted(rep.not_verified.items()):
        print(f"  not verified {code}: {why}")
    for note in rep.notes + [f"rule crashed: {e}" for e in rep.errors]:
        print(f"  note: {note}")
    blocking = any(i.level == "error" for i in issues) or c["critical"] or c["error"] or rep.errors
    return 1 if blocking else 0


def cmd_fix(a) -> int:
    """Fix what the lint finds where a fix is certain: safe fixes in one batch, the others one by one."""
    from lint.autofix import AutoFix
    src = Path(a.file)
    af = AutoFix(src.read_bytes())
    fixes = af.proposals()
    if not fixes:
        print("Nothing to fix automatically.")
        return 0

    def ask(question: str) -> str:
        return "y" if a.yes else input(question).strip()

    chosen, values = [], {}
    safe = [f for f in fixes if f.safe]
    if safe:
        print(f"{len(safe)} safe fix(es): the program behaves exactly as before.")
        for f in safe:
            print(f"  {f.code} {f.where}: {f.what} ({f.checked})")
        if a.safe or ask("Apply them? [y/n] ").lower().startswith("y"):
            chosen += safe
    rest = [] if a.safe else [f for f in fixes if not f.safe]  # --safe: nothing that changes behaviour
    tags = [f for f in rest if f.code == "INF001"]  # often thousands: one question for all of them
    for f in [f for f in rest if f.code != "INF001"]:
        print(f"\n{f.code} {f.where}: {f.what}\n  Changes: {f.change}")
        if f.needs:
            while not a.yes:  # checked as it is typed: one wrong answer must not lose the other fixes
                v = ask(f"  {f.needs[0].upper() + f.needs[1:]} (empty: skip): ")
                if not v:
                    break
                try:
                    if float(v) > 0:
                        values[len(chosen)] = v
                        chosen.append(f)
                        break
                except ValueError:
                    pass
                print("  A number above 0, please.")
        elif ask("  Apply? [y/n] ").lower().startswith("y"):
            chosen.append(f)
    if tags:
        print(f"\nINF001: {len(tags)} unused tag(s) that an HMI, SCADA or another controller could still read:")
        for f in tags[:10]:
            print(f"  {f.where}")
        if len(tags) > 10:
            print(f"  ... and {len(tags) - 10} more")
        if ask("Delete them all? [y/n] ").lower().startswith("y"):
            chosen += tags
    if not chosen:
        print("Nothing applied; the file is unchanged.")
        return 0
    try:
        done = af.apply(chosen, values)
    except ValueError as e:
        print(f"fix: {e}", file=sys.stderr)
        return 2
    out = Path(a.output) if a.output else src.with_name(src.stem + "_fixed" + src.suffix)
    out.write_bytes(af.write())
    print(f"\n{len(done)} fix(es) applied, written to {out}")
    still = af.findings()
    if still:
        print(f"Still open ({len(still)}): " + ", ".join(sorted({f.code for f in still})))
    return 0


def _client(a):
    from generate.llm import make_client
    return make_client(a.backend, a.url, a.model, think=False if a.no_think else None,
                       allow_remote=getattr(a, "allow_remote", False))


def cmd_ask(a) -> int:
    """Plain English -> LogicSpec (local model) -> rungs, optionally L5X."""
    from generate.llm import Generator, LLMError
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


def cmd_probe(a) -> int:
    """Find out which part breaks grammar-constrained answers on a llama-server."""
    import urllib.error
    import urllib.request
    from generate.gbnf import build_gbnf
    from generate.llm import check_url
    url = check_url((a.url or "http://127.0.0.1:8080").rstrip("/"), a.allow_remote) + "/v1/chat/completions"
    ask = [{"role": "user", "content": "Write LogicSpec: turn on Motor_Run while Start_PB is on."}]
    spec_grammar = build_gbnf({"Motor_Run": "BOOL", "Start_PB": "BOOL"}, allow_new_tags=False)
    off = {"chat_template_kwargs": {"enable_thinking": False}}
    tests = [
        ("1 no grammar", {}),
        ("2 tiny grammar", {"grammar": 'root ::= "OK"'}),
        ("3 tiny grammar, thinking off", {"grammar": 'root ::= "OK"', **off}),
        ("4 LogicSpec grammar, thinking off", {"grammar": spec_grammar, **off}),
        ("5 LogicSpec grammar", {"grammar": spec_grammar}),
    ]
    for name, extra in tests:
        body = {"messages": ask, "temperature": 0, "max_tokens": 60, "stream": False, **extra}
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                msg = json.loads(r.read().decode("utf-8"))["choices"][0]["message"]
            text = (msg.get("content") or "").strip().replace("\n", " ")
            think = " (+reasoning text)" if msg.get("reasoning_content") else ""
            print(f"{name:36s} OK    {text[:70]!r}{think}")
        except urllib.error.HTTPError as e:
            print(f"{name:36s} ERROR {e.code}: {e.read().decode('utf-8', 'replace')[:160]}")
        except (urllib.error.URLError, OSError) as e:
            print(f"{name:36s} cannot reach {url}: {e}")
            return 1
    return 0


def _model_label(a, client) -> str:
    """What actually answered: llama-server ignores --model, so ask the server."""
    name = a.model
    if a.backend != "ollama":
        try:
            name = ", ".join(client.list_models()) or "?"
        except Exception:  # noqa: BLE001 - a label must never break a finished run
            name = "?"
    return f"{name} via {a.backend}" + (" (no-think)" if a.no_think else "")


def cmd_suite(a) -> int:
    from eval.suite import generate
    from eval.suite_run import model_run, self_test, summary, write_excel
    cases = generate(per_combo=a.per, seed=a.seed, version=a.version,
                     instructions=a.only.split(",") if a.only else None)
    def progress(n, total, o):
        if a.model or n % 50 == 0 or not o.ok:
            flag = "  [grammar rejected, free text]" if getattr(o, "grammar", "") == "rejected" else ""
            print(f"[{n}/{total}] {'ok ' if o.ok else 'BAD'} {o.case.id}{flag}", file=sys.stderr)
    if a.self_test:
        out = self_test(cases, a.version, progress)
        title = f"SELF-TEST (compiler vs reference), {len(cases)} cases, v{a.version}, seed {a.seed}"
    else:
        client = _client(a)
        out = model_run(cases, client, a.version, progress)
        title = f"MODEL {_model_label(a, client)}, {len(cases)} cases, v{a.version}, seed {a.seed}"
    print(summary(out, title))
    if a.excel:
        write_excel(out, a.excel, title)
        print(f"wrote {a.excel}", file=sys.stderr)
    return 0 if all(o.ok for o in out) or not a.self_test else 1


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

    v = sub.add_parser("validate", help="import checks and the programming rules (CRT/ERR/WAR/INF) on an L5X file")
    v.add_argument("file", nargs="?")
    v.add_argument("--disable", help="rule codes to skip, comma separated (e.g. INF004,INF003)")
    v.add_argument("--rules", action="store_true", help="list the rules and exit")
    v.add_argument("--profile", help="company coding-standards profile (YAML), see docs/PROFILE.md")
    v.set_defaults(fn=cmd_validate)

    fx = sub.add_parser("fix", help="fix lint findings where the fix is certain: safe ones in one batch, "
                                    "the ones that change behaviour one by one")
    fx.add_argument("file")
    fx.add_argument("-o", "--output", help="where to write (default: FILE_fixed.L5X next to it)")
    fx.add_argument("--safe", action="store_true", help="apply the safe fixes only, without asking")
    fx.add_argument("--yes", action="store_true", help="answer yes to every question (values are skipped)")
    fx.set_defaults(fn=cmd_fix)

    def llm_args(p):
        p.add_argument("--backend", choices=["ollama", "llamacpp", "openai"], default="ollama",
                       help="ollama | llamacpp (llama-server, grammar-constrained) | openai (LM Studio etc.)")
        p.add_argument("--model", default="phi4-mini", help="model name (default phi4-mini; llama-server ignores it)")
        p.add_argument("--url", "--ollama", dest="url", help="server address (default: the backend's usual port)")
        p.add_argument("--allow-remote", action="store_true",
                       help="allow a model server on another computer (your tags and requests are sent there)")
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

    pr = sub.add_parser("probe", help="check grammar-constrained answers on a llama-server (5 short requests)")
    pr.add_argument("--url", help="default http://127.0.0.1:8080")
    pr.add_argument("--allow-remote", action="store_true", help="allow a server on another computer")
    pr.set_defaults(fn=cmd_probe)

    su = sub.add_parser("suite", help="instruction suite (series/parallel/nested): --self-test or --model")
    su.add_argument("--self-test", action="store_true", help="compiler vs reference rungs, no model")
    su.add_argument("--per", type=int, default=3, help="cases per instruction x structure (default 3)")
    su.add_argument("--seed", type=int, default=1)
    su.add_argument("--version", type=int, default=35, help="35: EQU/GRT/MOV names, 36: EQ/GT/MOVE")
    su.add_argument("--only", help="comma-separated instructions, e.g. ONS,TON,GT")
    su.add_argument("--excel", help="write results to an .xlsx (like the old TestData sheet)")
    llm_args(su)
    su.set_defaults(fn=cmd_suite)

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
