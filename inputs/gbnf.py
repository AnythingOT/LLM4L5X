"""Per-request GBNF grammar (llama.cpp) for LogicSpec.

With llama.cpp's server the grammar is applied while the model generates, so
every reply is syntactically valid LogicSpec and only uses the tags allowed:
  * BOOL tags (and timer/counter .DN/.TT/.EN bits) as contacts
  * plain BOOL tags as coils/latches (never a timer's .DN)
  * numeric tags in comparisons and math
  * TIMER / COUNTER tags in timer / counter actions
  * "ANY" tags (names from the request whose type is unknown) everywhere
A small model therefore cannot write prose, invent syntax, or misspell a tag.

Checked in tests against every expected answer of the instruction suite with
a small GBNF interpreter (tests/helpers.py). Not yet run inside llama.cpp
itself: if llama-server rejects the grammar, the request falls back to
unconstrained generation and the error is shown.
"""

from __future__ import annotations

import json

NUMERIC = {"SINT", "INT", "DINT", "LINT", "REAL", "LREAL", "USINT", "UINT", "UDINT", "ULINT"}


def _alts(values) -> str:
    return " | ".join(json.dumps(v) for v in sorted(set(values)))


def build_gbnf(tags: dict[str, str], allow_new_tags: bool = False) -> str:
    """tags: {name: datatype}; datatype "ANY" = unknown (allowed in every position)."""
    bool_read, bool_write, num, timers, counters, anyref = [], [], [], [], [], []
    for name, dt in tags.items():
        dt = (dt or "ANY").upper()
        if dt == "BOOL":
            bool_read.append(name)
            bool_write.append(name)
        elif dt in NUMERIC:
            num.append(name)
        elif dt == "TIMER":
            timers.append(name)
            bool_read += [f"{name}.DN", f"{name}.TT", f"{name}.EN"]
            num += [f"{name}.ACC", f"{name}.PRE"]
        elif dt == "COUNTER":
            counters.append(name)
            bool_read += [f"{name}.DN", f"{name}.OV", f"{name}.UN"]
            num += [f"{name}.ACC", f"{name}.PRE"]
        else:  # ANY, STRING, UDT ...: usable anywhere, with timer/counter members
            anyref.append(name)
    if not (bool_read or num or anyref or allow_new_tags):
        raise ValueError("no usable tags")

    def ref(rule: str, names: list[str], members: str = "") -> str | None:
        parts = []
        if names:
            parts.append(_alts(names))
        if anyref:
            parts.append(f"any-ref{members}")
        if allow_new_tags:
            parts.append(f"new-tag{members}")
        return f"{rule} ::= {' | '.join(parts)}\n" if parts else None

    member = ' ("." ("DN" | "TT" | "EN" | "ACC" | "PRE" | "OV" | "UN"))?'
    defs = {"bool-ref": ref("bool-ref", bool_read, member), "bool-out": ref("bool-out", bool_write),
            "num-ref": ref("num-ref", num, member), "timer-ref": ref("timer-ref", timers),
            "counter-ref": ref("counter-ref", counters), "data-ref": ref("data-ref", num)}
    has = {k: v is not None for k, v in defs.items()}
    rules = "".join(v for v in defs.values() if v)
    if anyref:
        rules += f"any-ref ::= {_alts(anyref)}\n"
    if allow_new_tags:
        rules += 'new-tag ::= [A-Za-z] [A-Za-z0-9]* ("_" [A-Za-z0-9]+)*\n'

    # only offer the constructs that have tags to use; every rule on one line
    operand = "num-ref | number" if has["num-ref"] else "number"
    atom = ['"(" ws expr ws ")"', '"RISE(" ws expr ws ")"', "delay", "cmp"]
    if has["bool-ref"]:
        atom.append("bool-ref")
    delay_tmr = ' (ws "," ws timer-ref)?' if has["timer-ref"] else ""
    actions = []
    if has["bool-out"]:
        actions.append('("ENERGIZE" | "SET" | "RESET") ws1 bool-out')
    if has["num-ref"]:
        actions += ['"CLEAR" ws1 num-ref', 'num-ref ws ":=" ws operand (ws arith-op ws operand)?']
    resettable = [r for r in ("timer-ref", "counter-ref") if has[r]]
    if resettable:
        actions.append(f'"RESET_ACC" ws1 ({" | ".join(resettable)})')
    if has["counter-ref"]:
        actions.append('("COUNT_UP" | "COUNT_DOWN") "(" ws counter-ref ws "," ws [0-9]+ ws ")"')
    if has["timer-ref"]:
        actions.append('("ON_DELAY_TIMER" | "OFF_DELAY_TIMER") "(" ws timer-ref ws "," ws duration ws ")"')
    if has["data-ref"]:
        actions.append('"COPY(" ws data-ref ws "," ws data-ref ws "," ws operand ws ")"')
    statements = (["assign"] if has["bool-out"] else []) + (["ifthen"] if actions else [])
    if not statements:
        raise ValueError("no usable tags")
    lines = [
        "root ::= ws statement (ws statement)* ws",
        f"statement ::= {' | '.join(statements)}",
    ]
    if has["bool-out"]:
        lines.append('assign ::= bool-out ws ":=" ws expr ws ";"')
    if actions:
        lines.append('ifthen ::= "IF" ws1 cond ws1 "THEN" ws1 action (ws "," ws action)* ws ";"')
        lines.append(f"action ::= {' | '.join(actions)}")
    lines += [
        'cond ::= "TRUE" | expr',
        'expr ::= unary | unary (ws1 "AND" ws1 unary)+ | unary (ws1 "OR" ws1 unary)+',
        'unary ::= "NOT" ws1 unary | atom',
        f"atom ::= {' | '.join(atom)}",
        f'delay ::= ("DELAY" | "OFFDELAY") "(" ws expr ws "," ws duration{delay_tmr} ws ")"',
        "cmp ::= operand ws cmp-op ws operand",
        'cmp-op ::= "=" | "<>" | ">=" | "<=" | ">" | "<"',
        f"operand ::= {operand}",
        'number ::= "-"? [0-9]+ ("." [0-9]+)?',
        'duration ::= [0-9]+ ("ms" | "s" | "min" | "h")',
        'arith-op ::= "+" | "-" | "*" | "/"',
    ]
    return "\n".join(lines) + "\n" + rules + 'ws ::= [ \\t\\n]*\nws1 ::= [ \\t\\n]+\n'
