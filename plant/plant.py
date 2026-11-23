"""A plant: a set of devices stepped together, loaded from YAML, with PLANT: tags for tests."""

from __future__ import annotations

import re

import yaml

from .devices import FAULTS, Device, Motor, PlantError, Valve

_TYPES = {"motor": Motor, "pump": Motor, "fan": Motor, "valve": Valve}
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PREFIX = "PLANT:"


class Plant:
    def __init__(self, devices: list[Device]):
        seen: dict[str, str] = {}
        for d in devices:
            if d.name in seen:
                raise PlantError(f"device {d.name} is defined twice")
            seen[d.name] = d.name
        writers: dict[str, str] = {}
        for d in devices:
            for t in d.feedbacks():
                if t in writers:
                    raise PlantError(f"{t} is written by {writers[t]} and {d.name}: one tag, one device")
                writers[t] = d.name
        self.devices = {d.name: d for d in devices}

    def commands(self) -> list[str]:
        """Tags to read from the PLC before each step."""
        return sorted({t for d in self.devices.values() for t in d.commands()})

    def feedbacks(self) -> list[str]:
        """Tags the plant writes to the PLC after each step."""
        return sorted({t for d in self.devices.values() for t in d.feedbacks()})

    def step(self, dt_ms: float, plc: dict[str, object]) -> dict[str, bool]:
        """Advance every device by dt_ms given the PLC's commands; return the feedback to write."""
        if dt_ms < 0:
            raise PlantError("time cannot run backwards")
        out: dict[str, bool] = {}
        for d in self.devices.values():
            out.update(d.step(dt_ms, {t: bool(plc.get(t)) for t in d.commands()}))
        return out

    def notes(self) -> list[str]:
        return [n for d in self.devices.values() for n in d.notes]

    # ---- PLANT:<device>.<attr> tags, read and written by tests
    def owns(self, tag: str) -> bool:
        return tag.startswith(PREFIX)

    def _split(self, tag: str) -> tuple[Device, str]:
        dev, _, attr = tag[len(PREFIX):].partition(".")
        if dev not in self.devices:
            raise PlantError(f"{tag}: no device {dev} (devices: {', '.join(self.devices) or 'none'})")
        return self.devices[dev], attr

    def read(self, tag: str) -> object:
        d, attr = self._split(tag)
        values = {"fault": d.fault, **d.state()}
        if attr not in values:
            raise PlantError(f"{tag}: {d.name} has {', '.join(values)}")
        return values[attr]

    def write(self, tag: str, value: object) -> None:
        d, attr = self._split(tag)
        if attr != "fault":
            raise PlantError(f"{tag}: only {PREFIX}{d.name}.fault can be set")
        v = "" if value in (None, "", 0, False, "none", "healthy") else str(value)
        if v and v not in FAULTS[d.kind]:
            raise PlantError(f"{tag}: unknown fault {v!r}; a {d.kind} can have {', '.join(FAULTS[d.kind])}")
        d.fault = v


def load_plant(text: str) -> Plant:
    """devices:
      - {name: P101, type: pump, cmd: P101_Cmd, running: P101_Running, start_ms: 1000}
      - {name: XV102, type: valve, open_cmd: XV102_Open, open_ls: XV102_ZSO, closed_ls: XV102_ZSC}
    """
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise PlantError(f"plant file is not valid YAML: {e}") from None
    items = data.get("devices") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise PlantError("plant file needs a 'devices:' list")
    devices = []
    for n, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise PlantError(f"device {n}: expected name, type and tags")
        item = dict(item)
        kind = str(item.pop("type", "")).lower()
        name = str(item.get("name", ""))
        if kind not in _TYPES:
            raise PlantError(f"device {n} ({name or '?'}): type must be one of {', '.join(_TYPES)}")
        if not _NAME.match(name):
            raise PlantError(f"device {n}: name {name!r} must be a plain identifier like P101")
        cls = _TYPES[kind]
        allowed = {f for f in cls.__dataclass_fields__ if not f.startswith("_") and f not in ("notes",)}
        extra = set(item) - allowed
        if extra:
            raise PlantError(f"{name}: unknown {', '.join(sorted(extra))}; a {kind} takes "
                             f"{', '.join(sorted(allowed - {'name', 'fault'}))}")
        d = cls(**item)
        if not d.commands() or not all(d.commands()):
            raise PlantError(f"{name}: a {kind} needs its command tag ({'cmd' if cls is Motor else 'open_cmd'})")
        if d.fault and d.fault not in FAULTS[d.kind]:
            raise PlantError(f"{name}: unknown fault {d.fault!r}")
        devices.append(d)
    return Plant(devices)
