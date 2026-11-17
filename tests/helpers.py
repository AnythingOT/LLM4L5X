"""Shared test helpers: random LogicSpec expressions, reference evaluation,
and a tiny GBNF interpreter so generated grammars can be checked without llama.cpp."""

from __future__ import annotations

import itertools
import json
import random
import re

from core.logicspec import And, Cmp, Not, Or, Var

BOOLS = ["A", "B", "C", "D", "E", "F"]
NUMS = ["N1", "N2"]
NUM_VALUES = [4, 5, 6]


def random_expr(rng: random.Random, depth: int = 3):
    r = rng.random()
    if depth == 0 or r < 0.3:
        if rng.random() < 0.8:
            e = Var(rng.choice(BOOLS))
        else:
            e = Cmp(rng.choice(["=", "<>", ">", "<", ">=", "<="]), rng.choice(NUMS), "5")
        return Not(e) if rng.random() < 0.3 else e
    n = rng.randint(2, 3)
    items = tuple(random_expr(rng, depth - 1) for _ in range(n))
    e = And(items) if rng.random() < 0.5 else Or(items)
    return Not(e) if rng.random() < 0.25 else e


def evaluate(e, env) -> bool:
    if isinstance(e, Var):
        return bool(env.get(e.name, 0))
    if isinstance(e, Not):
        return not evaluate(e.expr, env)
    if isinstance(e, And):
        return all(evaluate(i, env) for i in e.items)
    if isinstance(e, Or):
        return any(evaluate(i, env) for i in e.items)
    if isinstance(e, Cmp):
        a = env.get(e.a, 0) if not e.a.lstrip("-").isdigit() else int(e.a)
        b = env.get(e.b, 0) if not e.b.lstrip("-").isdigit() else int(e.b)
        return {"=": a == b, "<>": a != b, ">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[e.op]
    raise TypeError(e)


def environments(bools=BOOLS, nums=NUMS):
    for bv in itertools.product([0, 1], repeat=len(bools)):
        for nv in itertools.product(NUM_VALUES, repeat=len(nums)):
            env = dict(zip(bools, bv))
            env.update(zip(nums, nv))
            yield env


# ---------------------------------------------------------------- mini GBNF interpreter

_TOK = re.compile(r'\s*(::=|"(?:\\.|[^"\\])*"|\[(?:\\.|[^\]\\])*\]|[A-Za-z][A-Za-z0-9-]*|[|()?*+])')


def _parse_grammar(text: str) -> dict:
    rules = {}
    for line in text.splitlines():
        line = line.split("#")[0].strip() if not line.strip().startswith('"') else line.strip()
        if not line:
            continue
        name, body = line.split("::=", 1)
        toks = _TOK.findall(body)
        pos = 0

        def alt():
            nonlocal pos
            seqs = [seq()]
            while pos < len(toks) and toks[pos] == "|":
                pos += 1
                seqs.append(seq())
            return ("alt", seqs)

        def seq():
            nonlocal pos
            items = []
            while pos < len(toks) and toks[pos] not in ("|", ")"):
                t = toks[pos]
                pos += 1
                if t == "(":
                    node = alt()
                    assert toks[pos] == ")"
                    pos += 1
                elif t.startswith('"'):
                    node = ("lit", json.loads(t))
                elif t.startswith("["):
                    node = ("cls", re.compile(t))
                else:
                    node = ("ref", t)
                if pos < len(toks) and toks[pos] in "?*+":
                    node = (toks[pos], node)
                    pos += 1
                items.append(node)
            return ("seq", items)

        rules[name.strip()] = alt()
        assert pos == len(toks), f"trailing tokens in rule {name}"
    return rules


class Grammar:
    def __init__(self, text: str):
        self.rules = _parse_grammar(text)
        for name, node in self.rules.items():
            for ref in self._refs(node):
                assert ref in self.rules, f"rule {name} references undefined rule {ref}"

    def _refs(self, node):
        kind = node[0]
        if kind == "ref":
            yield node[1]
        elif kind in ("alt", "seq"):
            for n in node[1]:
                yield from self._refs(n)
        elif kind in "?*+":
            yield from self._refs(node[1])

    def _m(self, node, s, i):
        kind = node[0]
        if kind == "lit":
            if s.startswith(node[1], i):
                yield i + len(node[1])
        elif kind == "cls":
            if i < len(s) and node[1].fullmatch(s[i]):
                yield i + 1
        elif kind == "ref":
            yield from self._m(self.rules[node[1]], s, i)
        elif kind == "alt":
            for n in node[1]:
                yield from self._m(n, s, i)
        elif kind == "seq":
            yield from self._seq(node[1], 0, s, i)
        elif kind == "?":
            yield i
            yield from self._m(node[1], s, i)
        elif kind in "*+":
            yield from self._rep(node[1], s, i, kind == "+")

    def _seq(self, items, k, s, i):
        if k == len(items):
            yield i
            return
        for j in self._m(items[k], s, i):
            yield from self._seq(items, k + 1, s, j)

    def _rep(self, node, s, i, need_one):
        if not need_one:
            yield i
        for j in self._m(node, s, i):
            if j > i:
                yield from self._rep(node, s, j, False)

    def accepts(self, s: str) -> bool:
        return any(j == len(s) for j in self._m(self.rules["root"], s, 0))
