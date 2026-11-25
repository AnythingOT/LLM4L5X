"""Evidence of a test run: requirements, traceability, results step by step, and what exactly was tested.

A run record is plain data (JSON), written once and never changed:

* **requirements** come from the user requirements workbook (the instruction sheet): a Req ID with the
  text of its rows. A row with no Req ID is a requirement of its own, named by sheet and row
  ("Pump row 6"), so no row drops out of the matrix. INFRA rows serve no requirement.
* **implementation**: a generated rung carries its Req IDs in its comment ("[R1, R3] Start the pump ...");
  a rung of a row with no Req ID is matched by its comment, which is the row's requirement text.
* **tests**: each test case names its requirements (REQ R1, R3).
* **results**: every step of every test case, with what was expected and what was read, and when.
* **fingerprints** (SHA-256) of every input file, of the device models and test cases, and of the tool's
  own code: a later run on anything changed shows as different.

The record's own fingerprint is printed in the PDF report, so a report can be checked against its record.
This is engineering evidence from the scan simulator, not a validated record and not evidence about the
controller; the report says so.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_CODE_DIRS = ("core", "l5x", "lint", "scenario", "plant", "gui", "explain", "inputs", "udt", "library", "eval")
_COMMENT_REQS = re.compile(r"^\s*\[([^\]]+)\]\s*(.*)$", re.S)
FORMAT = 1


def sha256(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def code_fingerprint(root: Path = ROOT) -> str:
    """One hash over the tool's source files (path and content), so a report names the exact code that ran,
    with or without git."""
    h = hashlib.sha256()
    for d in _CODE_DIRS:
        for p in sorted((root / d).rglob("*")):
            if p.is_file() and p.suffix in (".py", ".js", ".html", ".css", ".json", ".yaml") \
                    and "__pycache__" not in p.parts:
                h.update(p.relative_to(root).as_posix().encode())
                h.update(b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


@dataclass
class Requirement:
    id: str
    text: str
    rows: list[str] = field(default_factory=list)  # "Pump row 6"
    from_row: bool = False  # a row with no Req ID, named by its sheet and row


def requirements_from_workbook(data: bytes) -> list[Requirement]:
    """The instruction sheet's requirements, in the order they first appear."""
    from generate.spec_excel import read_requirements
    out: dict[str, Requirement] = {}
    for sheet in read_requirements(data):
        for row in sheet.rows:
            where = f"{sheet.title} row {row.line}"
            text = (row.request or row.comment or row.logic or "").strip()
            if row.infra:
                continue
            ids = row.reqs or (where,)
            for rid in ids:
                r = out.setdefault(rid, Requirement(rid, "", [], from_row=not row.reqs))
                r.rows.append(where)
                if text and text not in r.text:
                    r.text = f"{r.text} {text}".strip() if r.text else text
    return list(out.values())


def rungs_by_requirement(l5x_files: list[bytes], reqs: list[Requirement]) -> tuple[dict[str, list[str]], list[str]]:
    """(requirement -> ["Pump rung 3", ...], rungs that serve no requirement)."""
    from l5x.reader import read_l5x
    by_text = {r.text.strip(): r.id for r in reqs if r.from_row}
    out: dict[str, list[str]] = {}
    orphans: list[str] = []
    for data in l5x_files:
        for rt in read_l5x(data).routines:
            for g in rt.rungs:
                where = f"{rt.name} rung {g.number}"
                m = _COMMENT_REQS.match(g.comment or "")
                ids = [i.strip() for i in m.group(1).split(",") if i.strip()] if m else []
                if not ids and (g.comment or "").strip() in by_text:
                    ids = [by_text[g.comment.strip()]]
                if ids:
                    for i in ids:
                        out.setdefault(i, []).append(where)
                elif g.rung is not None and any(True for _ in g.rung.instructions()):
                    orphans.append(where)
    return out, orphans


def matrix(reqs: list[Requirement], rungs: dict[str, list[str]], results: list[dict],
           program_given: bool) -> tuple[list[dict], dict]:
    """The traceability matrix (one row per requirement) and its gaps."""
    tests: dict[str, list[tuple[str, bool]]] = {}
    for r in results:
        for q in r["reqs"]:
            tests.setdefault(q, []).append((r["id"], r["passed"]))
    known = {r.id for r in reqs}
    rows = []
    for r in reqs + [Requirement(q, "", []) for q in sorted(set(rungs) | set(tests)) if q not in known]:
        t = tests.get(r.id, [])
        built = bool(rungs.get(r.id))
        if t and not all(ok for _, ok in t):
            status = "Fail"
        elif not t:
            status = "No test" if built or not program_given else "Not built, no test"
        elif program_given and not built:
            status = "Not built"
        else:
            status = "Pass"
        rows.append({"id": r.id, "text": r.text, "rows": r.rows, "known": r.id in known or not known,
                     "rungs": rungs.get(r.id, []), "tests": [{"id": i, "passed": ok} for i, ok in t],
                     "status": status})
    gaps = {
        "no_test": [x["id"] for x in rows if not x["tests"]],
        "not_built": [x["id"] for x in rows if program_given and not x["rungs"] and x["known"]],
        "unknown_requirement": [x["id"] for x in rows if not x["known"]],
        "tests_without_requirement": [r["id"] for r in results if not r["reqs"]],
    }
    return rows, gaps


def _actual(v):
    """A value as a PLC engineer reads it: a bit is 1 or 0."""
    if isinstance(v, bool):
        return int(v)
    return v if v is None or isinstance(v, (int, float, str)) else str(v)


def result_dict(res) -> dict:
    """A ScenarioResult as plain data, every step with its evidence."""
    return {"id": res.id, "title": res.title, "reqs": list(res.reqs), "passed": res.passed, "error": res.error,
            "steps": [{"line": s.line, "phase": s.phase, "action": s.action, "text": s.text,
                       "passed": s.passed, "actual": _actual(s.actual), "t_ms": s.t_ms, "message": s.message}
                      for s in res.steps]}


def run_record(*, program: list[tuple[str, bytes]], devices: str, tests: str, results: list,
               requirements: tuple[str, bytes] | None = None, scan_ms: float = 10.0,
               now: datetime | None = None) -> dict:
    """Everything a report needs, and the fingerprint that ties the report to it."""
    now = now or datetime.now().astimezone()
    reqs = requirements_from_workbook(requirements[1]) if requirements else []
    rungs, orphans = rungs_by_requirement([d for _, d in program], reqs)
    res = [result_dict(r) for r in results]
    rows, gaps = matrix(reqs, rungs, res, program_given=bool(program))
    gaps["rungs_without_requirement"] = orphans if reqs or rungs else []
    inputs = [{"kind": "program", "name": n, "sha256": sha256(d)} for n, d in program]
    if requirements:
        inputs.append({"kind": "requirements", "name": requirements[0], "sha256": sha256(requirements[1])})
    inputs += [{"kind": "device models", "name": "", "sha256": sha256(devices)},
               {"kind": "test cases", "name": "", "sha256": sha256(tests)}]
    passed = sum(r["passed"] for r in res)
    record = {
        "format": FORMAT,
        "created": now.isoformat(timespec="seconds"),
        "tool": {"name": "LLM4L5X", "code_sha256": code_fingerprint()},
        "target": {"name": "Scan simulator (LLM4L5X)", "scan_ms": scan_ms,
                   "note": "Simulated program and device models on this PC. Not a test of the controller."},
        "inputs": inputs,
        "summary": {"test_cases": len(res), "passed": passed, "failed": len(res) - passed,
                    "requirements": len(rows), "requirements_passed": sum(r["status"] == "Pass" for r in rows)},
        "matrix": rows,
        "gaps": gaps,
        "results": res,
        "devices": devices,
        "tests": tests,
    }
    record["id"] = now.strftime("%Y%m%d-%H%M%S") + "-" + fingerprint(record)[:8]
    return record


def fingerprint(record: dict) -> str:
    """SHA-256 of the record as canonical JSON, without its id (the id is made from this)."""
    body = {k: v for k, v in record.items() if k != "id"}
    return sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str))


class RunStore:
    """Run records on disk, one file each, written once: an earlier run is never changed or replaced."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def save(self, record: dict) -> Path:
        """Write the record; the same run twice in one second (same inputs, same results) gets "-2"."""
        self.folder.mkdir(parents=True, exist_ok=True)
        base, n = record["id"], 1
        while True:
            path = self.folder / f"{record['id']}.json"
            try:
                with open(path, "x", encoding="utf-8") as f:  # "x": never overwrite an earlier run
                    json.dump(record, f, ensure_ascii=False, indent=1, default=str)
                return path
            except FileExistsError:
                n += 1
                record["id"] = f"{base}-{n}"

    def get(self, run_id: str) -> dict | None:
        if not re.fullmatch(r"[\w-]+", run_id or ""):
            return None
        path = self.folder / f"{run_id}.json"
        return json.loads(path.read_text("utf-8")) if path.is_file() else None

    def list(self) -> list[dict]:
        out = []
        # newest first, by when the file was written (two runs in one second have the same timestamp)
        for p in sorted(self.folder.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True):
            try:
                r = json.loads(p.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            out.append({"id": r.get("id"), "created": r.get("created"), "summary": r.get("summary"),
                        "program": [i["name"] for i in r.get("inputs", []) if i.get("kind") == "program"]})
        return out
