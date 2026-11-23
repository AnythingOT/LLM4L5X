"""Where a scenario runs. A Backend reads and writes tags and lets time pass.

SimBackend runs rungs in our scan simulator with a plant model on the same clock: each scan the plant
reads the PLC's commands, steps by scan_ms and writes its feedback, then the logic scans. One clock
means no emulator-to-simulator timing drift. A pylogix backend (emulator or controller) implements
the same three methods; the plant then steps in the poll loop instead.
"""

from __future__ import annotations

from typing import Protocol

from core.rung import Rung, base_tag, is_literal, walk
from core.simulator import Simulator

_PRESET_ARG = {"TON": 1, "TOF": 1, "RTO": 1, "CTU": 1, "CTD": 1}


class Backend(Protocol):
    now_ms: float

    def has(self, tag: str) -> bool: ...
    def read(self, tag: str) -> object: ...
    def write(self, tag: str, value: object) -> None: ...
    def advance(self, ms: float) -> None: ...


def presets_from_rungs(rungs: list[Rung]) -> dict[str, float]:
    """TON(T,5000,0) -> {"T.PRE": 5000}: hand-written rungs carry their presets as literals."""
    out = {}
    for r in rungs:
        for i in walk(r.body):
            k = _PRESET_ARG.get(i.name)
            if k is not None and len(i.args) > k:
                try:
                    out[f"{i.args[0]}.PRE"] = float(i.args[k]) if "." in i.args[k] else int(i.args[k])
                except ValueError:
                    pass
    return out


class SimBackend:
    def __init__(self, rungs: list[Rung], state: dict | None = None, plant=None, scan_ms: float = 10.0):
        if scan_ms <= 0:
            raise ValueError("scan_ms must be positive")
        self.sim = Simulator(rungs, {**presets_from_rungs(rungs), **(state or {})})
        self.plant = plant
        self.scan_ms = scan_ms
        self.now_ms = 0.0
        self.scans = 0
        self._names = {base_tag(a) for r in rungs for i in walk(r.body) for a in i.args if not is_literal(a)}
        self._names |= {base_tag(k) for k in (state or {})}
        if plant is not None:
            self._names |= set(plant.commands()) | set(plant.feedbacks())
        self._step(0)  # first scan: outputs settle from the initial state

    def _step(self, dt: float) -> None:
        if self.plant is not None:
            cmds = {t: self.sim.get(t) for t in self.plant.commands()}
            for tag, v in self.plant.step(dt, cmds).items():
                self.sim.put(tag, int(v))
        self.sim.scan(int(dt))
        self.scans += 1

    def has(self, tag: str) -> bool:
        """A tag the logic, the initial state or the plant knows. The simulator reads an unknown tag as 0,
        so without this check a typo in EXPECT Pump_Cmdd == 0 would pass."""
        if self.plant is not None and self.plant.owns(tag):
            dev = tag[len("PLANT:"):].partition(".")[0]
            return dev in self.plant.devices
        return base_tag(tag) in self._names

    def read(self, tag: str) -> object:
        if self.plant is not None and self.plant.owns(tag):
            return self.plant.read(tag)
        return self.sim.get(tag)

    def write(self, tag: str, value: object) -> None:
        if self.plant is not None and self.plant.owns(tag):
            self.plant.write(tag, value)
        else:
            self.sim.put(tag, value)

    def advance(self, ms: float) -> None:
        """Let ms pass in whole scans (at least one, so a write is seen by the logic)."""
        n = max(1, round(ms / self.scan_ms))
        for _ in range(n):
            self._step(self.scan_ms)
            self.now_ms += self.scan_ms
