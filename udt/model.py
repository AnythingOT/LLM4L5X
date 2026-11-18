"""A UDT as a list of members, the checks Studio 5000 applies to one, and the
small text form the model writes:

    UDT Motor_Status "Motor status";
    Running BOOL "Motor is running";
    Speed REAL "Speed, rpm";
    Alarms BOOL[32] "Alarm bits";
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from udt.layout import SIZE

# member types a new UDT may use (MESSAGE and motion types cannot be UDT members)
MEMBER_TYPES = {"BOOL", "SINT", "INT", "DINT", "LINT", "REAL", "LREAL", "STRING", "TIMER", "COUNTER", "CONTROL"}
NATIVE = set(SIZE) | {"BIT", "USINT", "UINT", "UDINT", "ULINT"}
NAME_MAX = 40


@dataclass
class UdtMember:
    name: str
    datatype: str  # BOOL, DINT, ..., or a UDT/AOI name
    dim: int = 0  # 0 = not an array
    description: str = ""


@dataclass
class UdtDef:
    name: str
    description: str = ""
    members: list[UdtMember] = field(default_factory=list)

    def member_types(self) -> set[str]:
        return {m.datatype for m in self.members}


class UdtError(ValueError):
    pass


def name_problem(name: str) -> str | None:
    """Why a Logix name is invalid, or None. Rules as Studio 5000 applies them to tags and members."""
    if not name:
        return "is empty"
    if len(name) > NAME_MAX:
        return f"is {len(name)} characters; the limit is {NAME_MAX}"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return "may use only letters, digits and _, and must not start with a digit"
    if "__" in name:
        return "must not contain two underscores in a row"
    if name.endswith("_"):
        return "must not end with _"
    return None


def check(udts: list[UdtDef], known: dict[str, str] | None = None) -> list[str]:
    """Problems that would stop the import. `known`: data types already in the project
    ({name: "UDT" | "AOI" | "STRING"}). Returns readable messages; empty means fine."""
    known = {k.upper(): v for k, v in (known or {}).items()}
    errors = []
    batch = {u.name.upper(): u for u in udts}
    if len(batch) != len(udts):
        errors.append("two UDTs have the same name")
    for u in udts:
        why = name_problem(u.name)
        if why:
            errors.append(f"UDT name '{u.name}' {why}")
        if u.name.upper() in NATIVE:
            errors.append(f"UDT name '{u.name}' is a built-in data type")
        if not u.members:
            errors.append(f"UDT '{u.name}' has no members")
        seen = set()
        for m in u.members:
            where = f"{u.name}.{m.name}"
            why = name_problem(m.name)
            if why:
                errors.append(f"member '{where}' {why}")
            if m.name.upper() in seen:
                errors.append(f"member '{where}' appears twice (names are not case sensitive)")
            seen.add(m.name.upper())
            t = m.datatype.upper()
            if t in MEMBER_TYPES:
                pass
            elif t == "MESSAGE":
                errors.append(f"member '{where}': MESSAGE cannot be a UDT member")
            elif m.datatype.upper() in batch or t in known:
                if m.datatype.upper() == u.name.upper():
                    errors.append(f"member '{where}' uses its own UDT")
            else:
                errors.append(f"member '{where}': unknown data type {m.datatype}")
            if m.dim < 0:
                errors.append(f"member '{where}': array size must be positive")
            if t == "BOOL" and m.dim and m.dim % 32:
                errors.append(f"member '{where}': BOOL arrays must be a multiple of 32 (got {m.dim})")
    if not errors:
        try:
            dependency_order(udts)
        except UdtError as e:
            errors.append(str(e))
    return errors


def dependency_order(udts: list[UdtDef]) -> list[UdtDef]:
    """Nested UDTs first. Raises UdtError on a cycle."""
    by = {u.name.upper(): u for u in udts}
    order, state = [], {}

    def visit(u, path):
        k = u.name.upper()
        if state.get(k) == "done":
            return
        if state.get(k) == "busy":
            raise UdtError("UDTs nest each other in a loop: " + " -> ".join(path + [u.name]))
        state[k] = "busy"
        for m in u.members:
            if m.datatype.upper() in by:
                visit(by[m.datatype.upper()], path + [u.name])
        state[k] = "done"
        order.append(u)

    for u in udts:
        visit(u, [])
    return order


# ---------------------------------------------------------------- text form

_TYPE = r"([A-Za-z_]\w*)(?:\s*\[\s*(\d+)\s*\])?"
_UDT_LINE = re.compile(r'^\s*UDT\s+([A-Za-z_]\w*)\s*(?:"([^"]*)")?\s*;?\s*$', re.I)
_MEMBER_LINE = re.compile(r'^\s*([A-Za-z_]\w*)\s*:?\s+' + _TYPE + r'\s*(?:"([^"]*)")?\s*;?\s*$')


def parse_spec(text: str) -> list[UdtDef]:
    """The text form above. Several UDTs may follow each other; '//' starts a comment."""
    udts: list[UdtDef] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        m = _UDT_LINE.match(line)
        if m:
            udts.append(UdtDef(m.group(1), (m.group(2) or "").strip()))
            continue
        m = _MEMBER_LINE.match(line)
        if m:
            if not udts:
                raise UdtError(f"line {n}: a member before the first 'UDT Name' line")
            name, dtype, dim, desc = m.groups()
            dt = dtype.upper() if dtype.upper() in NATIVE else dtype
            udts[-1].members.append(UdtMember(name, dt, int(dim) if dim else 0, (desc or "").strip()))
            continue
        raise UdtError(f"line {n}: expected 'UDT Name \"description\";' or 'Member TYPE[n] \"description\";', "
                       f"got: {raw.strip()[:60]}")
    if not udts:
        raise UdtError("no 'UDT Name' line")
    return udts


def format_spec(udts: list[UdtDef]) -> str:
    out = []
    for u in udts:
        out.append(f'UDT {u.name}' + (f' "{u.description}"' if u.description else "") + ";")
        for m in u.members:
            t = f"{m.datatype}[{m.dim}]" if m.dim else m.datatype
            out.append(f"{m.name} {t}" + (f' "{m.description}"' if m.description else "") + ";")
    return "\n".join(out)
