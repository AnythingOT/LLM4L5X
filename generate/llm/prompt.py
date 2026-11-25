"""The system prompt and the examples and tags each request is shown."""

from __future__ import annotations

from pathlib import Path

import yaml

from .names import _words


EXAMPLES_FILE = Path(__file__).parent.parent / "examples.yaml"

SYSTEM_PROMPT = """You turn plain-English PLC control descriptions into LogicSpec.
Reply with LogicSpec statements only, each ending with ';'. No explanations, no code fences.

LogicSpec:
  X := condition;                      X is on while the condition is true
  IF condition THEN action, action;    do the actions while the condition is true
  IF TRUE THEN action;                 always
Conditions: Tag, NOT Tag, AND, OR, comparisons (= <> > < >= <=),
  RISE(condition) = only at the moment it becomes true,
  DELAY(condition, 5s) = condition has been true for 5 s,
  OFFDELAY(condition, 5s) = condition is true or went false less than 5 s ago.
Actions: ENERGIZE X (on while the condition is true; a coil); SET X (latch); RESET X (unlatch);
  CLEAR N; N := value; N := A + B (also - * /);
  COUNT_UP(C, 10); COUNT_DOWN(C, 10); RESET_ACC C;
  ON_DELAY_TIMER(T, 5s) (TON); OFF_DELAY_TIMER(T, 5s) (TOF);
  COPY(Source, Dest, 10) copies 10 array elements.
Rules:
  - Never mix AND and OR without parentheses: write (A AND B) OR C.
  - "keeps running until", "stays on until" = seal-in: X := (Start OR X) AND NOT Stop;
  - "turn on"/"energize" with other actions = ENERGIZE; "latch"/"keep it set" = SET; "unlatch" = RESET.
  - "turn on"/"switch on X if C" with no other action = X := C; SET only for "latch"/"keep on"/"stays on".
  - The words decide the instruction, never the tag's name: "turn on Alarm_Latch" is ENERGIZE Alarm_Latch
    (or Alarm_Latch := C; when it is the only action), never SET.
  - "on-delay timer" = ON_DELAY_TIMER; "off-delay timer" = OFF_DELAY_TIMER. Match the words.
  - "either A or B, and C" = (A OR B) AND C: the part after ", and" still applies.
  - "subtract/divide/... and store the result in C" changes ONLY C: C := B - A; never B := ...
  - RISE(X) only when the request says so: "rising edge", "the moment", "each time", "once", "goes from off to on".
  - RISE covers only the signal whose edge is meant: "when A goes from off to on and B is on" = RISE(A) AND B;
    RISE(A AND B) would also fire when B turns on while A is already on.
  - "move A to B", "copy A into B", "store A in B" = B := A; (the destination is on the left).
  - Several actions under one condition: ONE IF with commas, IF c THEN a, b, c; (';' ends the IF).
  - COUNT_UP and COUNT_DOWN already count once per rising edge: do not wrap their condition in RISE.
  - "reset the counter/timer C" = RESET_ACC C.
  - Copy tag names EXACTLY as written in the request (same spelling, case and underscores).
  - Times need units: 500ms, 5s, 2min, 1h."""


def load_examples(path: Path = EXAMPLES_FILE) -> list[dict]:
    return yaml.safe_load(path.read_text("utf-8")) or []


def pick_examples(request: str, examples: list[dict], k: int = 5) -> list[dict]:
    """Most similar examples by word overlap; always at least the first (basic) one."""
    rw = _words(request)
    scored = sorted(examples, key=lambda e: -len(rw & _words(e["english"])))
    chosen = scored[:k]
    if examples and examples[0] not in chosen:
        chosen[-1] = examples[0]
    return chosen


def pick_tags(request: str, tags: dict[str, str], descriptions: dict[str, str] | None = None,
              k: int = 30) -> list[tuple[str, str, str]]:
    """Project tags most related to the request: (name, type, description)."""
    descriptions = descriptions or {}
    rw = _words(request)
    lower = request.lower()
    scored = []
    for name, dtype in tags.items():
        if dtype in ("ALIAS", "") or ":" in name:
            continue
        tw = _words(name) | _words(descriptions.get(name, ""))
        score = 3 * len(rw & _words(name)) + len(rw & tw)
        if name.lower() in lower:
            score += 10
        if score:
            scored.append((score, name, dtype))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [(n, t, descriptions.get(n, "")) for _, n, t in scored[:k]]
