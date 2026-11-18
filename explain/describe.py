"""Deterministic English read-back of LogicSpec.

Used to (1) let the user confirm intent before import, (2) write rung
comments, (3) generate description -> LogicSpec pairs from existing code
for few-shot retrieval. Wording is plain on purpose: the user must be
able to spot a wrong AND/OR at a glance.
"""

from __future__ import annotations

from core.logicspec import (
    And, Assign, Clear, Cmp, Copy, Count, Energize, Delay, Expr, IfThen, Math, Not, Or, ResetAcc, ResetBit,
    Rise, SetBit, StartTimer, Statement, Var, fmt_ms,
)

_CMP_WORDS = {
    "=": "equals", "<>": "does not equal", ">": "is greater than",
    "<": "is less than", ">=": "is at least", "<=": "is at most",
}
_MATH_WORDS = {"+": "plus", "-": "minus", "*": "times", "/": "divided by"}


def describe_expr(e: Expr, nested: bool = False) -> str:
    if isinstance(e, Var):
        return f"{e.name} is on"
    if isinstance(e, Not) and isinstance(e.expr, Var):
        return f"{e.expr.name} is off"
    if isinstance(e, Not):
        return f"it is not true that ({describe_expr(e.expr)})"
    if isinstance(e, Cmp):
        return f"{e.a} {_CMP_WORDS[e.op]} {e.b}"
    if isinstance(e, Rise):
        return f"the moment ({describe_expr(e.expr)}) becomes true"
    if isinstance(e, Delay):
        if e.off:
            return f"({describe_expr(e.expr)}) is true or became false less than {fmt_ms(e.ms)} ago"
        return f"({describe_expr(e.expr)}) has been true for {fmt_ms(e.ms)}"
    if isinstance(e, And):
        s = " AND ".join(describe_expr(i, True) for i in e.items)
        return f"({s})" if nested else s
    if isinstance(e, Or):
        s = " OR ".join(describe_expr(i, True) for i in e.items)
        return f"(either {s})" if nested else f"either {s}"
    raise TypeError(e)


def describe_action(a) -> str:
    if isinstance(a, Energize):
        return f"turn on {a.tag} (off again when the condition is false)"
    if isinstance(a, SetBit):
        return f"latch {a.tag} on"
    if isinstance(a, ResetBit):
        return f"unlatch {a.tag}"
    if isinstance(a, Clear):
        return f"set {a.tag} to 0"
    if isinstance(a, ResetAcc):
        return f"reset {a.tag}"
    if isinstance(a, Count):
        return f"count {'down' if a.down else 'up'} {a.tag} (preset {a.preset}) on each rising edge"
    if isinstance(a, StartTimer):
        kind = "off-delay" if a.off else "on-delay"
        return f"run {kind} timer {a.tag} ({fmt_ms(a.ms)})"
    if isinstance(a, Copy):
        return f"copy {a.length} element(s) from {a.source} to {a.dest}"
    if isinstance(a, Math):
        if a.op is None:
            return f"copy {a.a} into {a.dest}"
        return f"set {a.dest} to {a.a} {_MATH_WORDS[a.op]} {a.b}"
    raise TypeError(a)


def describe_statement(s: Statement) -> str:
    if isinstance(s, Assign):
        return f"{s.target} is on while {describe_expr(s.expr)}; otherwise off."
    acts = "; ".join(describe_action(a) for a in s.actions)
    if s.cond is None:
        return f"Every scan: {acts}."
    return f"When {describe_expr(s.cond)}: {acts}."
