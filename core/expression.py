"""Expressions of CPT and CMP (and FAL-style math): parsed once, evaluated against the simulator's tags.

Never Python's eval: a small parser for what Logix allows, so a rung from a file cannot run code.
Operators, from loosest to tightest: OR, XOR, AND, comparisons (= <> < > <= >=), + -, * / MOD,
NOT and unary minus, ** ; functions ABS SQR (square root) SQRT LN LOG SIN COS TAN ASN ACS ATN DEG RAD TRN.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable

Value = float | int
Lookup = Callable[[str], Value]


class ExprError(ValueError):
    pass


_TOKEN = re.compile(r"""\s*(?:
    (?P<num>(?:16|8|2)\#[0-9A-Fa-f_]+|\d+\.\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?|\d+(?:[eE][-+]?\d+)?)
  | (?P<op>\*\*|<=|>=|<>|[-+*/()=<>,])
  | (?P<name>[A-Za-z_:][\w:]*(?:\[[^\]]*\])*(?:\.[A-Za-z_]\w*(?:\[[^\]]*\])*|\.\d+)*)
)""", re.X)

_WORD_OPS = {"MOD", "AND", "OR", "XOR", "NOT"}


def _int_div(x, y):
    if y == 0:
        raise ExprError("divide by zero")
    if isinstance(x, float) or isinstance(y, float):
        return x / y
    return int(x / y)  # integer operands: truncate toward zero


def _mod(x, y):
    if y == 0:
        raise ExprError("MOD by zero")
    return math.fmod(x, y) if isinstance(x, float) or isinstance(y, float) else int(math.fmod(x, y))


def _bits(f):
    def g(x, y):
        if isinstance(x, float) or isinstance(y, float):
            return f(int(bool(x)), int(bool(y)))  # REAL operands: as logical values
        return f(int(x), int(y))
    return g


_BINARY = {
    "OR": (1, _bits(lambda x, y: x | y)), "XOR": (2, _bits(lambda x, y: x ^ y)), "AND": (3, _bits(lambda x, y: x & y)),
    "=": (4, lambda x, y: int(x == y)), "<>": (4, lambda x, y: int(x != y)), "<": (4, lambda x, y: int(x < y)),
    ">": (4, lambda x, y: int(x > y)), "<=": (4, lambda x, y: int(x <= y)), ">=": (4, lambda x, y: int(x >= y)),
    "+": (5, lambda x, y: x + y), "-": (5, lambda x, y: x - y),
    "*": (6, lambda x, y: x * y), "/": (6, _int_div), "MOD": (6, _mod),
    "**": (8, lambda x, y: float(x) ** y),
}
_FUNCS = {
    "ABS": abs, "SQR": math.sqrt, "SQRT": math.sqrt, "LN": math.log, "LOG": math.log10,
    "SIN": math.sin, "COS": math.cos, "TAN": math.tan, "ASN": math.asin, "ACS": math.acos, "ATN": math.atan,
    "DEG": math.degrees, "RAD": math.radians, "TRN": lambda x: int(x),
}


def _number(text: str) -> Value:
    for prefix, base in (("16#", 16), ("8#", 8), ("2#", 2)):
        if text.startswith(prefix):
            return int(text[len(prefix):].replace("_", ""), base)
    return float(text) if re.search(r"[.eE]", text) and not text.startswith(("16#", "8#", "2#")) else int(text)


def _tokens(text: str) -> list[tuple[str, str]]:
    out, i = [], 0
    while i < len(text):
        if text[i:].strip() == "":
            break
        m = _TOKEN.match(text, i)
        if not m or m.end() == i:
            raise ExprError(f"cannot read the expression at: {text[i:i + 20]!r}")
        i = m.end()
        kind = m.lastgroup
        tok = m.group(kind)
        if kind == "name" and tok.upper() in _WORD_OPS:
            out.append(("op", tok.upper()))
        else:
            out.append((kind, tok))
    return out


class Expression:
    """A parsed expression: call it with a lookup (tag name -> value)."""

    def __init__(self, text: str):
        self.text = text
        self._t = _tokens(text)
        self._i = 0
        self.tags: list[str] = []
        self._fn = self._binary(0)
        if self._i != len(self._t):
            raise ExprError(f"unexpected {self._t[self._i][1]!r} in {text!r}")

    def __call__(self, lookup: Lookup) -> Value:
        return self._fn(lookup)

    def _peek(self):
        return self._t[self._i] if self._i < len(self._t) else ("end", "")

    def _take(self):
        tok = self._peek()
        self._i += 1
        return tok

    def _binary(self, min_prec: int):
        left = self._unary()
        while True:
            kind, tok = self._peek()
            if kind != "op" or tok not in _BINARY or _BINARY[tok][0] < min_prec:
                return left
            prec, f = _BINARY[tok]
            self._take()
            right = self._binary(prec + (0 if tok == "**" else 1))  # ** groups right to left
            left = _apply(f, left, right)

    def _unary(self):
        kind, tok = self._peek()
        if kind == "op" and tok == "-":
            self._take()
            inner = self._binary(7)
            return lambda env: -inner(env)
        if kind == "op" and tok == "+":
            self._take()
            return self._binary(7)
        if kind == "op" and tok == "NOT":
            self._take()
            inner = self._binary(7)

            def not_(env):
                v = inner(env)
                return int(not v) if isinstance(v, float) else ~int(v)  # bitwise on integers, as Logix
            return not_
        return self._atom()

    def _atom(self):
        kind, tok = self._take()
        if kind == "num":
            v = _number(tok)
            return lambda env: v
        if kind == "op" and tok == "(":
            inner = self._binary(0)
            if self._take() != ("op", ")"):
                raise ExprError(f"missing ) in {self.text!r}")
            return inner
        if kind == "name":
            if self._peek() == ("op", "("):
                f = _FUNCS.get(tok.upper())
                if f is None:
                    raise ExprError(f"function {tok} is not supported")
                self._take()
                arg = self._binary(0)
                if self._take() != ("op", ")"):
                    raise ExprError(f"missing ) after {tok}( in {self.text!r}")
                return lambda env: f(arg(env))
            self.tags.append(tok)
            return lambda env: env(tok)
        raise ExprError(f"unexpected {tok or 'end'} in {self.text!r}")


def _apply(f, a, b):
    return lambda env: f(a(env), b(env))


_CACHE: dict[str, Expression] = {}


def compile_expr(text: str) -> Expression:
    e = _CACHE.get(text)
    if e is None:
        e = _CACHE[text] = Expression(text)
    return e
