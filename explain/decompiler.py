"""Turn existing rungs back into LogicSpec.

Used to mine few-shot examples from real projects and to explain rungs.
Only rungs of the shape "conditions, then outputs" convert; anything else
is reported as not convertible with a reason. Nothing is forced.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.rung import Branch, Instr, Rung, Series, is_literal, walk
from core.logicspec import (
    And, Assign, Clear, Cmp, Copy, Count, Energize, Expr, IfThen, Math, Not, Or, ResetAcc, ResetBit, Rise,
    SetBit, StartTimer, Statement, Var,
)

INSTR_CMP = {"EQU": "=", "NEQ": "<>", "GRT": ">", "LES": "<", "GEQ": ">=", "LEQ": "<=",
             "EQ": "=", "NE": "<>", "GT": ">", "LT": "<", "GE": ">=", "LE": "<="}  # v35 and v36+ names
INSTR_MATH = {"ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/"}
_OUTPUTS = {"OTE", "OTL", "OTU", "CLR", "RES", "MOV", "MOVE", "COP", "ADD", "SUB", "MUL", "DIV",
            "TON", "TOF", "CTU", "CTD"}


class NotConvertible(ValueError):
    pass


@dataclass
class Decompiled:
    statements: list[Statement]


def _cond_elem(e) -> Expr:
    if isinstance(e, Branch):
        return Or(tuple(_cond_series(l) for l in e.legs))
    n = e.name.upper()
    if n == "XIC":
        return Var(e.args[0])
    if n == "XIO":
        return Not(Var(e.args[0]))
    if n in INSTR_CMP:
        return Cmp(INSTR_CMP[n], e.args[0], e.args[1])
    if n == "ONS":
        raise NotConvertible("ONS inside a branch or after another ONS")
    raise NotConvertible(f"{e.name} is not a condition LogicSpec can express")


def _cond_series(s: Series) -> Expr:
    if not s.items:
        raise NotConvertible("empty branch leg (always-true path)")
    parts = [_cond_elem(i) for i in s.items]
    return parts[0] if len(parts) == 1 else And(tuple(_flatten_and(parts)))


def _flatten_and(parts):
    for p in parts:
        if isinstance(p, And):
            yield from p.items
        else:
            yield p


def _is_output(e) -> bool:
    return isinstance(e, Instr) and e.name.upper() in _OUTPUTS


def _preset(tag: str, display: tuple[str, ...], presets: dict[str, int]) -> int:
    if tag in presets:
        return int(presets[tag])
    if display and is_literal(display[0]):
        return int(float(display[0]))
    raise NotConvertible(f"preset of {tag} unknown (shown as '?'; pass tag data)")


def _action(i: Instr, presets: dict[str, int]):
    n, a = i.name.upper(), i.args
    if n == "OTE":
        return Energize(a[0])
    if n == "OTL":
        return SetBit(a[0])
    if n == "OTU":
        return ResetBit(a[0])
    if n == "CLR":
        return Clear(a[0])
    if n == "RES":
        return ResetAcc(a[0])
    if n in ("MOV", "MOVE"):
        return Math(a[1], a[0])
    if n == "COP":
        return Copy(a[0], a[1], a[2])
    if n in INSTR_MATH:
        return Math(a[2], a[0], INSTR_MATH[n], a[1])
    if n in ("CTU", "CTD"):
        return Count(a[0], _preset(a[0], a[1:], presets), n == "CTD")
    if n in ("TON", "TOF"):
        return StartTimer(a[0], _preset(a[0], a[1:], presets), n == "TOF")
    raise NotConvertible(f"{i.name} has no LogicSpec action")


def decompile_rung(r: Rung, presets: dict[str, int] | None = None) -> list[Statement]:
    presets = presets or {}
    items = list(r.body.items)
    if not items:
        raise NotConvertible("empty rung")
    last = items[-1]
    if _is_output(last):
        outs, conds = [last], items[:-1]
    elif isinstance(last, Branch) and all(
        len(l.items) == 1 and _is_output(l.items[0]) for l in last.legs
    ):
        outs, conds = [l.items[0] for l in last.legs], items[:-1]
    else:
        raise NotConvertible("rung does not end in outputs only")
    for c in conds:
        for ins in walk(c):
            if ins.name.upper() in _OUTPUTS:
                raise NotConvertible(f"output {ins.name} in the middle of the rung")

    # one ONS allowed, at top level: everything to its left becomes RISE(...)
    ons_at = [k for k, c in enumerate(conds) if isinstance(c, Instr) and c.name.upper() == "ONS"]
    if len(ons_at) > 1:
        raise NotConvertible("more than one ONS in the rung")
    parts: list[Expr] = []
    if ons_at:
        k = ons_at[0]
        if k == 0:
            raise NotConvertible("ONS with nothing to its left")
        parts.append(Rise(_cond_series(Series(tuple(conds[:k])))))
        conds = conds[k + 1:]
    parts += [_cond_elem(c) for c in conds]
    cond: Expr | None
    if not parts:
        cond = None
    elif len(parts) == 1:
        cond = parts[0]
    else:
        cond = And(tuple(_flatten_and(parts)))

    if len(outs) == 1 and outs[0].name.upper() == "OTE":
        if cond is None:
            raise NotConvertible("OTE with no condition (always on)")
        return [Assign(outs[0].args[0], cond)]
    return [IfThen(cond, tuple(_action(o, presets) for o in outs))]


def try_decompile(r: Rung, presets: dict[str, int] | None = None) -> tuple[list[Statement] | None, str | None]:
    try:
        return decompile_rung(r, presets), None
    except NotConvertible as e:
        return None, str(e)
