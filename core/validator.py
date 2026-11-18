"""Static checks on rungs, independent of where they came from (model, compiler, project).

Errors mean "do not import". Warnings mean "a human should look".
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from core.catalog import Catalog, default_catalog, major_version
from core.rung import Branch, Instr, Rung, Series, base_tag, is_literal, is_placeholder, walk

import re

_STATUS_BIT = re.compile(r"\.(DN|TT|EN|CU|CD|OV|UN)$")

NUMERIC_TYPES = {"SINT", "INT", "DINT", "LINT", "REAL", "LREAL", "USINT", "UINT", "UDINT", "ULINT"}


@dataclass(frozen=True)
class Issue:
    level: str  # error | warning
    rung: int
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] rung {self.rung}: {self.message}"


def _last_is_output(s: Series, cat: Catalog) -> bool:
    if not s.items:
        return False
    last = s.items[-1]
    if isinstance(last, Branch):
        return all(_last_is_output(l, cat) for l in last.legs)
    spec = cat.get(last.name)
    return spec is None or spec.is_output  # unknown instructions are reported separately


def _branch_warnings(node, rung_no, out):
    if isinstance(node, Series):
        for it in node.items:
            _branch_warnings(it, rung_no, out)
    elif isinstance(node, Branch):
        for leg in node.legs:
            if not leg.items:
                out.append(Issue("warning", rung_no, "empty branch leg shorts the conditions around it"))
            _branch_warnings(leg, rung_no, out)


def validate(
    rungs: list[Rung],
    tag_types: dict[str, str] | None = None,
    catalog: Catalog | None = None,
    revision: str | None = None,
    string_types: set[str] | None = None,
) -> list[Issue]:
    """tag_types: {tag: datatype} for the project plus any new tags. Unknown tags are
    reported only when tag_types is given. string_types: data types that are strings
    (STRING plus the project's custom string types)."""
    cat = catalog or default_catalog()
    major = major_version(revision)
    strings = {s.upper() for s in (string_types or set())} | {"STRING"}
    types = {k: v.upper() for k, v in (tag_types or {}).items()}
    issues: list[Issue] = []
    ons_bits: dict[str, int] = {}
    ote_targets: dict[str, list[int]] = defaultdict(list)
    timer_users: dict[str, list[int]] = defaultdict(list)

    for n, r in enumerate(rungs):
        if not _last_is_output(r.body, cat):
            issues.append(Issue("error", n, "rung (or a branch leg at its end) does not end in an output instruction"))
        _branch_warnings(r.body, n, issues)
        for ins in walk(r.body):
            spec = cat.get(ins.name)
            if spec is None:
                inst = types.get(base_tag(ins.args[0]) or "") if ins.args else None
                if inst and inst.upper() == ins.name.upper():
                    # the instance tag's type is the instruction name: an Add-On Instruction
                    # whose definition is not in this export (or is source-protected)
                    issues.append(Issue("warning", n, f"{ins.name} is an Add-On Instruction whose definition is "
                                        "not in this export; its operands cannot be checked"))
                else:
                    issues.append(Issue("error", n, f"unknown instruction {ins.name}"))
                continue
            if not spec.available_in(major):
                if spec.min_version and major < spec.min_version:
                    old = next((i.name for i in cat.instructions.values() if i.renamed_to == spec.name), None)
                    hint = f"; use {old}" if old else ""
                    issues.append(Issue("error", n, f"{ins.name} needs v{spec.min_version}+, target is v{major}{hint}"))
                else:
                    issues.append(Issue("warning", n, f"{ins.name} was renamed {spec.renamed_to} in v{spec.max_version + 1}; target is v{major}"))
            if not spec.arity_ok(len(ins.args)):
                want = f"at least {len(spec.operands)}" if spec.variadic else str(len(spec.operands))
                issues.append(Issue("error", n, f"{ins.name} takes {want} operands, got {len(ins.args)}"))
                continue
            for op, arg in zip(spec.operands, ins.args):
                where = f"{ins.name} operand {op.name}"
                if op.optional and (arg == "" or is_placeholder(arg)):
                    continue
                if arg == "":
                    issues.append(Issue("error", n, f"{where} is empty"))
                    continue
                if is_placeholder(arg):
                    if op.role != "display":
                        issues.append(Issue("error", n, f"{where} is '?'"))
                    continue
                if op.role == "display":
                    continue
                if op.role in ("write", "struct") and is_literal(arg):
                    issues.append(Issue("error", n, f"{where} writes to a literal {arg}"))
                    continue
                if op.role == "write" and op.type == "BOOL" and _STATUS_BIT.search(arg):
                    issues.append(Issue("warning", n, f"{where} writes {arg}, which looks like a timer/counter status bit the instruction itself controls"))
                if op.type == "BOOL" and is_literal(arg):
                    issues.append(Issue("warning", n, f"{where} is a constant {arg}"))
                    continue
                if is_literal(arg) or op.type in ("EXPR", "ROUTINE", "NAME"):
                    continue
                b = base_tag(arg)
                # "Local:3:I", "S:FS": module-defined I/O and system tags are not <Tag> elements
                if tag_types is not None and b and ":" not in b and b not in types:
                    issues.append(Issue("error", n, f"{where}: tag {b} does not exist"))
                    continue
                t = types.get(arg) if arg in types else None  # only check plain tags
                if t and t not in ("ALIAS", ""):  # alias target type is not resolved
                    if op.type == "BOOL" and t != "BOOL":
                        issues.append(Issue("error", n, f"{where}: {arg} is {t}, needs BOOL"))
                    elif op.type in ("TIMER", "COUNTER") and t != op.type:
                        issues.append(Issue("error", n, f"{where}: {arg} is {t}, needs {op.type}"))
                    elif op.type == "COMPARABLE" and t not in NUMERIC_TYPES and t.upper() not in strings:
                        level = "error" if t in ("BOOL", "TIMER", "COUNTER") else "warning"
                        issues.append(Issue(level, n, f"{where}: {arg} is {t}, expected a number or string"))
                    elif op.type == "NUMERIC" and t not in NUMERIC_TYPES:
                        # BOOL/TIMER/COUNTER in a numeric slot is wrong; strings and UDTs are
                        # accepted by some instructions on some firmware, so only warn
                        level = "error" if t in ("BOOL", "TIMER", "COUNTER") else "warning"
                        issues.append(Issue(level, n, f"{where}: {arg} is {t}, expected a number"))
            name = ins.name.upper()
            if name == "ONS" and ins.args:
                bit = ins.args[0]
                if bit in ons_bits:
                    issues.append(Issue("error", n, f"ONS storage bit {bit} already used in rung {ons_bits[bit]}"))
                ons_bits[bit] = n
            if name == "OTE" and ins.args:
                ote_targets[ins.args[0]].append(n)
            if name in ("TON", "TOF", "RTO") and ins.args:
                timer_users[ins.args[0]].append(n)

    # one message per rung is enough when the same problem repeats inside it
    seen, unique = set(), []
    for i in issues:
        if (i.level, i.rung, i.message) not in seen:
            seen.add((i.level, i.rung, i.message))
            unique.append(i)
    issues[:] = unique

    for tag, where in ote_targets.items():
        if len(where) > 1:
            issues.append(Issue(
                "warning", where[-1],
                f"{tag} driven by OTE in rungs {where}; the last one wins every scan (duplicate destructive coil)",
            ))
    for tag, where in timer_users.items():
        if len(where) > 1:
            issues.append(Issue("error", where[-1], f"timer {tag} driven by more than one timer instruction (rungs {where})"))
    return issues


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.level == "error"]
