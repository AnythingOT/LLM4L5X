"""Request -> LogicSpec -> compiled rungs, with retries on any failed check."""

from __future__ import annotations

import difflib
import re
import time
from dataclasses import dataclass, field


from core.catalog import Catalog
from core.compiler import CompileError, CompileResult, Compiler
from core.logicspec import SpecError, format_spec, format_statement, parse_spec
from core.validator import errors, validate
from lint import check_rungs
from .checks import near_miss_warnings, output_problems
from .clients import LLMError
from .names import _norm, _words, extract_spec, plain_names, request_identifiers, snap_tags, spec_tags
from .prompt import SYSTEM_PROMPT, load_examples, pick_examples, pick_tags


# lint findings on generated rungs that send the model back for another attempt:
# a timer or one-shot shared between rungs cannot work as written
RETRY_CODES = {"ERR014", "ERR015"}


@dataclass
class Attempt:
    reply: str  # raw model reply, kept for diagnosis
    spec: str
    error: str | None


@dataclass
class Result:
    request: str
    spec: str | None  # final, compiled LogicSpec
    compiled: CompileResult | None
    attempts: list[Attempt] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    seconds: float = 0.0
    error: str | None = None


class Generator:
    def __init__(self, client, examples: list[dict] | None = None, retries: int = 2):
        self.client = client
        self.examples = load_examples() if examples is None else examples
        self.retries = retries

    def shown_examples(self, request: str) -> list[dict]:
        return pick_examples(request, self.examples, k=4)

    def messages(self, request: str, tags: list[tuple[str, str, str]]) -> list[dict]:
        system = SYSTEM_PROMPT
        if tags:
            listing = "\n".join(f"  {n} ({t})" + (f" - {d}" if d else "") for n, t, d in tags)
            system += ("\nExisting tags in this project. Use them whenever they match; "
                       f"invent a new short name only if none fits:\n{listing}")
        else:
            system += "\nInvent short, clear tag names like Pump_Run or Tank_Level (letters, digits, single _)."
        msgs = [{"role": "system", "content": system}]
        for ex in self.shown_examples(request):
            msgs += [{"role": "user", "content": ex["english"]},
                     {"role": "assistant", "content": ex["spec"]}]
        msgs.append({"role": "user", "content": request})
        return msgs

    def generate(self, request: str, known_tags: dict[str, str] | None = None,
                 descriptions: dict[str, str] | None = None, catalog: Catalog | None = None,
                 compiler_kw: dict | None = None, string_types: set[str] | None = None) -> Result:
        t0 = time.perf_counter()
        res = Result(request, None, None)
        tags = pick_tags(request, known_tags or {}, descriptions)
        msgs = self.messages(request, tags)
        idents = request_identifiers(request)
        allowed = set(known_tags or {}) | idents
        # statements of the examples shown; a reply that repeats one copied the example
        example_stmts = set()
        for ex in self.shown_examples(request):
            try:
                example_stmts |= {format_statement(s) for s in parse_spec(ex["spec"])}
            except SpecError:
                pass
        grammar = None
        if getattr(self.client, "supports_grammar", False):
            from generate.gbnf import build_gbnf
            types = dict(known_tags or {})
            # names the request writes but that do not look like tags (Beacon, A, D) must be writable too,
            # or the grammar forces the model onto some other existing tag
            types.update({i: "ANY" for i in idents | plain_names(request) if i not in types})
            grammar = build_gbnf(types, allow_new_tags=not allowed)
        for attempt in range(self.retries + 1):
            last = attempt == self.retries
            if grammar:
                try:
                    reply = self.client.chat(msgs, grammar=grammar)
                except LLMError as e:
                    if "rejected the grammar" not in str(e):
                        raise
                    res.warnings.append(f"grammar not accepted by the server, continuing without it: {e}")
                    grammar = None
                    reply = self.client.chat(msgs)
            else:
                reply = self.client.chat(msgs)
            spec = extract_spec(reply)
            error = None
            if not spec:
                error = "no LogicSpec statement found; reply with statements ending in ';' only"
            else:
                try:
                    if allowed:
                        spec, fixes = snap_tags(spec, allowed)
                        res.warnings += [f"tag name corrected: {f}" for f in fixes]
                    used = spec_tags(spec)
                    # an example repeated word for word is fine if it is about this request
                    # (same words in its tag names); otherwise the model copied an unrelated example
                    rw = _words(request)
                    copied = []
                    for st in parse_spec(spec):
                        text = format_statement(st)
                        if text in example_stmts:
                            tw = set().union(*(_words(t) for t in spec_tags(text))) or {""}
                            if len(tw & rw) / len(tw) < 0.5:
                                copied.append(text)
                    if copied:
                        raise SpecError(f"'{copied[0]}' is copied from the examples; "
                                        "write logic only for this request, using its tag names")
                    if allowed and not last:
                        # a name written in the request counts, even a plain word (Beacon) or a letter (D)
                        written = {u for u in used if re.search(rf"(?<![\w.]){re.escape(u)}(?![\w])", request)}
                        for u in sorted(used - allowed - written):
                            close = difflib.get_close_matches(u, sorted(allowed), n=1, cutoff=0.6)
                            if close:
                                raise SpecError(f"tag {u} is not in the request; did you mean {close[0]}? "
                                                "Use tag names exactly as written")
                    # every tag the request names is a condition or an output; one left out is usually a
                    # dropped interlock ("..., and Batch_Request is on"), which no other check would see
                    have = {_norm(u) for u in used}
                    missing = sorted(n for n in idents if _norm(n) not in have)
                    # a near-twin used in place of a named tag (Flow_SP for Flow_Setpoint) is another tag:
                    # the row would build and write the wrong one, so on the last attempt it fails the row
                    named = {_norm(i) for i in idents}
                    others = sorted({u.split(".")[0] for u in used if _norm(u.split(".")[0]) not in named})
                    twins = {n: c[0] for n in missing
                             if (c := difflib.get_close_matches(n, others, n=1, cutoff=0.6))}
                    if twins:
                        said = "; ".join(f"it names {n}, the logic uses {u}" for n, u in twins.items())
                        raise SpecError(f"{said}: a similar name is a different tag. Use the tag names exactly "
                                        "as the request writes them")
                    if missing and not last:
                        raise SpecError(f"the request names {', '.join(missing)} but the logic does not use "
                                        f"{'it' if len(missing) == 1 else 'them'}; every condition and "
                                        "output in the request must be in the logic")
                    if missing:
                        res.warnings.append(f"the request names {', '.join(missing)}, which the logic does not use")
                    stmts = parse_spec(spec)
                    for problem in output_problems(stmts, request, idents, known_tags):
                        if not last:
                            raise SpecError(problem)
                        res.warnings.append(problem)
                    compiled = Compiler(known_tags=known_tags, catalog=catalog,
                                        **(compiler_kw or {})).compile(stmts)
                    types = dict(known_tags or {})
                    types.update({t.name: t.datatype for t in compiled.tags.values()})
                    bad = errors(validate(compiled.rungs, types if known_tags else None, catalog=catalog,
                                          revision=(compiler_kw or {}).get("revision"), string_types=string_types))
                    # logic that cannot work as written: worth another attempt (other lint findings are shown)
                    bad += [f for f in check_rungs(compiled.rungs, types, catalog) if f.code in RETRY_CODES]
                    if bad:
                        error = "; ".join(i.message for i in bad[:3])
                    else:
                        res.spec, res.compiled = format_spec(stmts), compiled
                except (SpecError, CompileError) as e:
                    error = str(e).replace("\n", " ")
            res.attempts.append(Attempt(reply, spec, error))
            if error is None:
                break
            msgs = msgs + [{"role": "assistant", "content": reply},
                           {"role": "user", "content": f"That LogicSpec has an error: {error}\n"
                                                       "Reply with the corrected LogicSpec only."}]
        else:
            res.error = f"no valid LogicSpec after {len(res.attempts)} attempts: {res.attempts[-1].error}"
        if res.compiled and known_tags:
            res.warnings += near_miss_warnings(res.compiled, known_tags, request)
        res.seconds = round(time.perf_counter() - t0, 2)
        return res
