"""A small Logix scan simulator for testing compiled rungs.

Covers bits, comparisons, ONS, timers (TON, TOF, RTO), counters (CTU, CTD), RES, MOV, CLR, COP,
arithmetic, CPT and CMP expressions, subroutines (JSR) and Add-On Instruction logic. It is a test
oracle, not a controller emulator: no math status flags, no overflow. Its behaviour is checked against
Logix Emulate with eval/conformance.py; tests/TEST_STATUS.md says what that comparison found.

State is a flat dict: "Motor" -> bool, "T1.ACC" -> int, "Level" -> number. With `types` (tag -> data
type), a REAL written to an integer tag is rounded as Logix does (to nearest, .5 to even).
"""

from __future__ import annotations

import operator
import re
from dataclasses import dataclass, field

from core.expression import ExprError, compile_expr
from core.rung import Branch, Instr, Rung, Series, base_tag, is_literal


_V36 = {"EQ": "EQU", "NE": "NEQ", "GT": "GRT", "LT": "LES", "GE": "GEQ", "LE": "LEQ",
        "LIMIT": "LIM", "MOVE": "MOV"}


class SimError(RuntimeError):
    pass


_INTEGER = {"SINT", "INT", "DINT", "LINT", "USINT", "UINT", "UDINT", "ULINT"}
_MAX_DEPTH = 32  # nested JSR / AOI calls; a loop of calls stops here instead of hanging the page


@dataclass
class AoiDef:
    """An Add-On Instruction as the simulator runs it: its call operands and its Logic routine."""
    name: str
    params: list[tuple[str, str]]  # call operands in order: (name, usage Input/Output/InOut)
    rungs: list[Rung]
    members: set[str] = field(default_factory=set)  # every parameter and local tag name
    defaults: dict[str, object] = field(default_factory=dict)  # "Tmr.PRE" -> 5000, from the definition


def _num(text: str) -> float | int:
    t = text.strip()
    for prefix, base in (("16#", 16), ("8#", 8), ("2#", 2)):
        if t.startswith(prefix):
            return int(t[len(prefix):].replace("_", ""), base)
    return float(t) if re.search(r"[.eE]", t) else int(t)


class Simulator:
    def __init__(self, rungs: list[Rung], state: dict | None = None, *, routine_of: list[str] | None = None,
                 aois: dict[str, AoiDef] | None = None, types: dict[str, str] | None = None,
                 skip: set[str] | None = None):
        """routine_of: "Program/Routine" of each rung. A routine another routine of its program calls with
        JSR runs only when called; every other routine runs each scan, in order. Without routine_of, every
        rung runs each scan. skip: routine names a JSR passes over (MAP_IN, MAP_OUT in simulation)."""
        self.rungs = rungs
        self.state: dict = dict(state or {})
        self.types = {k.upper(): v.upper() for k, v in (types or {}).items()}
        self.aois = {k.upper(): v for k, v in (aois or {}).items()}
        self.skip = {s.upper() for s in (skip or set())}
        self._routines: dict[str, list[int]] = {}
        self._prog_of: list[str] = []  # the program of each rung, for the JSRs in it
        for i, key in enumerate(routine_of or ["/"] * len(rungs)):
            self._routines.setdefault(key.upper(), []).append(i)
            self._prog_of.append(key.upper().split("/", 1)[0])
        called = set()
        for key, idx in self._routines.items():
            prog = key.split("/", 1)[0]
            for i in idx:
                called |= {f"{prog}/{c.args[0]}".upper() for c in _walk(rungs[i].body)
                           if c.name.upper() == "JSR" and c.args}
        self._top = [i for key, idx in self._routines.items() if key not in called for i in idx]
        self._program = [""]  # the program of the routine running now: JSR looks for its routine there
        self._depth = 0
        self._aoi_rungs: dict[tuple, list[Rung]] = {}
        self._aoi_ready: set[str] = set()
        self.dt = 0  # ms elapsed this scan
        self.power: list[bool] = []
        # power trace of the last scan, kept only when asked (the Energize page draws it): per rung,
        # element path -> 1 if power reached the element, | 2 if power left it. A path is the item's index in
        # its series, and in a branch "branch.leg.item": "2", "1.0.0", "1.1.0" ...
        self.trace = False
        self.flow: list[dict[str, int]] = []

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
        ref = ref.strip()
        if self.types and isinstance(value, float):
            t = self.types.get(ref.upper()) or ("" if "." in ref else self.types.get((base_tag(ref) or "").upper()))
            if t in _INTEGER:
                value = round(value)  # Logix: REAL to integer rounds to nearest, .5 to even (Python's round)
        self.state[ref] = value

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
        # whether each rung ended true this scan: the Energize page lights energized rungs. A rung of a
        # subroutine that was not called this scan stays False, with no power flow.
        self.power = [False] * len(self.rungs)
        self.flow = [{} for _ in self.rungs] if self.trace else []
        for i in self._top:
            self._run(i)
        return self.state

    def _run(self, i: int) -> None:
        self._program.append(self._prog_of[i])
        try:
            if self.trace:
                outer = getattr(self, "_flow", None)
                self._flow = {}
                self.power[i] = self.series(self.rungs[i].body, True, "")
                self.flow[i] = self._flow
                self._flow = outer
            else:
                self.power[i] = self.series(self.rungs[i].body, True)
        finally:
            self._program.pop()

    def series(self, s: Series, power: bool, path: str | None = None) -> bool:
        for k, e in enumerate(s.items):
            here = None if path is None else f"{path}{k}"
            before = power
            power = self.branch(e, power, here) if isinstance(e, Branch) else self.instr(e, power)
            if here is not None:
                self._flow[here] = int(bool(before)) | (2 if power else 0)
        return power

    def branch(self, b: Branch, power: bool, path: str | None = None) -> bool:
        out = False
        for j, leg in enumerate(b.legs):  # every leg executes, left to right
            out = self.series(leg, power, None if path is None else f"{path}.{j}.") or out
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
        if handler is not None:
            return handler(self, a, p)
        if n in self.aois:
            return self._aoi(self.aois[n], a, p)
        raise SimError(f"simulator does not support {i.name}")

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

    def _osr(self, a, p):  # output instructions: the rung goes on as it came in; the output bit is the edge
        self.put(a[1], p and not self.bit(a[0]))
        self.put(a[0], p)
        return p

    def _osf(self, a, p):
        self.put(a[1], (not p) and self.bit(a[0]))
        self.put(a[0], p)
        return p

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

    def _cpt(self, a, p):
        if p:
            self.put(a[0], self._eval(a[1]))
        return p

    def _cmp(self, a, p):
        return p and bool(self._eval(a[0]))

    def _eval(self, text: str):
        try:
            return compile_expr(text)(self.get)
        except ExprError as e:
            raise SimError(str(e)) from None
        except (ArithmeticError, ValueError) as e:  # SQR(-1), LN(0): a math fault on the controller
            raise SimError(f"math error in {text}: {e}") from None

    # ------------------------------------------------------------ subroutines and Add-On Instructions

    def _jsr(self, a, p):
        if not p or not a:
            return p
        target = a[0].strip()
        if target.upper() in self.skip:
            return p
        key = f"{self._program[-1]}/{target}".upper()
        idx = self._routines.get(key)
        if idx is None:
            raise SimError(f"JSR to {target}: that routine is not loaded")
        self._enter(f"JSR {target}")
        try:
            for i in idx:
                self._run(i)
        finally:
            self._depth -= 1
        return p

    def _enter(self, what: str) -> None:
        self._depth += 1
        if self._depth > _MAX_DEPTH:
            self._depth = 0
            raise SimError(f"{what}: calls nested more than {_MAX_DEPTH} deep (a routine calling itself?)")

    def _aoi(self, d: AoiDef, a, p) -> bool:
        """One call: inputs in, the logic runs when the rung is true (EnableIn), outputs out; the rung
        continues with EnableOut."""
        inst, ops = a[0].strip(), a[1:]
        if inst not in self._aoi_ready:  # first call: the definition's default values (timer presets ...)
            for k, v in d.defaults.items():
                self.state.setdefault(f"{inst}.{k}", v)
            self._aoi_ready.add(inst)
        bound = {}
        for (name, usage), op in zip(d.params, ops):
            if usage.upper() == "INOUT":
                bound[name.upper()] = op.strip()
            elif usage.upper() == "INPUT":
                self.put(f"{inst}.{name}", self.get(op))
        self.state[f"{inst}.EnableIn"] = p
        self.state[f"{inst}.EnableOut"] = p
        if p:
            key = (d.name, inst, tuple(sorted(bound.items())))
            rungs = self._aoi_rungs.get(key)
            if rungs is None:
                rungs = self._aoi_rungs[key] = [_rename(r, d, inst, bound) for r in d.rungs]
            self._enter(f"{d.name}({inst})")
            try:
                for r in rungs:
                    self.series(r.body, True)
            finally:
                self._depth -= 1
        for (name, usage), op in zip(d.params, ops):
            if usage.upper() == "OUTPUT" and not is_literal(op):
                self.put(op, self.get(f"{inst}.{name}"))
        return bool(self.state.get(f"{inst}.EnableOut"))

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


def _walk(node):
    if isinstance(node, Instr):
        yield node
    elif isinstance(node, Series):
        for x in node.items:
            yield from _walk(x)
    elif isinstance(node, Branch):
        for leg in node.legs:
            yield from _walk(leg)


_IDENT = re.compile(r"(?<![\w.\]#])([A-Za-z_][A-Za-z0-9_]*)")


def _rename(r: Rung, d: AoiDef, inst: str, bound: dict[str, str]) -> Rung:
    """The AOI's logic as this instance runs it: its parameters and locals become members of the instance
    tag (Tmr.DN -> Pump1.Tmr.DN), an InOut parameter becomes the tag passed in the call."""
    names = {m.upper() for m in d.members} | {"ENABLEIN", "ENABLEOUT"}

    def ref(text: str) -> str:
        def one(m):
            w = m.group(1)
            u = w.upper()
            if u in bound:
                return bound[u]
            return f"{inst}.{w}" if u in names else w
        return _IDENT.sub(one, text)

    def node(x):
        if isinstance(x, Instr):
            return Instr(x.name, tuple(a if is_literal(a) else ref(a) for a in x.args))
        if isinstance(x, Series):
            return Series(tuple(node(e) for e in x.items))
        return Branch(tuple(node(leg) for leg in x.legs))

    return Rung(node(r.body), r.comment)


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
    "LIM": Simulator._lim, "ONS": Simulator._ons, "OSR": Simulator._osr, "OSF": Simulator._osf,
    "OTE": Simulator._ote, "OTL": Simulator._otl, "OTU": Simulator._otu,
    "TON": lambda self, a, p: self._ton(a[0], p, retentive=False) or p,
    "RTO": lambda self, a, p: self._ton(a[0], p, retentive=True) or p,
    "TOF": lambda self, a, p: self._tof(a[0], p) or p,
    "CTU": lambda self, a, p: self._count(a[0], p, up=True) or p,
    "CTD": lambda self, a, p: self._count(a[0], p, up=False) or p,
    "RES": Simulator._res, "MOV": Simulator._mov, "CLR": Simulator._clr, "COP": Simulator._cop,
    "CPT": Simulator._cpt, "CMP": Simulator._cmp, "JSR": Simulator._jsr,
}
