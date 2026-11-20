"""Import checks on rungs, independent of where they came from (model, compiler, project):
syntax, operand count and types, tags that exist, instruction names for the target version.

Errors mean "Studio 5000 will not accept this". Warnings mean "a human should look".
Programming-standard rules (duplicate coils, reused timers, unguarded division ...) are
the lint rules in lint/, reported with their CRT/ERR/WAR/INF codes.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.catalog import Catalog, default_catalog, major_version
from core.rung import Branch, Rung, Series, base_tag, is_literal, is_placeholder, walk

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


class _NoCase(dict):
    """Tag names in Logix ignore case: start_pb is Start_PB."""

    def __init__(self, d: dict):
        super().__init__({k.upper(): v for k, v in d.items()})

    def __contains__(self, k) -> bool:
        return isinstance(k, str) and super().__contains__(k.upper())

    def get(self, k, default=None):
        return super().get(k.upper(), default) if isinstance(k, str) else default


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
    ctx = _Ctx(cat, major_version(revision), _NoCase({k: v.upper() for k, v in (tag_types or {}).items()}),
               tag_types is not None, {s.upper() for s in (string_types or set())} | {"STRING"})
    issues: list[Issue] = []
    for n, r in enumerate(rungs):
        if not _last_is_output(r.body, cat):
            issues.append(Issue("error", n, "rung (or a branch leg at its end) does not end in an output instruction"))
        for ins in walk(r.body):
            issues += [Issue(level, n, msg) for level, msg in _instruction(ins, ctx)]
    # one message per rung is enough when the same problem repeats inside it
    return list(dict.fromkeys(issues))


@dataclass(frozen=True)
class _Ctx:
    cat: Catalog
    major: int | None
    types: dict[str, str]  # tag -> DATATYPE (upper case)
    check_tags: bool  # report unknown tags (only when the caller gave the project's tags)
    strings: set[str]


def _instruction(ins, ctx: _Ctx):
    """(level, message) for one instruction: known, available in this version, operands."""
    spec = ctx.cat.get(ins.name)
    if spec is None:
        inst = ctx.types.get(base_tag(ins.args[0]) or "") if ins.args else None
        if inst and inst == ins.name.upper():
            # the instance tag's type is the instruction name: an Add-On Instruction whose
            # definition is not in this export (or is source-protected)
            yield "warning", (f"{ins.name} is an Add-On Instruction whose definition is not in this export; "
                              "its operands cannot be checked")
        else:
            yield "error", f"unknown instruction {ins.name}"
        return
    if not spec.available_in(ctx.major):
        if spec.min_version and ctx.major < spec.min_version:
            old = next((i.name for i in ctx.cat.instructions.values() if i.renamed_to == spec.name), None)
            yield "error", f"{ins.name} needs v{spec.min_version}+, target is v{ctx.major}" + (f"; use {old}" if old else "")
        else:
            yield "warning", f"{ins.name} was renamed {spec.renamed_to} in v{spec.max_version + 1}; target is v{ctx.major}"
    if not spec.arity_ok(len(ins.args)):
        want = f"at least {len(spec.operands)}" if spec.variadic else str(len(spec.operands))
        yield "error", f"{ins.name} takes {want} operands, got {len(ins.args)}"
        return
    for op, arg in zip(spec.operands, ins.args):
        found = _operand(f"{ins.name} operand {op.name}", op, arg, ctx)
        if found:
            yield found


def _operand(where: str, op, arg: str, ctx: _Ctx) -> tuple[str, str] | None:
    if op.optional and (arg == "" or is_placeholder(arg)):
        return None
    if arg == "":
        return "error", f"{where} is empty"
    if is_placeholder(arg):
        return None if op.role == "display" else ("error", f"{where} is '?'")
    if op.role == "display":
        if op.member == "PRE" and is_literal(arg) and not 0 <= float(arg) <= 2_147_483_647:
            return "error", f"{where} {arg} is outside 0 to 2147483647 (.PRE is a DINT)"
        return None
    if op.role in ("write", "struct") and is_literal(arg):
        return "error", f"{where} writes to a literal {arg}"
    if op.type == "BOOL" and is_literal(arg):
        return "warning", f"{where} is a constant {arg}"
    if is_literal(arg) or op.type in ("EXPR", "ROUTINE", "NAME"):
        return None
    b = base_tag(arg)
    # "Local:3:I", "S:FS": module-defined I/O and system tags are not <Tag> elements
    if ctx.check_tags and b and ":" not in b and b not in ctx.types:
        return "error", f"{where}: tag {b} does not exist"
    t = ctx.types.get(arg)  # only plain tags are type-checked
    if not t or t == "ALIAS":  # alias target type is not resolved
        return None
    # BOOL/TIMER/COUNTER in a value slot is wrong; strings and UDTs are accepted by some
    # instructions on some firmware, so they only warn
    level = "error" if t in ("BOOL", "TIMER", "COUNTER") else "warning"
    if op.type == "BOOL" and t != "BOOL":
        return "error", f"{where}: {arg} is {t}, needs BOOL"
    if op.type in ("TIMER", "COUNTER") and t != op.type:
        return "error", f"{where}: {arg} is {t}, needs {op.type}"
    if op.type == "COMPARABLE" and t not in NUMERIC_TYPES and t not in ctx.strings:
        return level, f"{where}: {arg} is {t}, expected a number or string"
    if op.type == "NUMERIC" and t not in NUMERIC_TYPES:
        return level, f"{where}: {arg} is {t}, expected a number"
    return None


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.level == "error"]


@dataclass(frozen=True)
class ProjectIssue:
    where: str  # "Program / Routine / Rung 7"
    level: str
    message: str


def validate_project(project) -> list[ProjectIssue]:
    """Import checks for every ladder rung of an attached project (l5x.reader.Project).
    Rung numbers are the project's own, also after a rung that failed to parse."""
    cat = project.catalog()
    out: list[ProjectIssue] = []
    for rt in project.routines:
        good, numbers = [], []
        for x in rt.rungs:
            where = f"{rt.program} / {rt.name} / Rung {x.number}"
            if x.rung is None:
                out.append(ProjectIssue(where, "error", f"does not parse: {x.parse_error}"))
            else:
                good.append(x.rung)
                numbers.append(x.number)
        for i in validate(good, project.tag_types(rt.program), catalog=cat, revision=project.software_revision,
                          string_types=project.string_types):
            out.append(ProjectIssue(f"{rt.program} / {rt.name} / Rung {numbers[i.rung]}", i.level, i.message))
    return out
