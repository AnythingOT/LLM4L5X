"""Everything a rule needs, built once from a Project: rung list with locations,
tag lookup by scope, operand types, operand roles from the instruction catalog."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.catalog import Catalog
from core.rung import Instr, Rung, base_tag, is_literal, walk
from l5x.reader import Project, RoutineInfo, TagInfo

GUARDS = {"LIM", "LIMIT", "LES", "LT", "LEQ", "LE", "GRT", "GT", "GEQ", "GE", "EQU", "EQ", "NEQ", "NE", "MEQ", "CMP"}
TIMERS = {"TON", "TOF", "RTO", "TONR", "TOFR", "RTOR"}
COUNTERS = {"CTU", "CTD", "CTUD"}
ONE_SHOTS = {"ONS", "OSR", "OSF"}
INT_TYPES = {"SINT", "INT", "DINT", "LINT", "USINT", "UINT", "UDINT", "ULINT"}
REAL_TYPES = {"REAL", "LREAL"}
_BUILTIN_MEMBERS = {
    "TIMER": {"PRE": "DINT", "ACC": "DINT"},
    "COUNTER": {"PRE": "DINT", "ACC": "DINT"},
    "CONTROL": {"LEN": "DINT", "POS": "DINT"},
}
_IDENT = re.compile(r"[A-Za-z_][\w:]*")


@dataclass
class RungRef:
    location: str  # "Program / Routine / Rung 3" or "AOI:Name / Logic / Rung 3"
    owner: str  # program name, or "AOI:<name>"
    routine: str
    index: int  # position in its routine
    number: int
    rung: Rung
    comment: str | None


@dataclass
class Finding:
    code: str
    message: str
    location: str
    detail: str = ""

    @property
    def severity(self) -> str:
        from lint.rules import BY_CODE
        return BY_CODE[self.code].severity

    def to_dict(self) -> dict:
        from lint.rules import BY_CODE
        r = BY_CODE[self.code]
        return {"code": self.code, "title": r.title, "severity": r.severity,
                "message": self.message, "location": self.location, "detail": self.detail}


@dataclass
class Context:
    project: Project
    catalog: Catalog
    rungs: list[RungRef] = field(default_factory=list)
    ctrl_tags: dict[str, TagInfo] = field(default_factory=dict)
    prog_tags: dict[str, dict[str, TagInfo]] = field(default_factory=dict)
    aoi_scope: dict[str, dict[str, str]] = field(default_factory=dict)  # AOI -> {param/local: type}
    usage_text: str = ""  # identifiers of ST/FBD/SFC routines: usage, not analysed
    unparsed: int = 0  # rungs whose text did not parse
    not_verified: dict[str, str] = field(default_factory=dict)  # code -> why the export cannot answer it

    @classmethod
    def build(cls, project: Project, catalog: Catalog | None = None) -> "Context":
        ctx = cls(project, catalog or project.catalog())
        for t in project.tags.values():
            if t.scope == "controller":
                ctx.ctrl_tags[t.name] = t
            else:
                ctx.prog_tags.setdefault(t.scope, {})[t.name] = t
        for a in project.aois.values():
            scope = {p.name: p.datatype for p in a.params}
            scope.update({t.name: t.datatype for t in a.local_tags})
            ctx.aoi_scope[f"AOI:{a.name}"] = scope
        all_routines: list[RoutineInfo] = list(project.routines)
        for a in project.aois.values():
            all_routines += a.routines
        texts = []
        for rt in all_routines:
            texts.append(rt.usage_text)
            for i, r in enumerate(rt.rungs):
                if r.rung is None:
                    ctx.unparsed += 1
                    continue
                ctx.rungs.append(RungRef(f"{rt.program} / {rt.name} / Rung {r.number}", rt.program, rt.name,
                                         i, r.number, r.rung, r.comment))
        ctx.usage_text = "\n".join(t for t in texts if t)
        return ctx

    # ------------------------------------------------------------- tags and types

    def tag(self, base: str, owner: str) -> TagInfo | None:
        if owner in self.prog_tags and base in self.prog_tags[owner]:
            return self.prog_tags[owner][base]
        return self.ctrl_tags.get(base)

    def scope_of(self, base: str, owner: str) -> str:
        if owner.startswith("AOI:") and base in self.aoi_scope.get(owner, {}):
            return owner
        if base in self.prog_tags.get(owner, {}):
            return f"prog:{owner}"
        return "ctrl"

    def base_type(self, base: str, owner: str) -> str | None:
        if owner.startswith("AOI:") and base in self.aoi_scope.get(owner, {}):
            return self.aoi_scope[owner][base]
        t = self.tag(base, owner)
        return t.datatype if t else None

    def resolve_type(self, operand: str, owner: str) -> str | None:
        """Data type of an operand such as Tag, Tag.Member.3 or Arr[i].PRE; None if unknown."""
        op = operand.strip()
        if is_literal(op):
            return "REAL" if re.search(r"[.eE]", op) else "DINT"
        parts = re.sub(r"\[[^\]]*\]", "", op).split(".")
        if not re.fullmatch(r"[A-Za-z_]\w*", parts[0]):
            return None
        t = self.base_type(parts[0], owner)
        if not t:
            return None
        t = t.upper()
        for part in parts[1:]:
            if part.isdigit():
                return "BOOL"
            udt = next((d for n, d in self.project.datatypes.items() if n.upper() == t), None)
            if udt:
                m = next((m for m in udt.members if m.name.upper() == part.upper()), None)
                if m is None:
                    return None
                t = "BOOL" if m.datatype.upper() == "BIT" else m.datatype.upper()
            elif t in _BUILTIN_MEMBERS:
                t = _BUILTIN_MEMBERS[t].get(part.upper(), "BOOL")
            else:
                return None
        return t

    # ------------------------------------------------------------- operands by role

    def roles(self, ins: Instr) -> list[tuple[str, str]]:
        """(argument, role) pairs from the catalog; [] for an unknown instruction."""
        spec = self.catalog.get(ins.name)
        if spec is None:
            return []
        ops = list(spec.operands)
        if spec.variadic and ops and len(ins.args) > len(ops):
            ops += [ops[-1]] * (len(ins.args) - len(ops))
        return [(a, op.role if op.type not in ("EXPR", "ROUTINE", "NAME") else "other")
                for op, a in zip(ops, ins.args)]

    def writes(self, ins: Instr) -> list[str]:
        return [a for a, role in self.roles(ins) if role == "write"]

    def reads(self, ins: Instr) -> list[str]:
        return [a for a, role in self.roles(ins) if role == "read"]

    # ------------------------------------------------------------- usage

    def corpus(self) -> str:
        """All rung text plus ST/FBD identifiers, for 'is it used anywhere' questions."""
        from core.rung import format_rung
        return "\n".join(format_rung(r.rung) for r in self.rungs) + "\n" + self.usage_text

    def used_bases(self, owner: str | None = None) -> set[str]:
        """Base tag names referenced by ladder (optionally only one owner's rungs) and ST/FBD."""
        out = set()
        for r in self.rungs:
            if owner is not None and r.owner != owner:
                continue
            for ins in walk(r.rung.body):
                for a, role in self.roles(ins) or [(x, "read") for x in ins.args]:
                    if role == "display":
                        continue
                    b = base_tag(a)
                    if b:
                        out.add(b)
                    for inner in re.findall(r"\[([^\]]*)\]", a):
                        out.update(_IDENT.findall(inner))
                    if role == "other":
                        out.update(_IDENT.findall(a))
        out.update(_IDENT.findall(self.usage_text))
        return out


def guarded(before: tuple[Instr, ...], tag: str) -> bool:
    """True if a compare instruction on `tag` runs in series before, on the same path."""
    pat = re.compile(r"(?<![\w.:])" + re.escape(tag) + r"(?![\w])")
    return any(i.name.upper() in GUARDS and any(pat.search(a) for a in i.args) for i in before)


def concrete(operand: str) -> bool:
    """No variable index: usable as an identity (Arr[3] yes, Arr[i] no)."""
    return all(re.fullmatch(r"\s*\d+(\s*,\s*\d+)*\s*", x) for x in re.findall(r"\[([^\]]*)\]", operand))
