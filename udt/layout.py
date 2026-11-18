"""UDT memory layout: byte size as Studio 5000 lays it out, and the member order that
wastes no padding. Size rules (verified against Studio 5000 by L5X UDT Optimizer):

- consecutive BOOL members (BIT in the export) share SINT host bytes; the block starts 4-byte aligned
- BOOL[n] is stored as DINTs: ceil(n/32) * 4 bytes, 4-byte aligned
- other members are aligned to their type's alignment; nested UDTs and AOIs to min(size, 4)
- the total is padded to the largest alignment used (at least 4)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SIZE = {"BOOL": 1, "SINT": 1, "INT": 2, "DINT": 4, "LINT": 8, "REAL": 4, "LREAL": 8, "STRING": 88,
        "TIMER": 12, "COUNTER": 12, "CONTROL": 12, "MESSAGE": 50}
ALIGN = {"BOOL": 1, "SINT": 1, "INT": 2, "DINT": 4, "LINT": 8, "REAL": 4, "LREAL": 8, "STRING": 4,
         "TIMER": 4, "COUNTER": 4, "CONTROL": 4, "MESSAGE": 2}
_SCALAR_GROUP = {"BOOL": 0, "SINT": 1, "INT": 2, "DINT": 3, "REAL": 5, "LREAL": 6, "LINT": 7, "STRING": 8,
                 "TIMER": 9, "COUNTER": 9, "CONTROL": 9, "MESSAGE": 9}
_ARRAY_GROUP = {"BOOL": 0, "SINT": 1, "INT": 2, "DINT": 3, "REAL": 4, "LREAL": 5, "LINT": 6, "STRING": 7,
                "TIMER": 8, "COUNTER": 8, "CONTROL": 8, "MESSAGE": 8}
_SORT_ALIGN = {"BOOL": 1, "SINT": 1, "INT": 2, "MESSAGE": 2, "LREAL": 8, "LINT": 8}
HOST_PREFIX = "ZZZZZZZZZZ"  # hidden SINT hosts of BOOL members


@dataclass(frozen=True)
class M:
    name: str
    type: str  # BIT for a packed BOOL; native type name; or a UDT/AOI name
    dim: int = 0


def natural_key(name: str) -> list:
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", name.lower())]


def _align(offset: int, a: int) -> int:
    return (offset + a - 1) // a * a


def size_of(members: list[M], sizes: dict[str, int]) -> int:
    """Byte size of a member list in this order. `sizes` holds known UDT/AOI sizes."""
    off, max_align, i = 0, 4, 0
    while i < len(members):
        m = members[i]
        t = m.type.upper()
        if t == "BIT":
            bits = 0
            while i < len(members) and members[i].type.upper() == "BIT":
                bits, i = bits + 1, i + 1
            off = _align(off, 4) + (bits + 7) // 8
            continue
        if t == "BOOL" and m.dim > 0:
            sz, al = (m.dim + 31) // 32 * 4, 4
        elif t in SIZE:
            sz, al = SIZE[t] * max(m.dim, 1), ALIGN[t]
        elif m.type in sizes:
            sz, al = sizes[m.type] * max(m.dim, 1), min(sizes[m.type], 4)
        else:
            sz, al = 4 * max(m.dim, 1), 4
        max_align = max(max_align, al)
        off = _align(off, al) + sz
        i += 1
    return _align(off, max_align)


def sort_key(m: M, user_types: set[str]) -> tuple:
    """Order that never steps down in alignment (1, 2, 4, 8 bytes), grouped by type, then by name."""
    t = "BOOL" if m.type.upper() == "BIT" else m.type.upper()
    native = t in SIZE
    al = 4 if (t == "BOOL" and m.dim > 0) else _SORT_ALIGN.get(t, 4)
    if m.dim > 0:
        return (al, 4, _ARRAY_GROUP.get(t, 9 if not native else 10), t, natural_key(m.name))
    group = _SCALAR_GROUP.get(t, 10 if m.type in user_types else 11)
    return (al, group, 0, t, natural_key(m.name))


def dependency_order(types: dict[str, list[M]]) -> list[str]:
    """UDT names, nested types first. Raises ValueError on a cycle."""
    order, state = [], {}

    def visit(n, path):
        if state.get(n) == "done":
            return
        if state.get(n) == "busy":
            raise ValueError("UDT dependency cycle: " + " -> ".join(path + [n]))
        state[n] = "busy"
        for m in types[n]:
            if m.type in types:
                visit(m.type, path + [n])
        state[n] = "done"
        order.append(n)

    for n in types:
        visit(n, [])
    return order


@dataclass
class LayoutResult:
    name: str
    size_now: int
    size_best: int
    order_changes: bool
    unknown_types: list[str]


def analyse(types: dict[str, list[M]], aoi_sizes: dict[str, int]) -> list[LayoutResult]:
    sizes = dict(aoi_sizes)
    order = dependency_order(types)
    for n in order:
        sizes[n] = size_of(types[n], sizes)
    out = []
    user = set(types) | set(aoi_sizes)
    for n in order:
        members = types[n]
        unknown = sorted({m.type for m in members if m.type.upper() not in SIZE and m.type.upper() != "BIT"
                          and m.type not in user})
        known = [m for m in members if m.type not in unknown]
        best = sorted(known, key=lambda m: sort_key(m, user))
        packed = [M(m.name, "BIT", 0) if (m.type.upper() in ("BOOL", "BIT") and m.dim == 0) else m for m in best]
        out.append(LayoutResult(n, sizes[n], size_of(packed, sizes) if known else sizes[n],
                                [m.name for m in members] != [m.name for m in best], unknown))
    return out
