"""Device models: motor/pump with or without run feedback, 2-position valve (single or double
solenoid, 0, 1 or 2 limit switches)."""

from __future__ import annotations

from dataclasses import dataclass, field


class PlantError(ValueError):
    pass


@dataclass
class Device:
    name: str
    fault: str = ""  # one of FAULTS[type]; "" = healthy
    notes: list[str] = field(default_factory=list)  # things a test should know (both solenoids on)

    kind = "device"

    def commands(self) -> list[str]:
        """PLC output tags this device reads."""
        raise NotImplementedError

    def feedbacks(self) -> list[str]:
        """PLC input tags this device writes."""
        raise NotImplementedError

    def step(self, dt_ms: float, cmd: dict[str, bool]) -> dict[str, bool]:
        raise NotImplementedError

    def state(self) -> dict[str, object]:
        """What PLANT:<name>.<attr> exposes to a test, besides fault."""
        return {}


@dataclass
class Motor(Device):
    """A motor or pump started by one command. Running follows the command after start_ms / stop_ms.

    No running tag = a motor without feedback: nothing to simulate, a test checks the command only.
    Faults: fail_to_start (never runs), trip (stops, overload on), fb_stuck_on (running stays on).
    """
    cmd: str = ""
    running: str = ""
    overload: str = ""
    start_ms: float = 1000.0
    stop_ms: float = 500.0
    _on: bool = False
    _timer: float = 0.0

    kind = "motor"

    def commands(self) -> list[str]:
        return [self.cmd]

    def feedbacks(self) -> list[str]:
        return [t for t in (self.running, self.overload) if t]

    def step(self, dt_ms, cmd):
        want = bool(cmd.get(self.cmd)) and self.fault not in ("fail_to_start", "trip")
        if self.fault == "fb_stuck_on":
            self._on = True
        elif want != self._on:
            self._timer += dt_ms
            if self._timer >= (self.start_ms if want else self.stop_ms):
                self._on, self._timer = want, 0.0
        else:
            self._timer = 0.0
        out = {}
        if self.running:
            out[self.running] = self._on
        if self.overload:
            out[self.overload] = self.fault == "trip"
        return out

    def state(self):
        return {"running": self._on}


@dataclass
class Valve(Device):
    """A 2-position valve. Position runs 0 (closed) to 1 (open) over travel_ms.

    Single solenoid (close_cmd empty): open_cmd on opens, off closes (spring return).
    Double solenoid: open_cmd opens, close_cmd closes, neither holds, both holds and is noted.
    Limit switches: open_ls on at fully open, closed_ls on at fully closed; either may be absent.
    Faults: stuck (does not move), slow (3 x travel time), open_ls_off / open_ls_on /
    closed_ls_off / closed_ls_on (switch failed off or on).
    """
    open_cmd: str = ""
    close_cmd: str = ""
    open_ls: str = ""
    closed_ls: str = ""
    travel_ms: float = 3000.0
    position: float = 0.0  # starts closed

    kind = "valve"

    def commands(self) -> list[str]:
        return [t for t in (self.open_cmd, self.close_cmd) if t]

    def feedbacks(self) -> list[str]:
        return [t for t in (self.open_ls, self.closed_ls) if t]

    def _target(self, cmd) -> float | None:
        o = bool(cmd.get(self.open_cmd))
        if not self.close_cmd:
            return 1.0 if o else 0.0
        c = bool(cmd.get(self.close_cmd))
        if o and c:
            note = f"{self.name}: open and close commands on together"
            if note not in self.notes:
                self.notes.append(note)
            return None
        return 1.0 if o else 0.0 if c else None

    def step(self, dt_ms, cmd):
        target = self._target(cmd)
        if target is not None and self.fault != "stuck":
            travel = self.travel_ms * (3 if self.fault == "slow" else 1)
            move = dt_ms / travel if travel > 0 else 1.0
            self.position = min(target, self.position + move) if target > self.position \
                else max(target, self.position - move)
        out = {}
        if self.open_ls:
            out[self.open_ls] = {"open_ls_off": False, "open_ls_on": True}.get(self.fault, self.position >= 1.0)
        if self.closed_ls:
            out[self.closed_ls] = {"closed_ls_off": False, "closed_ls_on": True}.get(self.fault, self.position <= 0.0)
        return out

    def state(self):
        return {"position": round(self.position, 3)}


FAULTS = {
    "motor": ("fail_to_start", "trip", "fb_stuck_on"),
    "valve": ("stuck", "slow", "open_ls_off", "open_ls_on", "closed_ls_off", "closed_ls_on"),
}
