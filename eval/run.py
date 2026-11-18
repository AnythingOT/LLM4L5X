"""Score a model on eval/requests.yaml by meaning, not text.

    python cli.py eval eval/requests.yaml --model phi4-mini
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from explain.equivalence import equivalent
from inputs.llm import Generator, LLMError


@dataclass
class Row:
    request: str
    expected: str
    got: str | None
    ok: bool
    reason: str
    attempts: int
    seconds: float


def run_eval(path: str | Path, client, limit: int | None = None, progress=None) -> list[Row]:
    cases = yaml.safe_load(Path(path).read_text("utf-8")) or []
    if limit:
        cases = cases[:limit]
    gen = Generator(client)
    rows = []
    for n, c in enumerate(cases, 1):
        try:
            r = gen.generate(c["request"], known_tags=c.get("tags"))
        except LLMError as e:
            raise SystemExit(f"error: {e}") from None
        if r.spec is None:
            row = Row(c["request"], c["expect"], None, False, r.error or "no answer", len(r.attempts), r.seconds)
        else:
            ok, why = equivalent(r.spec, c["expect"])
            row = Row(c["request"], c["expect"], r.spec, ok, why, len(r.attempts), r.seconds)
        rows.append(row)
        if progress:
            progress(n, len(cases), row)
    return rows


def report(rows: list[Row], model: str) -> str:
    ok = sum(r.ok for r in rows)
    valid = sum(r.got is not None for r in rows)
    first = sum(r.ok and r.attempts == 1 for r in rows)
    secs = [r.seconds for r in rows]
    lines = [
        f"model:            {model}",
        f"correct:          {ok}/{len(rows)} ({100 * ok / max(1, len(rows)):.0f}%)",
        f"correct 1st try:  {first}/{len(rows)}",
        f"valid LogicSpec:  {valid}/{len(rows)}",
        f"time per request: avg {sum(secs) / max(1, len(secs)):.1f}s, max {max(secs, default=0):.1f}s",
    ]
    bad = [r for r in rows if not r.ok]
    if bad:
        lines.append("\nwrong:")
        for r in bad:
            lines += [f"- {r.request}", f"    expected: {r.expected.strip()}",
                      f"    got:      {(r.got or '-').strip()}", f"    why:      {r.reason}"]
    return "\n".join(lines)
