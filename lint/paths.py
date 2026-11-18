"""Path questions on the rung AST (core.rung): what is guaranteed to run before an
instruction on its power path, which sequences and branches a rung has."""

from __future__ import annotations

import re
from typing import Iterator

from core.rung import Branch, Instr, Series


def walk_series(node: Series, before: tuple[Instr, ...] = ()) -> Iterator[tuple[Instr, tuple[Instr, ...]]]:
    """(instruction, before) for every instruction. `before` holds the instructions that
    are in series ahead of it on its own path: earlier items of its sequence and of every
    enclosing sequence. Instructions in a sibling leg, or after a branch, are not included."""
    local = list(before)
    for item in node.items:
        if isinstance(item, Instr):
            yield item, tuple(local)
            local.append(item)
        else:
            for leg in item.legs:
                yield from walk_series(leg, tuple(local))
            # after a branch only the common prefix is guaranteed: `local` stays as it was


def sequences(node: Series) -> Iterator[Series]:
    """The rung itself and every branch leg, recursively."""
    yield node
    for item in node.items:
        if isinstance(item, Branch):
            for leg in item.legs:
                yield from sequences(leg)


def branches(node: Series) -> Iterator[Branch]:
    for item in node.items:
        if isinstance(item, Branch):
            yield item
            for leg in item.legs:
                yield from branches(leg)


def _norm(arg: str) -> str:
    return re.sub(r"\s+", "", arg)


def key(item) -> tuple:
    """Comparable identity of an instruction or branch (case and spacing ignored)."""
    if isinstance(item, Instr):
        return ("I", item.name.upper(), tuple(_norm(a) for a in item.args))
    if isinstance(item, Branch):
        return ("B", tuple(tuple(key(i) for i in leg.items) for leg in item.legs))
    return ("S", tuple(key(i) for i in item.items))


def fmt(item) -> str:
    if isinstance(item, Instr):
        return f"{item.name}({','.join(item.args)})"
    return "[" + ",".join("".join(fmt(i) for i in leg.items) for leg in item.legs) + "]"
