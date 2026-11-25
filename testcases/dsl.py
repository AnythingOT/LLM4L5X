"""The step language: text in, Scenario objects out. Errors name the line and what to write instead."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field

ACTIONS = ("SET", "EXPECT", "WAIT", "RESET", "COMMENT", "CALL")
OPS = ("==", "!=", "<=", ">=", "<", ">")
PHASES = ("SETUP", "MAIN", "TEARDOWN")
_TAG = r"(?:PLANT:)?[A-Za-z_][A-Za-z0-9_]*(?:\[\d+\])?(?:\.[A-Za-z_0-9]+)*"


class ScenarioError(ValueError):
    pass


@dataclass
class Step:
    action: str
    phase: str
    line: int
    tag: str = ""
    op: str = ""
    value: object = None
    within_ms: float | None = None
    hold: bool = False
    tolerance: float = 0.0
    text: str = ""  # COMMENT text, CALL target, the source line for reports


@dataclass
class Scenario:
    id: str
    title: str = ""
    reqs: tuple[str, ...] = ()
    steps: list[Step] = field(default_factory=list)


def _value(text: str, line: int) -> object:
    t = text.strip()
    if re.fullmatch(r"(?i)true|on", t):
        return 1
    if re.fullmatch(r"(?i)false|off", t):
        return 0
    try:
        return int(t) if re.fullmatch(r"[+-]?\d+", t) else float(t)
    except ValueError:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", t):
            return t  # a word: a plant fault name, or none
        raise ScenarioError(f"line {line}: {text!r} is not a number, TRUE/FALSE or a word") from None


def _expect(rest: str, phase: str, n: int, src: str) -> Step:
    m = re.fullmatch(rf"({_TAG})\s*(==|!=|<=|>=|<|>)\s*(\S+)(.*)", rest)
    if not m:
        raise ScenarioError(f"line {n}: write EXPECT <tag> <op> <value> [within_ms N [hold]] [tolerance X], "
                            f"op one of {' '.join(OPS)}")
    s = Step("EXPECT", phase, n, m.group(1), m.group(2), _value(m.group(3), n), text=src)
    mods = m.group(4).split()
    i = 0
    while i < len(mods):
        word = mods[i].lower()
        if word in ("within_ms", "tolerance", "±", "+-") and i + 1 < len(mods):
            try:
                num = float(mods[i + 1])
            except ValueError:
                raise ScenarioError(f"line {n}: {mods[i]} needs a number, got {mods[i + 1]!r}") from None
            if num < 0:
                raise ScenarioError(f"line {n}: {mods[i]} cannot be negative")
            if word == "within_ms":
                s.within_ms = num
            else:
                s.tolerance = num
            i += 2
        elif word in ("hold", "hold_until_deadline"):
            s.hold = True
            i += 1
        else:
            raise ScenarioError(f"line {n}: unknown {mods[i]!r} after EXPECT; use within_ms N, hold, tolerance X")
    if s.hold and s.within_ms is None:
        raise ScenarioError(f"line {n}: hold needs within_ms N (how long the value must stay)")
    if s.tolerance and not isinstance(s.value, (int, float)):
        raise ScenarioError(f"line {n}: tolerance only applies to numbers")
    return s


def parse_scenarios(text: str) -> list[Scenario]:
    out: list[Scenario] = []
    cur: Scenario | None = None
    phase = "MAIN"
    for n, raw in enumerate(text.splitlines(), 1):
        src = raw.split("#", 1)[0].strip() if not raw.strip().upper().startswith("COMMENT") else raw.strip()
        if not src:
            continue
        head = src.split(None, 1)[0].upper().rstrip(":")
        if head == "SCENARIO":
            try:
                words = shlex.split(src)[1:]
            except ValueError as e:
                raise ScenarioError(f"line {n}: {e}") from None
            if not words:
                raise ScenarioError(f"line {n}: SCENARIO needs an id, e.g. SCENARIO TC-07 \"title\" REQ R3")
            sid, rest = words[0], words[1:]
            reqs: list[str] = []
            title = ""
            if "REQ" in [w.upper() for w in rest]:
                k = [w.upper() for w in rest].index("REQ")
                reqs = [r for w in rest[k + 1:] for r in w.split(",") if r]
                rest = rest[:k]
            title = " ".join(rest)
            if any(s.id == sid for s in out):
                raise ScenarioError(f"line {n}: scenario {sid} is defined twice")
            cur = Scenario(sid, title, tuple(reqs))
            out.append(cur)
            phase = "MAIN"
            continue
        if cur is None:
            raise ScenarioError(f"line {n}: start with SCENARIO <id> before any step")
        if head in PHASES and src.rstrip(":").upper() == head:
            phase = head
            continue
        if head not in ACTIONS:
            raise ScenarioError(f"line {n}: {head!r} is not an action; use {', '.join(ACTIONS)} "
                                f"(or a phase: {', '.join(p + ':' for p in PHASES)})")
        rest = src.split(None, 1)[1].strip() if len(src.split(None, 1)) > 1 else ""
        if head == "COMMENT":
            cur.steps.append(Step("COMMENT", phase, n, text=rest))
        elif head == "CALL":
            if not rest:
                raise ScenarioError(f"line {n}: CALL needs a scenario id")
            cur.steps.append(Step("CALL", phase, n, text=rest.split()[0]))
        elif head == "WAIT":
            m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(ms)?", rest, re.I)
            if not m:
                raise ScenarioError(f"line {n}: write WAIT <milliseconds>, e.g. WAIT 1000")
            cur.steps.append(Step("WAIT", phase, n, value=float(m.group(1)), text=src))
        elif head == "RESET":
            if not re.fullmatch(_TAG, rest):
                raise ScenarioError(f"line {n}: write RESET <tag> (sets it to 0 / FALSE)")
            cur.steps.append(Step("RESET", phase, n, rest, value=0, text=src))
        elif head == "SET":
            m = re.fullmatch(rf"({_TAG})\s*=\s*(\S+)", rest)
            if not m:
                raise ScenarioError(f"line {n}: write SET <tag> = <value>")
            cur.steps.append(Step("SET", phase, n, m.group(1), value=_value(m.group(2), n), text=src))
        else:
            cur.steps.append(_expect(rest, phase, n, src))
    ids = {s.id for s in out}
    for s in out:
        for st in s.steps:
            if st.action == "CALL" and st.text not in ids:
                raise ScenarioError(f"line {st.line}: CALL {st.text}: no such scenario")
            if st.action == "CALL" and st.text == s.id:
                raise ScenarioError(f"line {st.line}: scenario {s.id} calls itself")
    return out
