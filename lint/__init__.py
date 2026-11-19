"""Static checks against a fixed checklist of PLC programming rules (CRT/ERR/WAR/INF codes).

    report = run(project, disabled={"INF004"})
    findings = check_rungs(rungs, tag_types)   # rung rules only, e.g. on generated logic

It only reports; it never changes the project. Rules are in lint/rules.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.catalog import Catalog
from core.rung import Rung
from l5x.reader import Project, RoutineInfo, RungInfo, TagInfo
from lint import checks_io, checks_lifecycle, checks_logic, checks_project, checks_tags, checks_udt  # noqa: F401
from lint.context import Context, Finding
from lint.registry import CHECKS
from lint.rules import BY_CODE, RULES, SEVERITY

__all__ = ["run", "check_rungs", "Report", "Finding", "RULES", "BY_CODE"]

_ORDER = {s: i for i, s in enumerate(SEVERITY.values())}


@dataclass
class Report:
    findings: list[Finding]
    suppressed: list[Finding] = field(default_factory=list)
    not_verified: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)  # a check that crashed: never a silent pass
    notes: list[str] = field(default_factory=list)  # what was not analysed
    disabled: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out = {s: 0 for s in SEVERITY.values()}
        for f in self.findings:
            out[f.severity] += 1
        return out

    def to_dict(self) -> dict:
        return {"findings": [f.to_dict() for f in self.findings],
                "suppressed": [f.to_dict() for f in self.suppressed],
                "not_verified": [f"{c}: {why}" for c, why in sorted(self.not_verified.items())],
                "errors": self.errors, "notes": self.notes, "counts": self.counts(), "disabled": self.disabled}


def _run_checks(ctx: Context, enabled: set[str]) -> tuple[list[Finding], list[str]]:
    findings, errors = [], []
    for codes, fn in CHECKS:
        if not enabled.intersection(codes):
            continue
        try:
            findings += [f for f in fn(ctx) if f.code in enabled]
        except Exception as e:  # noqa: BLE001 - report it, keep the other rules running
            errors.append(f"{fn.__name__}: {e!r}")
    findings.sort(key=lambda f: (_ORDER[f.severity], f.code))
    return findings, errors


def run(project: Project, disabled=(), catalog: Catalog | None = None) -> Report:
    """All enabled rules. On a partial export (program, routine, rung) only the rung rules
    run: the others need tasks, modules and descriptions that such an export leaves out."""
    disabled = {c.upper() for c in disabled}
    ctx = Context.build(project, catalog)
    full = project.is_full_export
    enabled = {r.code for r in RULES if r.code not in disabled and (full or r.scope == "rung")}
    findings, errors = _run_checks(ctx, enabled)
    kept, suppressed = _suppress(findings, project)
    notes = []
    if not full:
        notes.append(f"This is a {project.target_type or 'partial'} export: only the {sum(r.scope == 'rung' for r in RULES)} "
                     "rung rules ran. Export the whole controller for the project rules.")
    non_ladder = [rt for rt in project.routines if rt.usage_text]
    if non_ladder:
        notes.append(f"{len(non_ladder)} ST/FBD/SFC routine(s) are not analysed (their tag references still count as use).")
    protected = [rt for rt in project.routines if rt.protected] + \
                [rt for a in project.aois.values() for rt in a.routines if rt.protected]
    if protected or project.protected_aois:
        notes.append(f"{len(protected) + len(project.protected_aois)} protected routine(s)/AOI(s) cannot be read.")
    if ctx.unparsed:
        notes.append(f"{len(ctx.unparsed)} rung(s) did not parse: only their comments and tag names were checked; see the import checks.")
    return Report(kept, suppressed, ctx.not_verified, errors, notes, sorted(disabled))


def check_rungs(rungs: list[Rung], tag_types: dict[str, str] | None = None, catalog: Catalog | None = None,
                disabled=()) -> list[Finding]:
    """Rung rules on loose rungs (generated logic): no project needed."""
    tags = {n: TagInfo(n, t, "controller") for n, t in (tag_types or {}).items()}
    rt = RoutineInfo("Routine", "RLL", "Program",
                     [RungInfo(i, "", r.comment, r) for i, r in enumerate(rungs)])
    proj = Project("Controller", None, "Rung", tags, [rt], {}, {})
    ctx = Context.build(proj, catalog)
    for ref in ctx.rungs:
        ref.location = f"Rung {ref.number}"
    disabled = {c.upper() for c in disabled}
    findings, _ = _run_checks(ctx, {r.code for r in RULES if r.scope == "rung" and r.code not in disabled})
    return findings


# ---------------------------------------------------------------- suppression

_DIRECTIVE = re.compile(r"lint:disable(?:=([A-Za-z0-9_,\s]*))?", re.I)


def _directive(text: str | None):
    """None, "*" (everything) or a set of codes from a 'lint:disable[=CODE,...]' note."""
    m = _DIRECTIVE.search(text or "")
    if not m:
        return None
    codes = {c.strip().upper() for c in (m.group(1) or "").split(",") if c.strip()}
    return codes or "*"


def _suppress(findings: list[Finding], project: Project) -> tuple[list[Finding], list[Finding]]:
    """Honour 'lint:disable' written in a rung comment, a tag description or an AOI description.
    Suppressed findings are returned too: hidden from the list, never thrown away."""
    sup = {}
    for t in project.tags.values():
        d = _directive(t.description)
        if d:
            sup[f"Controller:{t.name}" if t.scope == "controller" else f"{t.scope}:{t.name}"] = d
    for rt in project.routines + [r for a in project.aois.values() for r in a.routines]:
        for r in rt.rungs:
            d = _directive(r.comment)
            if d:
                sup[f"{rt.program} / {rt.name} / Rung {r.number}"] = d
    for a in project.aois.values():
        d = _directive(a.description)
        if d:
            sup[f"AOI:{a.name}"] = d
    if not sup:
        return findings, []
    kept, hidden = [], []
    for f in findings:
        d = sup.get(f.location)
        if d is None and f.location.startswith("AOI:"):
            d = sup.get(f.location.split(" /")[0])
        (hidden if d is not None and (d == "*" or f.code in d) else kept).append(f)
    return kept, hidden
