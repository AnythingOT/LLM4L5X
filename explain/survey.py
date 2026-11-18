"""Survey a folder of L5X exports: does our parser, catalog and decompiler
agree with real files? Used to confirm format details and find gaps.

    python cli.py survey path/to/folder
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from core.ascii import AsciiSyntaxError, format_ascii, parse_ascii_rung
from core.rung import format_rung, walk
from core.validator import validate
from explain.decompiler import try_decompile
from l5x.reader import read_l5x


@dataclass
class Survey:
    files: int = 0
    unreadable: list[tuple[str, str]] = field(default_factory=list)
    rungs: int = 0
    parsed: int = 0
    exact_round_trip: int = 0
    ascii_round_trip: int = 0
    ascii_failures: list[tuple[str, str, str]] = field(default_factory=list)  # file, rung, reason
    convertible: int = 0
    mismatches: list[tuple[str, str, str]] = field(default_factory=list)  # file, original, ours
    unknown_instructions: Counter = field(default_factory=Counter)
    timer_display_forms: Counter = field(default_factory=Counter)
    not_convertible: Counter = field(default_factory=Counter)
    issues: Counter = field(default_factory=Counter)

    def report(self) -> str:
        pct = lambda a, b: f"{a}/{b} ({100 * a / b:.1f}%)" if b else "0/0"
        lines = [
            f"files read:              {self.files - len(self.unreadable)}/{self.files}",
            f"rungs parsed:            {pct(self.parsed, self.rungs)}",
            f"exact round trip:        {pct(self.exact_round_trip, self.parsed)}",
            f"ASCII round trip:        {pct(self.ascii_round_trip, self.parsed)}",
            f"convertible to LogicSpec:{pct(self.convertible, self.parsed):>16}",
            f"timer/counter operands:  {dict(self.timer_display_forms) or 'none seen'}",
            f"instructions not in catalog (AOIs excluded): {self.unknown_instructions.most_common(15) or 'none'}",
            "top reasons not convertible:",
            *[f"  {n:5d}  {r}" for r, n in self.not_convertible.most_common(8)],
            "top validator findings:",
            *[f"  {n:5d}  [{lvl}] {m}" for (lvl, m), n in self.issues.most_common(10)],
        ]
        if self.unreadable:
            lines.append("unreadable files:")
            lines += [f"  {f}: {e}" for f, e in self.unreadable[:10]]
        if self.ascii_failures:
            lines.append("ASCII round-trip failures (first 5):")
            lines += [f"  {f}: {why}\n    {r[:150]}" for f, r, why in self.ascii_failures[:5]]
        if self.mismatches:
            lines.append("round-trip differences (first 5):")
            for f, a, b in self.mismatches[:5]:
                lines += [f"  {f}", f"    file: {a[:150]}", f"    ours: {b[:150]}"]
        return "\n".join(lines)


def _generic(msg: str) -> str:
    """Strip tag names so similar findings group together."""
    msg = re.sub(r"\b(tag|bit) \S+", r"\1 <tag>", msg)
    msg = re.sub(r": \S+ is (\S+),", r": <tag> is \1,", msg)
    msg = re.sub(r"rungs? \[[^\]]*\]", "rungs [...]", msg)
    return msg[:90]


def survey(folder: str | Path) -> Survey:
    s = Survey()
    for f in sorted(Path(folder).rglob("*")):
        if f.suffix.lower() != ".l5x" or not f.is_file():
            continue
        s.files += 1
        try:
            p = read_l5x(f)
        except Exception as e:  # report and keep going
            s.unreadable.append((str(f), str(e)[:120]))
            continue
        cat = p.catalog()
        presets = p.presets()
        for rt in p.routines:
            good = []
            for r in rt.rungs:
                s.rungs += 1
                if r.rung is None:
                    s.issues[("error", "rung text does not parse")] += 1
                    continue
                s.parsed += 1
                good.append(r.rung)
                ours = format_rung(r.rung)
                if ours == r.text:
                    s.exact_round_trip += 1
                else:
                    s.mismatches.append((f.name, r.text, ours))
                try:
                    back = parse_ascii_rung(format_ascii(r.rung), cat)
                    if back.body == r.rung.body:
                        s.ascii_round_trip += 1
                    else:
                        s.ascii_failures.append((f.name, r.text, "different after round trip"))
                except AsciiSyntaxError as e:
                    s.ascii_failures.append((f.name, r.text, str(e)[:100]))
                for ins in walk(r.rung.body):
                    if cat.get(ins.name) is None:
                        s.unknown_instructions[ins.name] += 1
                    if ins.name.upper() in ("TON", "TOF", "RTO", "CTU", "CTD"):
                        s.timer_display_forms[",".join(a if a == "?" else "value" for a in ins.args[1:])] += 1
                stmts, why = try_decompile(r.rung, presets)
                if stmts:
                    s.convertible += 1
                else:
                    s.not_convertible[re.sub(r"\b[A-Z][A-Za-z_0-9]*(?= (is|has|in|with|inside))", "<instr>", why)] += 1
            for i in validate(good, p.tag_types(rt.program), catalog=cat, revision=p.software_revision,
                              string_types=p.string_types):
                s.issues[(i.level, _generic(i.message))] += 1
    return s
