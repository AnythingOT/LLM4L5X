"""A small Logix scan simulator for testing compiled rungs.

Covers bits, comparisons, ONS, timers (TON, TOF, RTO), counters (CTU, CTD),
RES, MOV, CLR, arithmetic. It is a test oracle, not a controller emulator:
no math status flags, no overflow, no data type limits.

State is a flat dict: "Motor" -> bool, "T1.ACC" -> int, "Level" -> number.
"""

from __future__ import annotations

import operator
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
        self.power: list[bool] = []

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
        # whether each rung ended true this scan: the Energise page lights energised rungs
        self.power = [self.series(r.body, True) for r in self.rungs]
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
        if n in _COMPARE:
            return p and _COMPARE[n](self.get(a[0]), self.get(a[1]))
        if n in _MATH:
            if p:
                self.put(a[2], _MATH[n](self.get(a[0]), self.get(a[1])))
            return p
        handler = _HANDLERS.get(n)
        if handler is None:
            raise SimError(f"simulator does not support {i.name}")
        return handler(self, a, p)

    # ------------------------------------------------------------ instructions (args, power) -> power out

    def _xic(self, a, p):
        return p and self.bit(a[0])

    def _xio(self, a, p):
        return p and not self.bit(a[0])

    def _lim(self, a, p):
        lo, t, hi = (self.get(x) for x in a)
        return p and (lo <= t <= hi if lo <= hi else (t >= lo or t <= hi))

    def _ons(self, a, p):
        out = p and not self.bit(a[0])
        self.put(a[0], p)
        return out

    def _ote(self, a, p):
        self.put(a[0], p)
        return p

    def _otl(self, a, p):
        if p:
            self.put(a[0], True)
        return p

    def _otu(self, a, p):
        if p:
            self.put(a[0], False)
        return p

    def _res(self, a, p):
        if p:
            for m in ("ACC", "DN", "EN", "TT", "CU", "CD", "OV", "UN"):
                self._sm(a[0], m, 0)
        return p

    def _mov(self, a, p):
        if p:
            self.put(a[1], self.get(a[0]))
        return p

    def _clr(self, a, p):
        if p:
            self.put(a[0], 0)
        return p

    def _cop(self, a, p):
        if p:
            count = int(self.get(a[2]))
            src, dst = a[0].strip(), a[1].strip()
            if count <= 1 and "[" not in src:
                self.put(dst, self.get(src))
            else:  # element-wise; src/dst may name an array or its first element
                sb, si = _array_start(src)
                db, di = _array_start(dst)
                for k in range(count):
                    self.state[f"{db}[{di + k}]"] = self.state.get(f"{sb}[{si + k}]", 0)
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


def _array_start(ref: str) -> tuple[str, int]:
    m = re.fullmatch(r"(.+)\[(\d+)\]", ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


def preset_state(tags) -> dict:
    """Initial simulator state from compiler TagDefs (timer/counter presets)."""
    st = {}
    for t in tags.values():
        if t.preset is not None:
            st[f"{t.name}.PRE"] = t.preset
    return st


def _div(x, y):
    if y == 0:  # Logix sets a minor fault and the destination; good enough to flag
        raise SimError("divide by zero")
    return (x / y) if isinstance(x, float) or isinstance(y, float) else int(x / y)


_COMPARE = {"EQU": operator.eq, "NEQ": operator.ne, "GRT": operator.gt,
            "LES": operator.lt, "GEQ": operator.ge, "LEQ": operator.le}
_MATH = {"ADD": operator.add, "SUB": operator.sub, "MUL": operator.mul, "DIV": _div}
_HANDLERS = {
    "XIC": Simulator._xic, "XIO": Simulator._xio, "AFI": lambda self, a, p: False, "NOP": lambda self, a, p: p,
    "LIM": Simulator._lim, "ONS": Simulator._ons,
    "OTE": Simulator._ote, "OTL": Simulator._otl, "OTU": Simulator._otu,
    "TON": lambda self, a, p: self._ton(a[0], p, retentive=False) or p,
    "RTO": lambda self, a, p: self._ton(a[0], p, retentive=True) or p,
    "TOF": lambda self, a, p: self._tof(a[0], p) or p,
    "CTU": lambda self, a, p: self._count(a[0], p, up=True) or p,
    "CTD": lambda self, a, p: self._count(a[0], p, up=False) or p,
    "RES": Simulator._res, "MOV": Simulator._mov, "CLR": Simulator._clr, "COP": Simulator._cop,
}
