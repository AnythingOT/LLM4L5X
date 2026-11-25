"""Tag names in requests and specs: what the user wrote, what the model wrote."""

from __future__ import annotations

import re




_WORD = re.compile(r"[A-Za-z]+|\d+")


def _words(text: str) -> set[str]:
    """Lower-case words; tag names are split on _ and camelCase."""
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return {w.lower() for w in _WORD.findall(text.replace("_", " ")) if len(w) > 1}


# ---------------------------------------------------------------- Ollama


def extract_spec(reply: str) -> str:
    """LogicSpec statements from a model reply: drops thinking, fences and prose.

    A statement may span lines ("IF ... THEN" newline "X := Y;"), so lines are joined
    until the ';' that ends the statement.
    """
    text = re.sub(r"<think>.*?</think>", "", reply, flags=re.S | re.I)
    text = re.sub(r"```[a-zA-Z]*", "", text)
    keep: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        line = line.strip().strip("`").strip()
        line = re.sub(r"^\s*(\d+[.)]|[-*])\s+", "", line)  # list markers
        if not line:
            continue
        # "IF" in capitals only: "If you need..." is prose
        if not buf and not re.match(r"(IF\b|[A-Za-z_][\w.\[\]:]*\s*:=)", line):
            continue
        buf.append(line)
        if ";" in line:
            stmt = " ".join(buf)
            keep.append(stmt[: stmt.rindex(";") + 1])
            buf = []
    return "\n".join(keep)


# ---------------------------------------------------------------- generator


_TAGLIKE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b|\b[A-Za-z]*[a-z][A-Z][A-Za-z0-9]*\b"
                      r"|\b[A-Z]{1,4}\d{2,}[A-Za-z0-9_]*\b")


def request_identifiers(request: str) -> set[str]:
    """Tag-like names written in the request: Pump_Run, FlowRate, PT101_PV."""
    from core.logicspec import KEYWORDS
    return {m for m in _TAGLIKE.findall(request) if m.upper() not in KEYWORDS}


_PLAIN = re.compile(r"(?<![\w.])[A-Z][A-Za-z0-9]*(?![\w(])")
_NOT_TAGS = {
    "A", "AN", "THE", "IF", "WHEN", "WHILE", "THEN", "ELSE", "OTHERWISE", "AND", "OR", "NOT", "EITHER",
    "BOTH", "IS", "ARE", "ON", "OFF", "TRUE", "FALSE", "TURN", "SWITCH", "SET", "RESET", "CLEAR", "STORE",
    "COPY", "MOVE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "RUN", "START", "STOP", "COUNT", "LATCH",
    "UNLATCH", "ENERGIZE", "KEEP", "HOLD", "WAIT", "AFTER", "BEFORE", "FOR", "WITH", "TO", "IN", "AT", "OF",
}


def plain_names(request: str) -> set[str]:
    """Capitalised words that may be tag names although they do not look like one: Beacon, D.
    "A" counts only as a subject ("A is on"), since it is usually the article."""
    from core.logicspec import KEYWORDS
    out = set()
    for m in _PLAIN.finditer(request):
        w = m.group(0)
        if w == "A" and not re.match(r"\s+(is|are|was)\b", request[m.end():]):
            continue
        if w.upper() in KEYWORDS or (w.upper() in _NOT_TAGS and w != "A"):
            continue
        out.add(w)
    return out


def _norm(name: str) -> str:
    return name.replace("_", "").lower()


def spec_tags(spec: str) -> set[str]:
    """Base tag names used in LogicSpec text."""
    from core.logicspec import tokenize
    out = set()
    for t in tokenize(spec):
        if t.kind == "TAG":
            out.add(re.split(r"[.\[]", t.value)[0])
    return out


def snap_tags(spec: str, allowed: set[str]) -> tuple[str, list[str]]:
    """Fix tag names that differ from an allowed name only in case or underscores
    (Press_Hi_Limit -> PressHiLimit, SPEED_REF -> Speed_Ref). Unambiguous matches only."""
    from core.logicspec import tokenize
    by_norm: dict[str, list[str]] = {}
    for a in allowed:
        by_norm.setdefault(_norm(a), []).append(a)
    fixes, out, last = [], [], 0
    for t in tokenize(spec):
        if t.kind != "TAG":
            continue
        base = re.split(r"[.\[]", t.value)[0]
        if base in allowed:
            continue
        cand = by_norm.get(_norm(base), [])
        if len(cand) == 1:
            out.append(spec[last:t.pos] + cand[0])
            last = t.pos + len(base)
            fixes.append(f"{base} -> {cand[0]}")
    out.append(spec[last:])
    return "".join(out), sorted(set(fixes))
