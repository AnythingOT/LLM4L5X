"""Compile LogicSpec into ladder rungs. Deterministic; no model involved.

AND -> series, OR -> branch, NOT pushed down to contacts (De Morgan),
comparisons negated by complement. RISE and DELAY may add helper rungs
before the rung that uses them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.catalog import Catalog, default_catalog, major_version
from core.rung import Branch, Instr, Rung, Series, base_tag, is_literal, is_plain_tag, walk
from core.logicspec import (
    And, Assign, Clear, Cmp, CMP_COMPLEMENT, Copy, Count, Energize, Delay, Expr, IfThen, Math, Not, Or,
    ResetAcc, ResetBit, Rise, SetBit, SpecError, StartTimer, Statement, Var, format_statement,
    parse_spec,
)
from explain.describe import describe_statement

CMP_INSTR = {"=": "EQU", "<>": "NEQ", ">": "GRT", "<": "LES", ">=": "GEQ", "<=": "LEQ"}
MATH_INSTR = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV"}

# Logix tag name rules: letter or underscore first, then letters, digits,
# underscores; no consecutive or trailing underscores; at most 40 characters.
_TAG_RULE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def tag_name_problem(name: str) -> str | None:
    if not _TAG_RULE.fullmatch(name):
        return "must start with a letter or underscore and use only letters, digits, underscores"
    if "__" in name:
        return "must not contain consecutive underscores"
    if name.endswith("_"):
        return "must not end with an underscore"
    if len(name) > 40:
        return "must be at most 40 characters"
    return None


class CompileError(SpecError):
    pass


@dataclass
class TagDef:
    name: str
    datatype: str  # BOOL DINT REAL TIMER COUNTER
    preset: int | None = None
    description: str | None = None
    allocated: bool = False  # created by the compiler, not named by the user


@dataclass
class CompileResult:
    rungs: list[Rung]
    tags: dict[str, TagDef]  # new tags to create
    statements: list[Statement]
    warnings: list[str] = field(default_factory=list)

    @property
    def texts(self) -> list[str]:
        from core.rung import format_rung
        return [format_rung(r) for r in self.rungs]


class Compiler:
    def __init__(
        self,
        known_tags: dict[str, str] | None = None,
        prefix: str = "L4X",
        display_operands: str = "placeholder",
        comments: bool = True,
        catalog: Catalog | None = None,
        revision: str | None = None,
    ):
        """
        known_tags: existing project tags {name: datatype}; not re-created, checked for type.
        revision: target Logix Designer version ("36.00"). v36+ uses the IEC mnemonics
            (EQ, GT, MOVE ...); earlier or unknown versions use EQU, GRT, MOV ...
        display_operands: "placeholder" writes TON(T,?,?); "values" writes TON(T,5000,0).
            Real exports always use "?" (docs/DESIGN.md section 9); "values" is a fallback.
        """
        if display_operands not in ("placeholder", "values"):
            raise ValueError("display_operands must be 'placeholder' or 'values'")
        self.known = {k: v.upper() for k, v in (known_tags or {}).items()}
        self.prefix = prefix
        self.display = display_operands
        self.comments = comments
        self.cat = catalog or default_catalog()
        self.major = major_version(revision)
        self._counter: dict[str, int] = {}
        self.tags: dict[str, TagDef] = {}
        self.warnings: list[str] = []
        self._helpers: list[Rung] = []
        self._user_names: set[str] = set()

    # ------------------------------------------------------------ naming

    def _alloc(self, kind: str, datatype: str, desc: str) -> str:
        while True:
            n = self._counter.get(kind, 0) + 1
            self._counter[kind] = n
            name = f"{self.prefix}_{kind}_{n}"
            if name not in self.known and name not in self.tags and name not in self._user_names:
                break
        self.tags[name] = TagDef(name, datatype, description=desc, allocated=True)
        return name

    def _struct_tag(self, name: str, datatype: str, preset: int) -> None:
        if not is_plain_tag(name):
            raise CompileError(f"{datatype.lower()} tag {name!r} must be a plain tag name")
        if name in self.known:
            if self.known[name] != datatype:
                raise CompileError(f"{name} is a {self.known[name]} in the project, used as {datatype}")
            self.warnings.append(
                f"{name} already exists; its preset is set in the project, not by this import ({preset})"
            )
            return
        prev = self.tags.get(name)
        if prev:
            if prev.datatype != datatype:
                raise CompileError(f"{name} used as both {prev.datatype} and {datatype}")
            if prev.preset != preset:
                raise CompileError(f"{name} given two presets: {prev.preset} and {preset}")
            return
        self.tags[name] = TagDef(name, datatype, preset)

    def _display(self, preset: int) -> tuple[str, str]:
        return ("?", "?") if self.display == "placeholder" else (str(preset), "0")

    # ------------------------------------------------------------ conditions

    def cond(self, e: Expr, neg: bool, first: bool) -> list:
        """Return series items for expression e (negated if neg).

        `first` is True when nothing is to the left of this position on the
        power path; RISE can then be compiled inline as an ONS.
        """
        if isinstance(e, Var):
            return [Instr("XIO" if neg else "XIC", (e.name,))]
        if isinstance(e, Cmp):
            op = CMP_COMPLEMENT[e.op] if neg else e.op
            return [Instr(CMP_INSTR[op], (e.a, e.b))]
        if isinstance(e, Not):
            return self.cond(e.expr, not neg, first)
        if isinstance(e, (And, Or)):
            series = isinstance(e, And) != neg  # De Morgan swaps AND/OR under NOT
            if series:
                out = []
                for i, item in enumerate(e.items):
                    out += self.cond(item, neg, first and i == 0)
                return out
            legs = []
            for item in e.items:
                leg = Series(tuple(self.cond(item, neg, first)))
                # flatten OR-of-OR: a leg that is just a branch contributes its legs
                if len(leg.items) == 1 and isinstance(leg.items[0], Branch):
                    legs += leg.items[0].legs
                else:
                    legs.append(leg)
            return [Branch(tuple(legs))]
        if isinstance(e, Rise):
            if neg:
                raise CompileError("NOT RISE(...) has no ladder equivalent; restate the condition")
            ons = self._alloc("ONS", "BOOL", "One-shot storage bit")
            if first:
                return self.cond(e.expr, False, True) + [Instr("ONS", (ons,))]
            # Not at the start of the power path: an inline ONS would see
            # everything to its left. Compute the edge on its own rung.
            edge = self._alloc("EDGE", "BOOL", "Rising edge, true for one scan")
            body = self.cond(e.expr, False, True) + [Instr("ONS", (ons,)), Instr("OTE", (edge,))]
            self._helpers.append(Rung(Series(tuple(body)), self._c(f"Helper: rising edge of {_short(e.expr)}")))
            return [Instr("XIO" if neg else "XIC", (edge,))]
        if isinstance(e, Delay):
            name = e.timer
            dtype = "TIMER"
            if name:
                self._struct_tag(name, dtype, e.ms)
            else:
                name = self._alloc("TMR", dtype, "On-delay timer" if not e.off else "Off-delay timer")
                self.tags[name].preset = e.ms
            pre, acc = self._display(e.ms)
            body = self.cond(e.expr, False, True) + [Instr("TOF" if e.off else "TON", (name, pre, acc))]
            kind = "off-delay" if e.off else "on-delay"
            self._helpers.append(Rung(Series(tuple(body)), self._c(f"Helper: {kind} {e.ms} ms for {_short(e.expr)}")))
            return [Instr("XIO" if neg else "XIC", (f"{name}.DN",))]
        raise TypeError(e)

    # ------------------------------------------------------------ actions

    def action(self, a) -> Instr:
        if isinstance(a, Energize):
            return Instr("OTE", (a.tag,))
        if isinstance(a, SetBit):
            return Instr("OTL", (a.tag,))
        if isinstance(a, ResetBit):
            return Instr("OTU", (a.tag,))
        if isinstance(a, Clear):
            return Instr("CLR", (a.tag,))
        if isinstance(a, ResetAcc):
            return Instr("RES", (a.tag,))
        if isinstance(a, Count):
            self._struct_tag(a.tag, "COUNTER", a.preset)
            return Instr("CTD" if a.down else "CTU", (a.tag, *self._display(a.preset)))
        if isinstance(a, StartTimer):
            self._struct_tag(a.tag, "TIMER", a.ms)
            return Instr("TOF" if a.off else "TON", (a.tag, *self._display(a.ms)))
        if isinstance(a, Copy):
            return Instr("COP", (a.source, a.dest, a.length))
        if isinstance(a, Math):
            if is_literal(a.dest):
                raise CompileError(f"cannot write to a number: {a.dest}")
            if a.op is None:
                return Instr("MOV", (a.a, a.dest))
            return Instr(MATH_INSTR[a.op], (a.a, a.b, a.dest))
        raise TypeError(a)

    # ------------------------------------------------------------ statements

    def _c(self, text: str) -> str | None:
        return text if self.comments else None

    def statement(self, s: Statement) -> list[Rung]:
        self._helpers = []
        if isinstance(s, Assign):
            items = self.cond(s.expr, False, True) + [Instr("OTE", (s.target,))]
        else:
            items = self.cond(s.cond, False, True) if s.cond is not None else []
            outs = [self.action(a) for a in s.actions]
            if len(outs) == 1:
                items += outs
            else:
                items.append(Branch(tuple(Series((o,)) for o in outs)))
        comment = self._c(describe_statement(s))
        main = Rung(Series(tuple(items)), comment)
        return self._helpers + [main]

    def compile(self, stmts: list[Statement]) -> CompileResult:
        self._user_names = _names_in(stmts)
        rungs: list[Rung] = []
        for s in stmts:
            try:
                rungs += self.statement(s)
            except CompileError as e:
                raise CompileError(f"{format_statement(s)}\n  -> {e}") from None
        if self.major is not None and self.major >= 36:
            rungs = [Rung(_rename(r.body, self.cat), r.comment) for r in rungs]
        self._type_tags(rungs)
        return CompileResult(rungs, self.tags, stmts, self.warnings)

    # ------------------------------------------------------------ tag typing

    def _type_tags(self, rungs: list[Rung], skip_unknown: bool = False) -> None:
        """Infer data types for plain tags from the operand types they are used in."""
        want: dict[str, set[str]] = {}
        member_refs: set[str] = set()
        untyped: set[str] = set()
        for r in rungs:
            for ins in walk(r.body):
                spec = self.cat.get(ins.name)
                if spec is None:
                    if skip_unknown:
                        continue
                    raise CompileError(f"compiler produced unknown instruction {ins.name}")
                floats = any(is_literal(x) and _is_float(x) for x in ins.args)
                for op, arg in zip(spec.operands, ins.args):
                    if op.role == "display" or is_literal(arg) or arg == "?":
                        continue
                    if not is_plain_tag(arg):
                        member_refs.add(base_tag(arg) or arg)
                        continue
                    t = {"BOOL": "BOOL", "TIMER": "TIMER", "COUNTER": "COUNTER"}.get(op.type)
                    if t is None and op.type in ("NUMERIC", "COMPARABLE"):
                        t = "REAL" if floats else "DINT"
                    if t:
                        want.setdefault(arg, set()).add(t)
                    else:
                        untyped.add(arg)
        for name, types in want.items():
            if "DINT" in types and "REAL" in types:
                types.discard("DINT")  # mixed numeric use: REAL is the safe choice
            if len(types) > 1:
                raise CompileError(f"{name} used as {' and '.join(sorted(types))}")
            t = types.pop()
            if name in self.known:
                kt = self.known[name]
                numeric = {"SINT", "INT", "DINT", "LINT", "REAL", "LREAL", "USINT", "UINT", "UDINT", "ULINT"}
                if t == kt or (t in ("DINT", "REAL") and kt in numeric) or (
                        t in ("DINT", "REAL") and kt not in ("BOOL", "TIMER", "COUNTER")):
                    # an existing STRING/UDT in a comparison or move is the project's business
                    continue
                raise CompileError(f"{name} is a {kt} in the project but is used as {t}")
            if name in self.tags:
                if self.tags[name].datatype != t:
                    raise CompileError(f"{name} used as {self.tags[name].datatype} and {t}")
                continue
            problem = tag_name_problem(name)
            if problem:
                raise CompileError(f"tag name {name!r} {problem}")
            self.tags[name] = TagDef(name, t)
        for u in sorted(untyped):
            if u not in self.tags and u not in self.known:
                self.warnings.append(f"cannot infer a data type for {u}; it must already exist in the project")
        for b in sorted(member_refs):
            if b not in self.tags and b not in self.known:
                self.warnings.append(f"{b} is used with a member, bit or index; it must already exist in the project")


def infer_tags(rungs: list[Rung], known_tags: dict[str, str] | None = None,
               catalog: Catalog | None = None) -> tuple[dict[str, TagDef], list[str]]:
    """New tags needed by existing rung text (pasted neutral/ASCII), typed from use.

    Timer/counter presets come from literal display operands (TON(T,5000,0));
    with '?' they are unknown and written as 0, with a warning.
    """
    comp = Compiler(known_tags=known_tags, catalog=catalog, comments=False)
    comp._type_tags(rungs, skip_unknown=True)
    for r in rungs:
        for ins in walk(r.body):
            spec = comp.cat.get(ins.name)
            if spec is None or not ins.args:
                continue
            tag = comp.tags.get(ins.args[0])
            if tag and tag.datatype in ("TIMER", "COUNTER"):
                pre = [a for o, a in zip(spec.operands, ins.args) if o.member == "PRE"]
                if pre and is_literal(pre[0]):
                    tag.preset = int(float(pre[0]))
                else:
                    comp.warnings.append(f"preset of new {tag.datatype.lower()} {tag.name} is unknown; "
                                         "it is created with PRE = 0, set it after import")
    return comp.tags, comp.warnings


def _rename(node, cat: Catalog):
    """Rewrite v35 mnemonics to their v36+ names (GRT -> GT, MOV -> MOVE, ...)."""
    if isinstance(node, Instr):
        spec = cat.get(node.name)
        return Instr(spec.renamed_to, node.args) if spec and spec.renamed_to else node
    if isinstance(node, Series):
        return Series(tuple(_rename(i, cat) for i in node.items))
    if isinstance(node, Branch):
        return Branch(tuple(_rename(l, cat) for l in node.legs))
    raise TypeError(node)


def _is_float(s: str) -> bool:
    return bool(re.search(r"[.eE]", s)) and not s.startswith(("16#", "2#", "8#"))


def _short(e: Expr) -> str:
    from core.logicspec import format_expr
    s = format_expr(e)
    return s if len(s) <= 60 else s[:57] + "..."


def _names_in(stmts) -> set[str]:
    text = "\n".join(format_statement(s) for s in stmts)
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text))


def compile_spec(text: str, **kw) -> CompileResult:
    return Compiler(**kw).compile(parse_spec(text))
