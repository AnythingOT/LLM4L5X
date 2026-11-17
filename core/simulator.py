"""A small Logix scan simulator for testing compiled rungs.

Covers bits, comparisons, ONS, timers (TON, TOF, RTO), counters (CTU, CTD),
RES, MOV, CLR, arithmetic. It is a test oracle, not a controller emulator:
no math status flags, no overflow, no data type limits.

State is a flat dict: "Motor" -> bool, "T1.ACC" -> int, "Level" -> number.
"""

from __future__ import annotations

import re

from core.rung import Branch, Instr, Rung, Series, is_literal


_V36 = {"EQ": "EQU", "NE": "NEQ", "GT": "GRT", "LT": "LES", "GE": "GEQ", "LE": "LEQ",
        "LIMIT": "LIM", "MOVE": "MOV"}


class SimError(RuntimeError):
    pass


def _num(text: str) -> float | int:
    t = text.strip()
    for prefix, base in (("16#", 16), ("8#", 8), ("2#", 2)):
        if t.startswith(prefix):
            return int(t[len(prefix):].replace("_", ""), base)
    return float(t) if re.search(r"[.eE]", t) else int(t)


class Simulator:
    def __init__(self, rungs: list[Rung], state: dict | None = None):
        self.rungs = rungs
        self.state: dict = dict(state or {})
        self.dt = 0  # ms elapsed this scan

    # ------------------------------------------------------------ values

    def get(self, ref: str):
        if is_literal(ref):
            return _num(ref)
        return self.state.get(ref.strip(), 0)

    def bit(self, ref: str) -> bool:
        return bool(self.get(ref))

    def put(self, ref: str, value) -> None:
        if is_literal(ref):
            raise SimError(f"write to literal {ref}")
        self.state[ref.strip()] = value

    def _m(self, tag: str, member: str):
        return self.state.get(f"{tag}.{member}", 0)

    def _sm(self, tag: str, member: str, v) -> None:
        self.state[f"{tag}.{member}"] = v

    # ------------------------------------------------------------ scan

    def scan(self, dt_ms: int = 0, inputs: dict | None = None) -> dict:
        """Apply inputs, run every rung once in order, return the state."""
        if inputs:
            self.state.update(inputs)
        self.dt = dt_ms
        for r in self.rungs:
            self.series(r.body, True)
        return self.state

    def series(self, s: Series, power: bool) -> bool:
        for e in s.items:
            power = self.branch(e, power) if isinstance(e, Branch) else self.instr(e, power)
        return power

    def branch(self, b: Branch, power: bool) -> bool:
        out = False
        for leg in b.legs:  # every leg executes, left to right
            out = self.series(leg, power) or out
        return out

    def instr(self, i: Instr, p: bool) -> bool:
        n, a = i.name.upper(), i.args
        n = _V36.get(n, n)  # v36+ mnemonics behave like the old ones
        if n == "XIC":
            return p and self.bit(a[0])
        if n == "XIO":
            return p and not self.bit(a[0])
        if n == "AFI":
            return False
        if n in ("EQU", "NEQ", "GRT", "LES", "GEQ", "LEQ"):
            x, y = self.get(a[0]), self.get(a[1])
            r = {"EQU": x == y, "NEQ": x != y, "GRT": x > y,
                 "LES": x < y, "GEQ": x >= y, "LEQ": x <= y}[n]
            return p and r
        if n == "LIM":
            lo, t, hi = (self.get(x) for x in a)
            r = lo <= t <= hi if lo <= hi else (t >= lo or t <= hi)
            return p and r
        if n == "ONS":
            out = p and not self.bit(a[0])
            self.put(a[0], p)
            return out
        if n == "OTE":
            self.put(a[0], p)
        elif n == "OTL":
            if p:
                self.put(a[0], True)
        elif n == "OTU":
            if p:
                self.put(a[0], False)
        elif n in ("TON", "RTO"):
            self._ton(a[0], p, retentive=(n == "RTO"))
        elif n == "TOF":
            self._tof(a[0], p)
        elif n in ("CTU", "CTD"):
            self._count(a[0], p, up=(n == "CTU"))
        elif n == "RES":
            if p:
                for m in ("ACC", "DN", "EN", "TT", "CU", "CD", "OV", "UN"):
                    self._sm(a[0], m, 0)
        elif n == "MOV":
            if p:
                self.put(a[1], self.get(a[0]))
        elif n == "CLR":
            if p:
                self.put(a[0], 0)
        elif n in ("ADD", "SUB", "MUL", "DIV"):
            if p:
                x, y = self.get(a[0]), self.get(a[1])
                if n == "DIV" and y == 0:
                    raise SimError("divide by zero")
                r = {"ADD": x + y, "SUB": x - y, "MUL": x * y,
                     "DIV": (x / y) if isinstance(x, float) or isinstance(y, float) else int(x / y)}[n]
                self.put(a[2], r)
        elif n == "NOP":
            pass
        else:
            raise SimError(f"simulator does not support {i.name}")
        return p

    # ------------------------------------------------------------ timers and counters

    def _ton(self, t: str, p: bool, retentive: bool) -> None:
        pre = self._m(t, "PRE")
        if p:
            self._sm(t, "EN", 1)
            if not self._m(t, "DN"):
                acc = self._m(t, "ACC") + self.dt
                if acc >= pre:
                    acc = pre
                    self._sm(t, "DN", 1)
                self._sm(t, "ACC", acc)
            self._sm(t, "TT", int(not self._m(t, "DN")))
        else:
            self._sm(t, "EN", 0)
            self._sm(t, "TT", 0)
            if not retentive:
                self._sm(t, "ACC", 0)
                self._sm(t, "DN", 0)

    def _tof(self, t: str, p: bool) -> None:
        pre = self._m(t, "PRE")
        if p:
            self._sm(t, "EN", 1)
            self._sm(t, "DN", 1)
            self._sm(t, "TT", 0)
            self._sm(t, "ACC", 0)
        else:
            self._sm(t, "EN", 0)
            if self._m(t, "DN"):
                acc = self._m(t, "ACC") + self.dt
                if acc >= pre:
                    self._sm(t, "ACC", pre)
                    self._sm(t, "DN", 0)
                    self._sm(t, "TT", 0)
                else:
                    self._sm(t, "ACC", acc)
                    self._sm(t, "TT", 1)

    def _count(self, c: str, p: bool, up: bool) -> None:
        flag = "CU" if up else "CD"
        if p and not self._m(c, flag):
            self._sm(c, "ACC", self._m(c, "ACC") + (1 if up else -1))
        self._sm(c, flag, int(p))
        self._sm(c, "DN", int(self._m(c, "ACC") >= self._m(c, "PRE")))


def preset_state(tags) -> dict:
    """Initial simulator state from compiler TagDefs (timer/counter presets)."""
    st = {}
    for t in tags.values():
        if t.preset is not None:
            st[f"{t.name}.PRE"] = t.preset
    return st
