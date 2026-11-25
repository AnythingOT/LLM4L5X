"""Measure the public L5X corpus and write the numbers into tests/TEST_STATUS.md.

Reads every export in a folder (the CI corpus: python -m eval.fetch_corpus corpus), and counts how many
rungs are read, explained in English, and how many ladder routines Energize can run whole (every instruction
simulated, AOI logic included). The section between the CORPUS markers in TEST_STATUS.md is replaced; the
rest of the file is written by hand. Run:  python -m eval.test_status corpus
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
from pathlib import Path

from core import simulator as sim
from core.catalog import default_catalog
from core.rung import walk
from explain.decompiler import try_decompile
from l5x.reader import read_l5x

STATUS = Path(__file__).resolve().parent.parent / "tests" / "TEST_STATUS.md"
BEGIN, END = "<!-- CORPUS:BEGIN (python -m eval.test_status) -->", "<!-- CORPUS:END -->"
SUPPORTED = set(sim._HANDLERS) | set(sim._COMPARE) | set(sim._MATH) | set(sim._V36)


def _aoi_ok(project) -> set[str]:
    """AOIs whose own logic the simulator can run (ladder, readable, every instruction known)."""
    ok: set[str] = set()
    pending = {a.name.upper(): a for a in project.aois.values()}
    changed = True
    while changed:  # an AOI may call another AOI: settle in rounds
        changed = False
        for name, a in list(pending.items()):
            logic = next((r for r in a.routines if r.name.upper() == "LOGIC"), None)
            if logic is None or logic.protected or not logic.is_ladder or any(x.rung is None for x in logic.rungs):
                del pending[name]
                continue
            names = {i.name.upper() for x in logic.rungs for i in walk(x.rung.body)}
            if names <= SUPPORTED | ok:
                ok.add(name)
                del pending[name]
                changed = True
    return ok


def measure(folder: Path) -> dict:
    files = sorted(p for p in folder.rglob("*") if p.suffix.lower() == ".l5x")
    n = collections.Counter()
    missing = collections.Counter()
    for f in files:
        try:
            p = read_l5x(f)
        except Exception:  # noqa: BLE001 - counted, not fatal
            n["unreadable"] += 1
            continue
        n["files"] += 1
        from gui.energize import EnergizeError, load
        if any(rt.is_ladder and rt.rungs and not rt.program.startswith("AOI:") for rt in p.routines):
            n["files_ladder"] += 1
            try:
                load([f.read_bytes()])
                n["files_run"] += 1
            except EnergizeError:
                pass
        presets = p.presets()
        aoi_ok = _aoi_ok(p)
        for rt in p.routines:
            if rt.program.startswith("AOI:") or not rt.is_ladder or not rt.rungs:
                continue
            n["routines"] += 1
            whole = True
            for x in rt.rungs:
                n["rungs"] += 1
                if x.rung is None:
                    whole = False
                    continue
                n["parsed"] += 1
                lack = {i.name.upper() for i in walk(x.rung.body)} - SUPPORTED - aoi_ok
                if lack:
                    whole = False
                    missing.update(lack)
                if try_decompile(x.rung, presets)[0]:
                    n["explained"] += 1
            n["runnable"] += whole
    cat = default_catalog()
    n["catalog"] = len(cat.names())
    n["simulated"] = len(SUPPORTED & set(cat.names()))
    return {"n": n, "missing": missing.most_common(10), "corpus": folder.name}


def render(m: dict, today: str) -> str:
    n = m["n"]
    pct = lambda a, b: f"{100 * a / max(b, 1):.1f}%"  # noqa: E731
    lack = ", ".join(f"{k} ({v})" for k, v in m["missing"])
    return "\n".join([
        BEGIN,
        f"Measured {today} with `python -m eval.test_status` on {n['files']} exports ({n['rungs']:,} rungs), "
        "MIT/Apache repositories pinned in `eval/corpus_sources.txt`.",
        "",
        "| What | Result |",
        "|---|---|",
        f"| Files read | {n['files']} of {n['files'] + n['unreadable']} |",
        f"| Rungs read (parsed) | {pct(n['parsed'], n['rungs'])} |",
        f"| Rungs explained in English | {pct(n['explained'], n['rungs'])} |",
        f"| Ladder routines Energize can run whole | {pct(n['runnable'], n['routines'])} ({n['runnable']} of {n['routines']}) |",
        f"| Whole exports with ladder that Energize loads (every routine and JSR target must run) | "
        f"{pct(n['files_run'], n['files_ladder'])} ({n['files_run']} of {n['files_ladder']}) |",
        f"| Catalog instructions the simulator has | {n['simulated']} of {n['catalog']}, plus JSR and readable AOI logic |",
        f"| Most common instructions it lacks (rungs) | {lack} |",
        END,
    ])


def write(m: dict, today: str | None = None) -> None:
    text = STATUS.read_text(encoding="utf-8")
    a, b = text.index(BEGIN), text.index(END) + len(END)
    STATUS.write_text(text[:a] + render(m, today or dt.date.today().strftime("%d %b %Y")) + text[b:],
                      encoding="utf-8", newline="\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("corpus", type=Path, help="folder of L5X exports")
    m = measure(ap.parse_args().corpus)
    write(m)
    print(render(m, "today"))


if __name__ == "__main__":
    main()
