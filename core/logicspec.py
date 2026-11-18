"""LogicSpec: the small boolean language the LLM writes instead of rung text.

    Pump := (Start_PB OR Pump) AND NOT Stop_PB AND NOT Fault;
    IF RISE(Reset_PB) THEN RESET Alarm, CLEAR Fault_Code;
    IF TRUE THEN Total := Total + Count;

Rules that make it easy for a small model and impossible to misread:
  * AND and OR may not be mixed at one level; parentheses are mandatory.
  * `tag := expr;` at statement level is always a boolean output (OTE).
  * Inside IF ... THEN, `tag := a [+-*/ b]` is a move or arithmetic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Union

# ---------------------------------------------------------------- AST: expressions


@dataclass(frozen=True)
class Var:
    name: str


@dataclass(frozen=True)
class Not:
    expr: "Expr"


@dataclass(frozen=True)
class And:
    items: tuple["Expr", ...]


@dataclass(frozen=True)
class Or:
    items: tuple["Expr", ...]


@dataclass(frozen=True)
class Cmp:
    op: str  # = <> > < >= <=
    a: str
    b: str


@dataclass(frozen=True)
class Rise:
    expr: "Expr"


@dataclass(frozen=True)
class Delay:
    expr: "Expr"
    ms: int
    off: bool = False  # True = OFFDELAY (TOF)
    timer: str | None = None  # explicit timer tag name


Expr = Union[Var, Not, And, Or, Cmp, Rise, Delay]

# ---------------------------------------------------------------- AST: actions and statements


@dataclass(frozen=True)
class Energize:
    tag: str  # OTE inside IF ... THEN: on while the condition is true, off otherwise


@dataclass(frozen=True)
class SetBit:
    tag: str


@dataclass(frozen=True)
class ResetBit:
    tag: str


@dataclass(frozen=True)
class Clear:
    tag: str


@dataclass(frozen=True)
class ResetAcc:
    tag: str


@dataclass(frozen=True)
class Count:
    tag: str
    preset: int
    down: bool = False


@dataclass(frozen=True)
class StartTimer:
    tag: str
    ms: int
    off: bool = False


@dataclass(frozen=True)
class Copy:
    source: str
    dest: str
    length: str  # number of elements (number or tag)


@dataclass(frozen=True)
class Math:
    dest: str
    a: str
    op: str | None = None  # + - * / or None for a move
    b: str | None = None


Action = Union[Energize, SetBit, ResetBit, Clear, ResetAcc, Count, StartTimer, Copy, Math]


@dataclass(frozen=True)
class Assign:
    target: str
    expr: Expr


@dataclass(frozen=True)
class IfThen:
    cond: Expr | None  # None = unconditional (IF TRUE)
    actions: tuple[Action, ...]


Statement = Union[Assign, IfThen]

CMP_OPS = ("=", "<>", ">", "<", ">=", "<=")
CMP_COMPLEMENT = {"=": "<>", "<>": "=", ">": "<=", "<=": ">", "<": ">=", ">=": "<"}
KEYWORDS = {
    "AND", "OR", "NOT", "IF", "THEN", "TRUE", "SET", "RESET", "CLEAR", "RISE",
    "DELAY", "OFFDELAY", "COUNT_UP", "COUNT_DOWN", "START_TIMER",
    "START_OFF_TIMER", "ON_DELAY_TIMER", "OFF_DELAY_TIMER", "RESET_ACC", "COPY", "ENERGIZE",
}

# ---------------------------------------------------------------- lexer


class SpecError(ValueError):
    pass


@dataclass(frozen=True)
class Tok:
    kind: str  # TAG KW NUM DUR OP EOF
    value: str
    pos: int
    ms: int | None = None


_TOKEN = re.compile(
    r"""
    (?P<ws>\s+|//[^\n]*|\#[^\n]*)
  | (?P<dur>\d+(?:\.\d+)?(?:ms|min|s|m|h)\b)
  | (?P<num>\d+\.\d*(?:[eE][+-]?\d+)?|\d+(?:[eE][+-]?\d+)?|\.\d+)
  | (?P<tag>[A-Za-z_][A-Za-z0-9_]*(?::[A-Za-z0-9_]+)*(?:\.[A-Za-z0-9_]+|\[[^\[\]]*\])*)
  | (?P<op>:=|<>|>=|<=|!=|==|&&|\|\||[=<>(),;+\-*/])
    """,
    re.VERBOSE,
)
_UNIT_MS = {"ms": 1, "s": 1000, "m": 60000, "min": 60000, "h": 3600000}


def _dur_ms(text: str) -> int:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|min|s|m|h)", text)
    ms = float(m.group(1)) * _UNIT_MS[m.group(2)]
    if ms != int(ms):
        raise SpecError(f"duration {text} is not a whole number of milliseconds")
    return int(ms)


_OP_ALIAS = {"!=": ("OP", "<>"), "==": ("OP", "="), "&&": ("KW", "AND"), "||": ("KW", "OR")}
_ACTION_KW = {"SET", "RESET", "CLEAR", "RESET_ACC", "ENERGIZE", "COUNT_UP", "COUNT_DOWN", "START_TIMER",
              "START_OFF_TIMER", "ON_DELAY_TIMER", "OFF_DELAY_TIMER", "COPY"}


def tokenize(text: str) -> list[Tok]:
    toks, i = [], 0
    while i < len(text):
        m = _TOKEN.match(text, i)
        if not m:
            raise SpecError(f"unexpected character {text[i]!r} at {i + 1}")
        kind = m.lastgroup
        val = m.group()
        if kind == "tag" and val.upper() in KEYWORDS:
            toks.append(Tok("KW", val.upper(), i))
        elif kind == "dur":
            toks.append(Tok("DUR", val, i, _dur_ms(val)))
        elif kind == "op" and val in _OP_ALIAS:  # forms small models write: != == && ||
            k2, v2 = _OP_ALIAS[val]
            toks.append(Tok(k2, v2, i))
        elif kind != "ws":
            toks.append(Tok(kind.upper(), val, i))
        i = m.end()
    toks.append(Tok("EOF", "", len(text)))
    return toks


# ---------------------------------------------------------------- parser


class _P:
    def __init__(self, text: str):
        self.text = text
        self.toks = tokenize(text)
        self.k = 0

    @property
    def cur(self) -> Tok:
        return self.toks[self.k]

    def err(self, msg: str):
        t = self.cur
        shown = t.value or "end of input"
        raise SpecError(f"{msg} (got {shown!r} at {t.pos + 1})")

    def accept(self, kind: str, value: str | None = None) -> Tok | None:
        t = self.cur
        if t.kind == kind and (value is None or t.value == value):
            self.k += 1
            return t
        return None

    def expect(self, kind: str, value: str | None = None, what: str | None = None) -> Tok:
        t = self.accept(kind, value)
        if not t:
            self.err(f"expected {what or value or kind}")
        return t

    # program
    def program(self) -> list[Statement]:
        out = []
        while self.cur.kind != "EOF":
            out.append(self.statement())
        if not out:
            raise SpecError("empty specification")
        return out

    def statement(self) -> Statement:
        if self.accept("KW", "IF"):
            cond = None if self.accept("KW", "TRUE") else self.expr()
            self.expect("KW", "THEN")
            acts = [self.action()]
            while self.accept("OP", ","):
                acts.append(self.action())
            self.expect("OP", ";")
            return IfThen(cond, tuple(acts))
        if self.cur.kind == "KW" and self.cur.value in _ACTION_KW:
            self.err(f"{self.cur.value} is an action and needs a condition: "
                     f"IF condition THEN {self.cur.value} ...; (or IF TRUE THEN ... for always)")
        tgt = self.expect("TAG", what="a tag or IF").value
        if self.cur.kind == "OP" and self.cur.value == "=":
            self.err("assign with := not =")
        self.expect("OP", ":=")
        nxt = self.toks[self.k + 1] if self.k + 1 < len(self.toks) else None
        if self.cur.kind == "NUM" or (self.cur.kind == "TAG" and nxt and nxt.kind == "OP"
                                      and nxt.value in "+-*/" and nxt.value):
            self.err(f"math and moves go inside IF: IF condition THEN {tgt} := ...; "
                     f"('{tgt} := condition;' is only for turning a bit on and off)")
        if self.cur.kind == "KW" and self.cur.value == "TRUE":
            self.err(f"write '{tgt} := condition;' (on while true), or IF condition THEN SET {tgt};")
        e = self.expr()
        self.expect("OP", ";")
        return Assign(tgt, e)

    def expr(self) -> Expr:
        first = self.unary()
        if self.cur.kind == "KW" and self.cur.value in ("AND", "OR"):
            op = self.cur.value
            items = [first]
            while self.accept("KW", op):
                items.append(self.unary())
            if self.cur.kind == "KW" and self.cur.value in ("AND", "OR"):
                self.err("AND and OR mixed without parentheses; group them explicitly")
            return And(tuple(items)) if op == "AND" else Or(tuple(items))
        return first

    def unary(self) -> Expr:
        if self.accept("KW", "NOT"):
            return Not(self.unary())
        return self.atom()

    def atom(self) -> Expr:
        if self.accept("OP", "("):
            e = self.expr()
            self.expect("OP", ")")
            return e
        if self.accept("KW", "RISE"):
            self.expect("OP", "(")
            e = self.expr()
            self.expect("OP", ")")
            return Rise(e)
        for kw, off in (("DELAY", False), ("OFFDELAY", True)):
            if self.accept("KW", kw):
                self.expect("OP", "(")
                e = self.expr()
                self.expect("OP", ",")
                ms = self.expect("DUR", what="a duration like 5s or 500ms").ms
                name = None
                if self.accept("OP", ","):
                    name = self.expect("TAG", what="a timer tag").value
                self.expect("OP", ")")
                return Delay(e, ms, off, name)
        if self.cur.kind == "KW" and self.cur.value == "TRUE":
            self.err("TRUE is only allowed as the whole condition: IF TRUE THEN ...")
        a = self.operand(what="a tag, comparison, RISE, DELAY or '('")
        if self.cur.kind == "OP" and self.cur.value in CMP_OPS:
            op = self.cur.value
            self.k += 1
            b = self.operand()
            return Cmp(op, a, b)
        if not _is_tag(a):
            self.err(f"a number ({a}) can only be used in a comparison")
        return Var(a)

    def operand(self, what: str = "a tag or number") -> str:
        neg = "-" if self.accept("OP", "-") else ""
        t = self.accept("NUM")
        if t:
            return neg + t.value
        if neg:
            self.err("expected a number after '-'")
        t = self.accept("TAG")
        if t:
            return t.value
        self.err(f"expected {what}")

    def action(self) -> Action:
        simple = {"SET": SetBit, "RESET": ResetBit, "CLEAR": Clear, "RESET_ACC": ResetAcc, "ENERGIZE": Energize}
        if self.cur.kind == "KW" and self.cur.value in simple:
            cls = simple[self.cur.value]
            self.k += 1
            paren = self.accept("OP", "(")  # SET(X) is accepted as SET X
            tag = self.expect("TAG", what="a tag").value
            if paren:
                self.expect("OP", ")")
            return cls(tag)
        for kw, down in (("COUNT_UP", False), ("COUNT_DOWN", True)):
            if self.accept("KW", kw):
                self.expect("OP", "(")
                tag = self.expect("TAG", what="a counter tag").value
                self.expect("OP", ",")
                n = self.expect("NUM", what="a whole-number preset").value
                if not n.isdigit():
                    self.err("counter preset must be a whole number")
                self.expect("OP", ")")
                return Count(tag, int(n), down)
        # ON_/OFF_DELAY_TIMER mirror the English "on-delay"/"off-delay"; START_* are older aliases
        for kw, off in (("ON_DELAY_TIMER", False), ("OFF_DELAY_TIMER", True),
                        ("START_TIMER", False), ("START_OFF_TIMER", True)):
            if self.accept("KW", kw):
                self.expect("OP", "(")
                tag = self.expect("TAG", what="a timer tag").value
                self.expect("OP", ",")
                ms = self.expect("DUR", what="a duration like 5s").ms
                self.expect("OP", ")")
                return StartTimer(tag, ms, off)
        if self.accept("KW", "COPY"):
            self.expect("OP", "(")
            src = self.expect("TAG", what="a source tag").value
            self.expect("OP", ",")
            dst = self.expect("TAG", what="a destination tag").value
            self.expect("OP", ",")
            n = self.operand(what="a length")
            self.expect("OP", ")")
            return Copy(src, dst, n)
        dest = self.expect("TAG", what="an action").value
        self.expect("OP", ":=")
        a = self.operand()
        if self.cur.kind == "OP" and self.cur.value in "+-*/" and self.cur.value:
            op = self.cur.value
            self.k += 1
            return Math(dest, a, op, self.operand())
        return Math(dest, a)


def _is_tag(s: str) -> bool:
    return bool(re.match(r"[A-Za-z_]", s))


def parse_spec(text: str) -> list[Statement]:
    return _P(text).program()


def parse_expr(text: str) -> Expr:
    p = _P(text)
    e = p.expr()
    if p.cur.kind != "EOF":
        p.err("unexpected text after expression")
    return e


# ---------------------------------------------------------------- formatter


def fmt_ms(ms: int) -> str:
    if ms % 3600000 == 0:
        return f"{ms // 3600000}h"
    if ms % 60000 == 0:
        return f"{ms // 60000}min"
    if ms % 1000 == 0:
        return f"{ms // 1000}s"
    return f"{ms}ms"


def format_expr(e: Expr, parent: str | None = None) -> str:
    if isinstance(e, Var):
        return e.name
    if isinstance(e, Cmp):
        return f"{e.a} {e.op} {e.b}"
    if isinstance(e, Not):
        inner = format_expr(e.expr, "NOT")
        return f"NOT {inner}"
    if isinstance(e, Rise):
        return f"RISE({format_expr(e.expr)})"
    if isinstance(e, Delay):
        kw = "OFFDELAY" if e.off else "DELAY"
        name = f", {e.timer}" if e.timer else ""
        return f"{kw}({format_expr(e.expr)}, {fmt_ms(e.ms)}{name})"
    if isinstance(e, (And, Or)):
        op = "AND" if isinstance(e, And) else "OR"
        s = f" {op} ".join(format_expr(i, op) for i in e.items)
        return f"({s})" if parent is not None else s
    raise TypeError(e)


def format_action(a: Action) -> str:
    if isinstance(a, Energize):
        return f"ENERGIZE {a.tag}"
    if isinstance(a, SetBit):
        return f"SET {a.tag}"
    if isinstance(a, ResetBit):
        return f"RESET {a.tag}"
    if isinstance(a, Clear):
        return f"CLEAR {a.tag}"
    if isinstance(a, ResetAcc):
        return f"RESET_ACC {a.tag}"
    if isinstance(a, Count):
        return f"{'COUNT_DOWN' if a.down else 'COUNT_UP'}({a.tag}, {a.preset})"
    if isinstance(a, StartTimer):
        return f"{'OFF_DELAY_TIMER' if a.off else 'ON_DELAY_TIMER'}({a.tag}, {fmt_ms(a.ms)})"
    if isinstance(a, Copy):
        return f"COPY({a.source}, {a.dest}, {a.length})"
    if isinstance(a, Math):
        return f"{a.dest} := {a.a}" + (f" {a.op} {a.b}" if a.op else "")
    raise TypeError(a)


def format_statement(s: Statement) -> str:
    if isinstance(s, Assign):
        return f"{s.target} := {format_expr(s.expr)};"
    cond = "TRUE" if s.cond is None else format_expr(s.cond)
    return f"IF {cond} THEN {', '.join(format_action(a) for a in s.actions)};"


def format_spec(stmts: list[Statement]) -> str:
    return "\n".join(format_statement(s) for s in stmts)
