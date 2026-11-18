"""Do two LogicSpec programs do the same thing?

Used to score model output against an expected answer. Text equality is too
strict (`A AND B` vs `B AND A`, `N <= 5` vs `NOT N > 5`, one IF with two
actions vs two IFs). Instead each program is reduced to its effects:

    target -> condition       for X := cond
    (action, target) -> cond  for IF cond THEN action

and conditions are compared by truth table. RISE(...) and DELAY(...) are
treated as opaque atoms named by their normalised text.
"""

from __future__ import annotations

import itertools
import random

from core.logicspec import (And, Assign, Cmp, Delay, IfThen, Not, Or, Rise, Var, format_action,
                            format_expr, parse_spec)

# a <op> b with op in {<=, <, <>} becomes NOT (a <op'> b), so N <= 5 and NOT N > 5 match
_FLIP = {"<=": ">", "<": ">=", "<>": "="}


def _norm(e):
    if isinstance(e, Cmp):
        if e.op in _FLIP:
            return Not(Cmp(_FLIP[e.op], e.a, e.b))
        return e
    if isinstance(e, Not):
        return Not(_norm(e.expr))
    if isinstance(e, And):
        return And(tuple(_norm(i) for i in e.items))
    if isinstance(e, Or):
        return Or(tuple(_norm(i) for i in e.items))
    if isinstance(e, Rise):
        return Rise(_norm(e.expr))
    if isinstance(e, Delay):
        return Delay(_norm(e.expr), e.ms, e.off, None)  # timer name does not matter
    return e


def _atom_key(e) -> str:
    return format_expr(e)


def _atoms(e, out: set):
    if isinstance(e, (Var, Cmp, Rise, Delay)):
        out.add(_atom_key(e))
    elif isinstance(e, Not):
        _atoms(e.expr, out)
    elif isinstance(e, (And, Or)):
        for i in e.items:
            _atoms(i, out)


def _eval(e, env) -> bool:
    if isinstance(e, (Var, Cmp, Rise, Delay)):
        return env[_atom_key(e)]
    if isinstance(e, Not):
        return not _eval(e.expr, env)
    if isinstance(e, And):
        return all(_eval(i, env) for i in e.items)
    if isinstance(e, Or):
        return any(_eval(i, env) for i in e.items)
    raise TypeError(e)


def effects(text: str) -> dict:
    """{effect key: list of conditions (None = always)}"""
    out: dict = {}
    for s in parse_spec(text):
        if isinstance(s, Assign):
            out.setdefault(("OTE", s.target), []).append(_norm(s.expr))
        else:
            for a in s.actions:
                key = ("ACT", format_action(a))
                out.setdefault(key, []).append(None if s.cond is None else _norm(s.cond))
    return out


def _same_condition(a, b, max_exhaustive: int = 14, samples: int = 4000) -> bool:
    if a is None or b is None:
        return a is None and b is None
    names: set = set()
    _atoms(a, names)
    _atoms(b, names)
    names = sorted(names)
    if len(names) <= max_exhaustive:
        envs = (dict(zip(names, v)) for v in itertools.product([False, True], repeat=len(names)))
    else:
        rng = random.Random(0)
        envs = ({n: rng.random() < 0.5 for n in names} for _ in range(samples))
    return all(_eval(a, env) == _eval(b, env) for env in envs)


def equivalent(got: str, expected: str) -> tuple[bool, str]:
    """(same?, reason if not)."""
    try:
        g, e = effects(got), effects(expected)
    except Exception as ex:  # unparsable -> not equivalent
        return False, f"does not parse: {ex}"
    if set(g) != set(e):
        missing = [k[1] for k in set(e) - set(g)]
        extra = [k[1] for k in set(g) - set(e)]
        parts = []
        if missing:
            parts.append(f"missing {', '.join(sorted(missing))}")
        if extra:
            parts.append(f"unexpected {', '.join(sorted(extra))}")
        return False, "; ".join(parts)
    for k in e:
        if len(g[k]) != len(e[k]):
            return False, f"{k[1]} written {len(g[k])} times, expected {len(e[k])}"
        for cg, ce in zip(g[k], e[k]):
            if not _same_condition(cg, ce):
                return False, f"different condition for {k[1]}"
    return True, ""
