"""Mutation check for the behaviour comparator: break correct rungs on purpose
and count how often the comparator notices. A comparator that passes
everything would make the suite worthless."""

from __future__ import annotations

import random

from core.rung import Branch, Instr, Rung, Series

FLIP = {"XIC": "XIO", "XIO": "XIC", "GRT": "LES", "LES": "GRT", "GEQ": "LEQ", "LEQ": "GEQ", "EQU": "NEQ",
        "NEQ": "EQU", "GT": "LT", "LT": "GT", "GE": "LE", "LE": "GE", "EQ": "NE", "NE": "EQ",
        "OTL": "OTU", "OTU": "OTL", "ADD": "SUB", "SUB": "ADD", "MUL": "DIV", "DIV": "MUL",
        "TON": "TOF", "TOF": "TON", "CTU": "CTD", "CTD": "CTU"}


def _instrs(node, path=()):
    if isinstance(node, Instr):
        yield path, node
    elif isinstance(node, Series):
        for i, it in enumerate(node.items):
            yield from _instrs(it, path + (i,))
    elif isinstance(node, Branch):
        for i, leg in enumerate(node.legs):
            yield from _instrs(leg, path + (i,))


def _replace(node, path, new):
    if not path:
        return new
    i, rest = path[0], path[1:]
    if isinstance(node, Series):
        items = list(node.items)
        items[i] = _replace(items[i], rest, new)
        return Series(tuple(items))
    legs = list(node.legs)
    legs[i] = _replace(legs[i], rest, new)
    return Branch(tuple(legs))


def mutate(rungs: list[Rung], presets: dict, rng: random.Random):
    """One meaning-changing mutation: (rungs, presets, description) or None."""
    kind = rng.choice(["flip", "flip", "preset", "series_to_branch", "drop_condition"])
    if kind == "preset" and presets:
        t = rng.choice(sorted(presets))
        return rungs, {**presets, t: presets[t] * 2 + 1}, f"preset of {t} changed"
    k = rng.randrange(len(rungs))
    body = rungs[k].body
    cands = [(p, i) for p, i in _instrs(body) if i.name.upper() in FLIP and not i.name.startswith("ONS")]
    if kind == "series_to_branch":
        conds = [j for j, it in enumerate(body.items) if isinstance(it, Instr) and it.name.upper() in
                 ("XIC", "XIO", "GRT", "LES", "EQU", "NEQ", "GEQ", "LEQ", "GT", "LT", "EQ", "NE", "GE", "LE")]
        if len(conds) >= 2 and conds[1] == conds[0] + 1:
            j = conds[0]
            items = list(body.items)
            items[j:j + 2] = [Branch((Series((items[j],)), Series((items[j + 1],))))]
            new = rungs[:k] + [Rung(Series(tuple(items)))] + rungs[k + 1:]
            return new, presets, "AND turned into OR"
        kind = "flip"
    if kind == "drop_condition":
        conds = [j for j, it in enumerate(body.items) if isinstance(it, Instr) and it.name.upper() in ("XIC", "XIO")]
        if conds and len(body.items) > 1:
            items = list(body.items)
            items.pop(conds[0])
            new = rungs[:k] + [Rung(Series(tuple(items)))] + rungs[k + 1:]
            return new, presets, "a condition removed"
        kind = "flip"
    if not cands:
        return None
    p, ins = rng.choice(cands)
    new_ins = Instr(FLIP[ins.name.upper()], ins.args)
    new = rungs[:k] + [Rung(_replace(body, p, new_ins))] + rungs[k + 1:]
    return new, presets, f"{ins.name} -> {new_ins.name}"
