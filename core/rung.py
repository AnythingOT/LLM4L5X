"""Ladder neutral text: AST, parser and printer.

Neutral text is what Studio 5000 stores in <Rung><Text>, for example
    XIC(Start)[XIC(Run) ,XIO(Stop) ]OTE(Motor);
Series = AND, branch = OR.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Union
from collections.abc import Iterator


# ---------------------------------------------------------------- AST


@dataclass(frozen=True)
class Instr:
    name: str
    args: tuple[str, ...] = ()


@dataclass(frozen=True)
class Series:
    items: tuple[Elem, ...] = ()


@dataclass(frozen=True)
class Branch:
    legs: tuple[Series, ...]


Elem = Union[Instr, Branch]


@dataclass(frozen=True)
class Rung:
    body: Series
    comment: str | None = None

    def instructions(self) -> Iterator[Instr]:
        return walk(self.body)


def walk(node) -> Iterator[Instr]:
    """Yield every instruction in left-to-right order."""
    if isinstance(node, Instr):
        yield node
    elif isinstance(node, Series):
        for it in node.items:
            yield from walk(it)
    elif isinstance(node, Branch):
        for leg in node.legs:
            yield from walk(leg)
    elif isinstance(node, Rung):
        yield from walk(node.body)


# ---------------------------------------------------------------- parser


class RungSyntaxError(ValueError):
    def __init__(self, msg: str, text: str, pos: int):
        super().__init__(f"{msg} at column {pos + 1}: {text[max(0, pos - 20):pos]}<<HERE>>{text[pos:pos + 20]}")
        self.pos = pos


_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class _Parser:
    def __init__(self, text: str):
        self.t = text
        self.i = 0

    def ws(self):
        while self.i < len(self.t) and self.t[self.i].isspace():
            self.i += 1

    def peek(self) -> str:
        self.ws()
        return self.t[self.i] if self.i < len(self.t) else ""

    def err(self, msg):
        raise RungSyntaxError(msg, self.t, self.i)

    def rung(self) -> Series:
        s = self.series(stop=";")
        if self.peek() != ";":
            self.err("expected ';' at end of rung")
        self.i += 1
        if self.peek():
            self.err("text after ';'")
        return s

    def series(self, stop: str) -> Series:
        items = []
        while True:
            c = self.peek()
            if c == "" or c in stop:
                return Series(tuple(items))
            if c == "[":
                items.append(self.branch())
            else:
                items.append(self.instr())

    def branch(self) -> Branch:
        self.i += 1  # [
        legs = [self.series(stop=",]")]
        while True:
            c = self.peek()
            if c == ",":
                self.i += 1
                legs.append(self.series(stop=",]"))
            elif c == "]":
                self.i += 1
                break
            else:
                self.err("unterminated branch")
        if len(legs) < 2:
            self.err("branch needs at least two legs")
        return Branch(tuple(legs))

    def instr(self) -> Instr:
        self.ws()
        m = _NAME.match(self.t, self.i)
        if not m:
            self.err("expected instruction")
        self.i = m.end()
        if self.peek() != "(":
            self.err(f"expected '(' after {m.group()}")
        self.i += 1
        # Name kept as written so printing is lossless; catalog lookups are case-insensitive.
        return Instr(m.group(), tuple(self.args()))

    def args(self) -> list[str]:
        """Split at depth-0 commas until the matching ')'. Keeps inner text verbatim."""
        out, buf, opened, quote = [], [], [], False  # opened: a stack, so A(1] is caught
        while self.i < len(self.t):
            c = self.t[self.i]
            self.i += 1
            if quote:
                buf.append(c)
                if c == "'":
                    quote = False
                continue
            if c == "'":
                quote = True
            elif c in "([":
                opened.append(c)
            elif c in ")]":
                if not opened and c == ")":
                    a = "".join(buf).strip()
                    if a or out:
                        out.append(a)
                    return out
                if not opened:
                    self.err("unbalanced bracket in operand")
                if opened.pop() != {")": "(", "]": "["}[c]:
                    self.err(f"'{c}' closes a different bracket in operand")
            elif c == "," and not opened:
                out.append("".join(buf).strip())
                buf = []
                continue
            buf.append(c)
        self.err("unterminated operand list")


def parse_rung(text: str, comment: str | None = None) -> Rung:
    return Rung(_Parser(text).rung(), comment)


# ---------------------------------------------------------------- printer
# Export style, confirmed on 3,160 rungs from public Studio 5000 exports:
#   top level:      elements are concatenated with no separator
#   inside [ ... ]: every element is followed by one space, legs are
#                   separated by "," and the branch closes with "]"
#   e.g.  XIC(a)[XIC(b) XIO(c) ,XIC(d) [XIC(e) ,XIC(f) ] ]OTE(g);


def format_elem(e, in_branch: bool = False) -> str:
    if isinstance(e, Instr):
        return f"{e.name}({','.join(e.args)})"
    if isinstance(e, Series):
        if in_branch:
            return "".join(format_elem(i, True) + " " for i in e.items)
        return "".join(format_elem(i) for i in e.items)
    if isinstance(e, Branch):
        return "[" + ",".join(format_elem(l, True) for l in e.legs) + "]"
    raise TypeError(e)


def format_rung(r: Rung | Series) -> str:
    body = r.body if isinstance(r, Rung) else r
    return format_elem(body) + ";"


def normalize(text: str) -> str:
    """Parse and reprint in canonical style."""
    return format_rung(parse_rung(text))


# ---------------------------------------------------------------- tag helpers

_BASE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_:]*)")
_NUMBER = re.compile(r"^[+-]?(\d+\.?\d*([eE][+-]?\d+)?|\.\d+([eE][+-]?\d+)?|16#[0-9A-Fa-f_]+|2#[01_]+|8#[0-7_]+)$")


def is_literal(arg: str) -> bool:
    return bool(_NUMBER.match(arg.strip()))


def is_placeholder(arg: str) -> bool:
    return arg.strip() == "?"


def base_tag(arg: str) -> str | None:
    """'Tank[3].Level.2' -> 'Tank'. Returns None for literals and '?'."""
    if is_literal(arg) or is_placeholder(arg):
        return None
    m = _BASE.match(arg)
    return m.group(1) if m else None


def is_plain_tag(arg: str) -> bool:
    """True if the operand is a bare tag name with no member, bit or index."""
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", arg.strip()))
