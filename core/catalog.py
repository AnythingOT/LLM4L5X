"""Instruction catalog: loads instructions.yaml and lets L5X content extend it (AOIs)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROLES = {"read", "write", "struct", "display"}
TYPES = {"BOOL", "NUMERIC", "TIMER", "COUNTER", "ANY", "ROUTINE", "EXPR", "NAME"}
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
    min_version: int | None = None  # first Logix Designer major version with this mnemonic
    max_version: int | None = None  # last major version with this mnemonic
    renamed_to: str | None = None  # mnemonic used from the next version on

    def available_in(self, major: int | None) -> bool:
        if major is None:
            return True
        return (self.min_version is None or major >= self.min_version) and (
            self.max_version is None or major <= self.max_version
        )

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
        min_version=raw.get("min_version"),
        max_version=raw.get("max_version"),
        renamed_to=raw.get("renamed_to"),
    )


def major_version(revision: str | None) -> int | None:
    """'36.00' / 'v35.01' / '32' -> 36 / 35 / 32; None if unknown."""
    m = re.match(r"\s*v?(\d+)", revision or "")
    return int(m.group(1)) if m else None


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
