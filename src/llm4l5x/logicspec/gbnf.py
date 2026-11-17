"""Build a per-request GBNF grammar (llama.cpp) for LogicSpec.

The grammar restricts tag names to the candidates you pass in, and splits
them by type: only BOOL tags (and timer/counter status bits) can be used
as contacts, only plain BOOL tags as outputs (never a timer's .DN), only
numeric tags in comparisons and arithmetic. A small
model therefore cannot invent a tag or compare a bit to 5.

EXPERIMENTAL: generated text has not yet been run through llama.cpp.
Test it before relying on it (HANDOFF.md section 7).
"""

from __future__ import annotations

import json

NUMERIC = {"SINT", "INT", "DINT", "LINT", "REAL", "LREAL", "USINT", "UINT", "UDINT", "ULINT"}


def _alts(values: list[str]) -> str:
    return " | ".join(json.dumps(v) for v in sorted(set(values)))


def build_gbnf(tags: dict[str, str], allow_new_tags: bool = False) -> str:
    """tags: candidate tags {name: datatype}, usually from retrieval."""
    bools, nums, timers, counters = [], [], [], []
    writable: list[str] = []  # BOOL tags only: never write a timer/counter status bit
    for name, dt in tags.items():
        dt = dt.upper()
        if dt == "BOOL":
            bools.append(name)
            writable.append(name)
        elif dt in NUMERIC:
            nums.append(name)
        elif dt == "TIMER":
            timers.append(name)
            bools += [f"{name}.DN", f"{name}.TT", f"{name}.EN"]
            nums += [f"{name}.ACC", f"{name}.PRE"]
        elif dt == "COUNTER":
            counters.append(name)
            bools += [f"{name}.DN", f"{name}.OV", f"{name}.UN"]
            nums += [f"{name}.ACC", f"{name}.PRE"]
    new = 'new-tag ::= [A-Za-z] [A-Za-z0-9_]*\n' if allow_new_tags else ""

    def rule(name: str, values: list[str], kind: str) -> str:
        parts = []
        if values:
            parts.append(_alts(values))
        if allow_new_tags and kind != "fixed":
            parts.append("new-tag")
        if not parts:
            return ""  # no rule -> alternatives using it are dropped below
        return f"{name} ::= {' | '.join(parts)}\n"

    bool_rule = rule("bool-ref", bools, "new")
    write_rule = rule("bool-out", writable, "new")
    num_rule = rule("num-ref", nums, "new")
    timer_rule = rule("timer-ref", timers, "new")
    counter_rule = rule("counter-ref", counters, "new")

    atom = ['"(" ws expr ws ")"', '"RISE(" ws expr ws ")"',
            '("DELAY" | "OFFDELAY") "(" ws expr ws "," ws duration ws ")"', "cmp"]
    if bool_rule:
        atom.append("bool-ref")
    actions = []
    if write_rule:
        actions.append('("SET" | "RESET") ws1 bool-out')
    if num_rule:
        actions.append('"CLEAR" ws1 num-ref')
        actions.append('num-ref ws ":=" ws operand (ws arith-op ws operand)?')
    if timer_rule or counter_rule:
        refs = " | ".join(r for r, ok in (("timer-ref", timer_rule), ("counter-ref", counter_rule)) if ok)
        actions.append(f'"RESET_ACC" ws1 ({refs})')
    if counter_rule:
        actions.append('("COUNT_UP" | "COUNT_DOWN") "(" ws counter-ref ws "," ws [0-9]+ ws ")"')
    if timer_rule:
        actions.append('("START_TIMER" | "START_OFF_TIMER") "(" ws timer-ref ws "," ws duration ws ")"')
    if not actions:
        raise ValueError("no usable tags: pass at least one BOOL or numeric tag")

    statements = ['ifthen']
    if write_rule and bool_rule:
        statements.insert(0, "assign")
    operand = "num-ref | number" if num_rule else "number"

    g = f"""root ::= ws statement (ws statement)* ws
statement ::= {' | '.join(statements)}
{'assign ::= bool-out ws ":=" ws expr ws ";"' + chr(10) if write_rule and bool_rule else ''}ifthen ::= "IF" ws1 cond ws1 "THEN" ws1 action (ws "," ws action)* ws ";"
cond ::= "TRUE" | expr
expr ::= unary | unary (ws1 "AND" ws1 unary)+ | unary (ws1 "OR" ws1 unary)+
unary ::= "NOT" ws1 unary | atom
atom ::= {' | '.join(atom)}
cmp ::= operand ws cmp-op ws operand
cmp-op ::= "=" | "<>" | ">=" | "<=" | ">" | "<"
arith-op ::= "+" | "-" | "*" | "/"
operand ::= {operand}
number ::= "-"? [0-9]+ ("." [0-9]+)?
duration ::= [0-9]+ ("ms" | "s" | "min" | "h")
action ::= {' | '.join(actions)}
{bool_rule}{write_rule}{num_rule}{timer_rule}{counter_rule}{new}ws ::= [ \\t\\n]*
ws1 ::= [ \\t\\n]+
"""
    return g
