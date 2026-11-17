"""Cross-reference: which rung reads or writes which tag."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ..catalog import Catalog
from ..rung import base_tag, walk
from .reader import Project


@dataclass(frozen=True)
class Ref:
    program: str
    routine: str
    rung: int
    instruction: str
    operand: str
    role: str  # read | write | struct


def cross_reference(project: Project, catalog: Catalog | None = None) -> dict[str, list[Ref]]:
    """Map base tag name -> references. Program-scoped tags are not
    distinguished from controller tags of the same name (rare; flagged in docs)."""
    cat = catalog or project.catalog()
    out: dict[str, list[Ref]] = defaultdict(list)
    for rt in project.routines:
        for r in rt.rungs:
            if r.rung is None:
                continue
            for ins in walk(r.rung.body):
                spec = cat.get(ins.name)
                if spec is None:
                    continue
                for op, arg in zip(spec.operands, ins.args):
                    if op.role == "display" or op.type in ("ROUTINE", "EXPR"):
                        continue
                    b = base_tag(arg)
                    if b:
                        out[b].append(Ref(rt.program, rt.name, r.number, ins.name, arg, op.role))
    return dict(out)
