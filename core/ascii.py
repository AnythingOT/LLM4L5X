"""ASCII rung text <-> neutral text.

Logix Designer's rung editor can show a rung two ways:

    neutral:  XIC(a)[XIC(b) ,XIO(c) ]OTE(d);
    ASCII:    XIC a BST XIC b NXB XIO c BND OTE d

L5X files only ever contain neutral text. ASCII is what the editor shows in
"ASCII" mode and what RSLogix 500 / PLC-5 users are used to. ASCII has no
punctuation around operands, so parsing it needs each instruction's operand
count from the catalog.

Also accepted: RSLogix 500 style SOR ... EOR rung markers.

UNVERIFIED: how the editor writes an operand that contains spaces (a CPT
expression such as "A + B"). We quote such operands with double quotes and
accept single- or double-quoted operands when parsing.
"""

from __future__ import annotations

import re

from core.catalog import Catalog, default_catalog
from core.rung import Branch, Instr, Rung, Series

BRANCH_TOKENS = {"BST", "NXB", "BND"}


class AsciiSyntaxError(ValueError):
    pass


# ---------------------------------------------------------------- tokens

_TOKEN = re.compile(r'"[^"]*"|\S+')


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text)


def _unquote(tok: str) -> str:
    return tok[1:-1] if len(tok) >= 2 and tok[0] == tok[-1] == '"' else tok


# ---------------------------------------------------------------- split into rungs


def split_ascii_rungs(text: str) -> list[str]:
    """SOR ... EOR blocks if present, otherwise one rung per non-empty line."""
    toks = _tokens(text)
    if any(t.upper() == "SOR" for t in toks):
        rungs, cur, inside = [], [], False
        for t in toks:
            u = t.upper()
            if u == "SOR":
                if inside and cur:
                    rungs.append(" ".join(cur))
                cur, inside = [], True
            elif u == "EOR":
                if cur:
                    rungs.append(" ".join(cur))
                cur, inside = [], False
            elif inside:
                cur.append(t)
        if cur:
            rungs.append(" ".join(cur))
        return rungs
    return [line.strip() for line in text.splitlines() if line.strip()]


# ---------------------------------------------------------------- parse


def parse_ascii_rung(text: str, catalog: Catalog | None = None, comment: str | None = None) -> Rung:
    cat = catalog or default_catalog()
    toks = [t for t in _tokens(text) if t.upper() not in ("SOR", "EOR")]
    k = 0

    def is_mnemonic(t: str) -> bool:
        return t.upper() in BRANCH_TOKENS or cat.get(t) is not None

    def series(stop: set[str]) -> Series:
        nonlocal k
        items = []
        while k < len(toks) and toks[k].upper() not in stop:
            t = toks[k]
            u = t.upper()
            if u == "BST":
                k += 1
                legs = [series({"NXB", "BND"})]
                while k < len(toks) and toks[k].upper() == "NXB":
                    k += 1
                    legs.append(series({"NXB", "BND"}))
                if k >= len(toks) or toks[k].upper() != "BND":
                    raise AsciiSyntaxError(f"BST without matching BND in: {text}")
                k += 1
                if len(legs) < 2:
                    raise AsciiSyntaxError(f"branch needs at least one NXB in: {text}")
                items.append(Branch(tuple(legs)))
                continue
            if u in ("NXB", "BND"):
                raise AsciiSyntaxError(f"{u} without BST in: {text}")
            spec = cat.get(t)
            if spec is None:
                raise AsciiSyntaxError(
                    f"unknown instruction {t!r}: ASCII text needs its operand count. "
                    "If it is an Add-On Instruction, attach the project that defines it.")
            k += 1
            n = len(spec.operands)
            if k + n > len(toks):
                raise AsciiSyntaxError(f"{t} needs {n} operands in: {text}")
            args = [_unquote(x) for x in toks[k:k + n]]
            for raw in toks[k:k + n]:
                if raw.upper() in BRANCH_TOKENS:
                    raise AsciiSyntaxError(f"{t} needs {n} operands, ran into {raw} in: {text}")
            k += n
            if spec.variadic:  # take operands until the next instruction or branch token
                while k < len(toks) and not is_mnemonic(toks[k]):
                    args.append(_unquote(toks[k]))
                    k += 1
            items.append(Instr(t, tuple(args)))
        return Series(tuple(items))

    body = series(set())
    if k != len(toks):
        raise AsciiSyntaxError(f"unexpected {toks[k]} in: {text}")
    if not body.items:
        raise AsciiSyntaxError("empty rung")
    return Rung(body, comment)


def parse_ascii(text: str, catalog: Catalog | None = None) -> list[Rung]:
    return [parse_ascii_rung(r, catalog) for r in split_ascii_rungs(text)]


# ---------------------------------------------------------------- print


def _arg(a: str) -> str:
    return f'"{a}"' if (not a or re.search(r"\s", a)) else a


def _fmt(node) -> str:
    if isinstance(node, Instr):
        return " ".join([node.name, *(_arg(a) for a in node.args)])
    if isinstance(node, Series):
        return " ".join(_fmt(i) for i in node.items)
    if isinstance(node, Branch):
        parts = ["BST"]
        for i, leg in enumerate(node.legs):
            if i:
                parts.append("NXB")
            if leg.items:  # empty leg: nothing between the markers
                parts.append(_fmt(leg))
        parts.append("BND")
        return " ".join(parts)
    raise TypeError(node)


def format_ascii(r: Rung | Series) -> str:
    """Single spaces between tokens; text inside quoted operands is kept as is."""
    body = r.body if isinstance(r, Rung) else r
    return _fmt(body)


# ---------------------------------------------------------------- detection


def looks_like_ascii(text: str, catalog: Catalog | None = None) -> bool:
    """True if the first token is a known instruction or SOR and there is no '(' after it."""
    cat = catalog or default_catalog()
    toks = _tokens(text)
    if not toks:
        return False
    first = toks[0].upper()
    if first == "SOR":
        return True
    return (first in BRANCH_TOKENS or cat.get(first) is not None) and not re.match(r"\s*\w+\(", text)
