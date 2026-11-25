"""Do two sets of rungs behave the same?

Replaces string equality (Excel EXACT) as the test oracle. Both rung sets run
in the scan simulator on the same random input sequences: several scans each,
with time passing so timers can finish. After every scan every observable
output is compared. Equivalent rungs written differently (condition order,
v35 vs v36 names, a helper rung vs an inline ONS, other internal tag names)
pass; logic that behaves differently fails, with the first difference.

Internal tags (one-shot storage, compiler helper bits, auto timers) are not
compared; only what a user would observe: coils, latched bits, math and move
destinations, counter values and named timers' done bits.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

from core.catalog import Catalog, default_catalog
from core.rung import Rung, base_tag, format_rung, is_literal, is_placeholder, walk
from core.simulator import SimError, Simulator, _num

INTERNAL = re.compile(r"^(L4X_|REF_)")
_V36 = {"EQ": "EQU", "NE": "NEQ", "GT": "GRT", "LT": "LES", "GE": "GEQ", "LE": "LEQ",
        "LIMIT": "LIM", "MOVE": "MOV"}
_TIMERS = {"TON", "TOF", "RTO"}
_COUNTERS = {"CTU", "CTD"}


@dataclass
class Side:
    rungs: list[Rung]
    presets: dict[str, int]  # timer/counter tag -> PRE


def _internal(ref: str) -> bool:
    return bool(INTERNAL.match(base_tag(ref) or ref))


def _refs(side: Side, cat: Catalog):
    """(bool inputs, numeric inputs, observable outputs, literals)."""
    reads_b, reads_n, writes, lits = set(), set(), set(), set()
    for r in side.rungs:
        for ins in walk(r.body):
            spec = cat.get(ins.name)
            if spec is None:
                raise SimError(f"no simulation for {ins.name}")
            name = _V36.get(ins.name.upper(), ins.name.upper())
            if name == "COP":
                n = int(_num(ins.args[2])) if is_literal(ins.args[2]) else 1
                sb, si = _arr(ins.args[0])
                db, di = _arr(ins.args[1])
                for k in range(n):
                    reads_n.add(f"{sb}[{si + k}]" if (n > 1 or "[" in ins.args[0]) else ins.args[0])
                    writes.add(f"{db}[{di + k}]" if (n > 1 or "[" in ins.args[1]) else ins.args[1])
                continue
            for op, arg in zip(spec.operands, ins.args):
                if op.role == "display" or is_placeholder(arg) or arg == "":
                    continue
                if is_literal(arg):
                    lits.add(_num(arg))
                    continue
                if op.role == "read":
                    (reads_b if op.type == "BOOL" else reads_n).add(arg)
                elif op.role == "write":
                    writes.add(arg)
                elif op.role == "struct":
                    if name in _TIMERS:
                        writes |= {f"{arg}.DN", f"{arg}.PRE"}
                    elif name in _COUNTERS:
                        writes |= {f"{arg}.ACC", f"{arg}.DN", f"{arg}.PRE"}
                    elif name == "RES":
                        writes |= {f"{arg}.ACC", f"{arg}.DN"}
    return reads_b, reads_n, writes, lits


def _bool_writes(side: Side, cat: Catalog) -> set[str]:
    out = set()
    for r in side.rungs:
        for ins in walk(r.body):
            spec = cat.get(ins.name)
            for op, arg in zip(spec.operands if spec else (), ins.args):
                if op.role == "write" and op.type == "BOOL":
                    out.add(arg)
    return out


def _arr(ref: str) -> tuple[str, int]:
    m = re.fullmatch(r"(.+)\[(\d+)\]", ref.strip())
    return (m.group(1), int(m.group(2))) if m else (ref.strip(), 0)


def _start_state(side: Side) -> dict:
    return {f"{t}.PRE": p for t, p in side.presets.items()}


def _norm_text(rungs: list[Rung]) -> list[str]:
    out = []
    for r in rungs:
        t = format_rung(r)
        for new, old in _V36.items():
            t = re.sub(rf"\b{new}\(", f"{old}(", t)
        out.append(t)
    return out


def compare(expected: Side, got: Side, seed: int = 0, sequences: int = 80, scans: int = 10,
            catalog: Catalog | None = None) -> tuple[bool, str]:
    """(same behaviour?, reason if not)."""
    cat = catalog or default_catalog()
    try:
        eb, en, ew, el = _refs(expected, cat)
        gb, gn, gw, gl = _refs(got, cat)
    except SimError:
        same = _norm_text(expected.rungs) == _norm_text(got.rungs)
        return same, "" if same else "different rung text (instruction not simulated, compared as text)"

    observable = {w for w in ew | gw if not _internal(w)}
    extra = sorted({base_tag(w) for w in gw - ew if not _internal(w)} - {base_tag(w) for w in ew})
    if extra:
        return False, f"writes {', '.join(extra)}, which the expected logic does not"
    written = ew | gw
    bools = sorted((eb | gb) - written - {w.split(".")[0] for w in written if _internal(w)})
    nums = sorted((en | gn) - written - set(bools))
    pool = sorted({v for x in el | gl | {0, 5, 10} for v in (x - 1, x, x + 1)} - {0} | {0})
    rng = random.Random(seed)
    out_bools = {w for w in (ew | gw) if "." not in w and "[" not in w and w in (_bool_writes(expected, cat) |
                                                                                  _bool_writes(got, cat))}
    for _ in range(sequences):
        # outputs start at random values (same on both sides), so CLR on a value that is
        # already 0, or OTU on a bit that is already off, still shows a difference
        init = {}
        for w in sorted(observable):
            if w.endswith((".DN", ".PRE")):
                continue
            if w.endswith(".ACC"):
                init[w] = rng.randint(0, 5)
            elif w in out_bools:
                init[w] = rng.random() < 0.5
            else:
                init[w] = rng.choice([v for v in pool if v != 0] or [7])
        se = Simulator(expected.rungs, {**_start_state(expected), **init})
        sg = Simulator(got.rungs, {**_start_state(got), **init})
        inputs = {b: rng.random() < 0.5 for b in bools}
        inputs.update({n: rng.choice(pool) for n in nums})
        for k in range(scans):
            for b in bools:  # inputs mostly persist so timers and edges get exercised
                if rng.random() < 0.35:
                    inputs[b] = not inputs[b]
            for n in nums:
                if rng.random() < 0.35:
                    inputs[n] = rng.choice(pool)  # includes 0: equality with 0 must be reachable
            dt = rng.choice([0, 300, 1000, 2500, 6000])
            try:
                ae = dict(se.scan(dt, dict(inputs)))
            except SimError as e:
                ae = {"__error__": str(e)}
            try:
                ag = dict(sg.scan(dt, dict(inputs)))
            except SimError as e:
                ag = {"__error__": str(e)}
            for key in sorted(observable | {"__error__"}):
                a, b = ae.get(key, 0), ag.get(key, 0)
                if isinstance(a, (bool, int, float)) and isinstance(b, (bool, int, float)):
                    if abs(float(a) - float(b)) <= 1e-6 * max(1.0, abs(float(a))):
                        continue
                elif a == b:
                    continue
                shown = {x: (int(v) if isinstance(v, bool) else v) for x, v in inputs.items()}
                return False, f"{key}: expected {_show(a)}, got {_show(b)} (scan {k + 1}, inputs {shown})"
    return True, ""


def _show(v):
    return int(v) if isinstance(v, bool) else v
