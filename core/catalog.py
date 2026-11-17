"""Instruction catalog: loads instructions.yaml and lets L5X content extend it (AOIs)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROLES = {"read", "write", "struct", "display"}
TYPES = {"BOOL", "NUMERIC", "TIMER", "COUNTER", "ANY", "ROUTINE", "EXPR"}
KINDS = {"input", "output"}


@dataclass(frozen=True)
class Operand:
    name: str
    type: str
    role: str
    member: str | None = None


@dataclass(frozen=True)
class Instruction:
    name: str
    kind: str
    operands: tuple[Operand, ...]
    description: str = ""
    variadic: bool = False
    source: str = "builtin"  # builtin | aoi

    @property
    def is_input(self) -> bool:
        return self.kind == "input"

    @property
    def is_output(self) -> bool:
        return self.kind == "output"

    def arity_ok(self, n: int) -> bool:
        return n >= len(self.operands) if self.variadic else n == len(self.operands)


@dataclass
class Catalog:
    instructions: dict[str, Instruction] = field(default_factory=dict)

    def get(self, name: str) -> Instruction | None:
        return self.instructions.get(name.upper())

    def __contains__(self, name: str) -> bool:
        return name.upper() in self.instructions

    def names(self) -> list[str]:
        return sorted(self.instructions)

    def add(self, instr: Instruction) -> None:
        self.instructions[instr.name.upper()] = instr

    def copy(self) -> "Catalog":
        return Catalog(dict(self.instructions))


def _validate_entry(name: str, raw: dict) -> Instruction:
    kind = raw.get("kind")
    if kind not in KINDS:
        raise ValueError(f"{name}: kind must be one of {sorted(KINDS)}, got {kind!r}")
    ops = []
    for o in raw.get("operands") or []:
        if o["role"] not in ROLES:
            raise ValueError(f"{name}.{o['name']}: bad role {o['role']!r}")
        if o["type"] not in TYPES:
            raise ValueError(f"{name}.{o['name']}: bad type {o['type']!r}")
        ops.append(Operand(o["name"], o["type"], o["role"], o.get("member")))
    return Instruction(
        name=name.upper(),
        kind=kind,
        operands=tuple(ops),
        description=raw.get("description", ""),
        variadic=bool(raw.get("variadic", False)),
    )


def load_catalog(text: str | None = None) -> Catalog:
    """Load the builtin catalog, or a catalog from YAML text."""
    if text is None:
        text = (Path(__file__).parent / "instructions.yaml").read_text("utf-8")
    raw = yaml.safe_load(text) or {}
    cat = Catalog()
    for name, entry in raw.items():
        cat.add(_validate_entry(name, entry))
    return cat


_DEFAULT: Catalog | None = None


def default_catalog() -> Catalog:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = load_catalog()
    return _DEFAULT
