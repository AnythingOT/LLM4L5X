"""Block files: parameters with defaults, rung patterns, tag types, plant entry and scenario patterns.

Patterns use {param} placeholders. Every placeholder must be a declared parameter, every value must
be a tag name or a number, and the result must parse and pass the rung rules: a block that cannot
build clean rungs is refused when it is loaded, not when it is used.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field
from pathlib import Path

import yaml

HERE = Path(__file__).parent / "blocks"
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,39}$")
_NUM = re.compile(r"^-?\d+(\.\d+)?$")
_KEYS = {"name", "version", "description", "params", "rungs", "tags", "plant", "scenarios"}


class LibraryError(ValueError):
    pass


@dataclass
class Instance:
    block: str
    version: str
    values: dict[str, str]
    rungs: list = field(default_factory=list)  # core.rung.Rung, with comments
    tags: list = field(default_factory=list)  # core.compiler.TagDef
    plant: dict = field(default_factory=dict)  # one plant-model device entry ({} = none)
    scenarios: str = ""


@dataclass
class Block:
    name: str
    version: str
    description: str
    params: dict[str, dict]  # name -> {default, description}
    rungs: list[tuple[str, str]]  # (rung pattern, comment pattern)
    tags: dict[str, str]  # tag pattern -> data type
    plant: dict
    scenarios: str
    source: str = ""

    def _fill(self, text: str, values: dict[str, str]) -> str:
        try:
            return string.Formatter().vformat(text, (), values)
        except KeyError as e:
            raise LibraryError(f"{self.name}: pattern uses {{{e.args[0]}}}, which is not a parameter") from None

    def instantiate(self, given: dict) -> Instance:
        from core.compiler import TagDef
        from core.rung import RungSyntaxError, parse_rung
        unknown = set(given) - set(self.params)
        if unknown:
            raise LibraryError(f"{self.name}: no parameter {', '.join(sorted(unknown))}; it takes "
                               f"{', '.join(self.params)}")
        values: dict[str, str] = {}
        for p, spec in self.params.items():  # in file order: a default may use earlier parameters
            v = given.get(p, spec.get("default"))
            if v is None:
                raise LibraryError(f"{self.name}: {p} is required ({spec.get('description', '')})".rstrip(" ()"))
            v = self._fill(str(v), values) if isinstance(v, str) else str(v)
            if not (_NAME.match(v) or _NUM.match(v)):
                raise LibraryError(f"{self.name}: {p} = {v!r} is not a tag name or a number")
            values[p] = v
        inst = Instance(self.name, self.version, values)
        for pat, comment in self.rungs:
            text = self._fill(pat, values)
            try:
                inst.rungs.append(parse_rung(text, self._fill(comment, values) or None))
            except RungSyntaxError as e:
                raise LibraryError(f"{self.name}: rung {text!r} does not parse: {e}") from None
        for pat, dt in self.tags.items():
            inst.tags.append(TagDef(self._fill(pat, values), dt))
        if self.plant:
            inst.plant = {}
            for k, v in self.plant.items():
                v = self._fill(v, values) if isinstance(v, str) else v
                inst.plant[k] = float(v) if isinstance(v, str) and _NUM.match(v) else v  # "1000" ms -> 1000.0
        inst.scenarios = self._fill(self.scenarios, values)
        return inst


def load_block(text: str, source: str = "") -> Block:
    try:
        d = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise LibraryError(f"{source or 'block'}: not valid YAML: {e}") from None
    if not isinstance(d, dict) or not d.get("name") or not d.get("rungs"):
        raise LibraryError(f"{source or 'block'}: a block needs at least name and rungs")
    extra = set(d) - _KEYS
    if extra:
        raise LibraryError(f"{d['name']}: unknown {', '.join(sorted(extra))}")
    params = {str(k): (v if isinstance(v, dict) else {"default": v}) for k, v in (d.get("params") or {}).items()}
    if "name" not in params:
        raise LibraryError(f"{d['name']}: every block takes a name parameter (the instance, e.g. P101)")
    rungs = [(r["rung"], r.get("comment", "")) if isinstance(r, dict) else (str(r), "") for r in d["rungs"]]
    b = Block(str(d["name"]), str(d.get("version", "1")), str(d.get("description", "")).strip(), params, rungs,
              {str(k): str(v) for k, v in (d.get("tags") or {}).items()}, dict(d.get("plant") or {}),
              str(d.get("scenarios") or ""), source)
    _self_test(b)
    return b


def _self_test(b: Block) -> None:
    """Build one instance from the defaults (required parameters get placeholder names) and check it:
    a broken block fails when the library loads."""
    import lint
    sample = {p: (s.get("default") if s.get("default") is not None else f"X_{p}") for p, s in b.params.items()}
    inst = b.instantiate(sample)
    types = {t.name: t.datatype for t in inst.tags}
    bad = [f for f in lint.check_rungs(inst.rungs, types) if f.severity in ("critical", "error")]
    if bad:
        raise LibraryError(f"{b.name}: its rungs fail rule {bad[0].code}: {bad[0].message}")
    if inst.plant:
        from devices import load_plant
        load_plant(yaml.safe_dump({"devices": [inst.plant]}))
    if inst.scenarios.strip():
        from testcases import parse_scenarios
        parse_scenarios(inst.scenarios)


def load_library(*folders: str | Path) -> dict[str, Block]:
    """Starter blocks, then each folder in turn: a company block of the same name replaces a starter."""
    out: dict[str, Block] = {}
    for folder in (HERE, *map(Path, folders)):
        for f in sorted(Path(folder).glob("*.yaml")):
            b = load_block(f.read_text(encoding="utf-8"), str(f))
            out[b.name] = b
    return out
