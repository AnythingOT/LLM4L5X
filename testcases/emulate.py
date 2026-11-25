"""Run test cases on Logix Emulate (or a controller) through pylogix: a backend like SimBackend.

Time is real time here: advance(ms) waits ms, polling the device models every poll_ms, so an EXPECT
with within_ms needs room for the poll (tens of ms). pylogix is imported only when this backend is
used, so the rest of the app does not need it: pip install pylogix.
"""

from __future__ import annotations

import time


class EmulateError(RuntimeError):
    pass


class EmulateBackend:
    def __init__(self, ip: str = "127.0.0.1", slot: int = 2, plant=None, poll_ms: float = 20.0, comm=None,
                 clock=time.monotonic, sleep=time.sleep):
        if comm is None:
            try:
                from pylogix import PLC
            except ImportError:
                raise EmulateError("pylogix is not installed: pip install pylogix") from None
            comm = PLC()
            comm.IPAddress = ip
            comm.ProcessorSlot = slot
            comm.SocketTimeout = 2.0
        self.comm, self.plant, self.poll_ms = comm, plant, poll_ms
        self._clock, self._sleep = clock, sleep
        self._t0 = clock()
        self._last = self._t0
        self.now_ms = 0.0
        self._seen: dict[str, bool] = {}

    # ------------------------------------------------------------ tags

    def _read(self, tag: str):
        r = self.comm.Read(tag)
        if r.Status != "Success":
            raise EmulateError(f"read {tag}: {r.Status}")
        return r.Value

    def has(self, tag: str) -> bool:
        if self.plant is not None and self.plant.owns(tag):
            return tag[len("PLANT:"):].partition(".")[0] in self.plant.devices
        if tag not in self._seen:
            self._seen[tag] = self.comm.Read(tag).Status == "Success"
        return self._seen[tag]

    def read(self, tag: str):
        if self.plant is not None and self.plant.owns(tag):
            return self.plant.read(tag)
        v = self._read(tag)
        return int(v) if isinstance(v, bool) else v

    def write(self, tag: str, value) -> None:
        if self.plant is not None and self.plant.owns(tag):
            self.plant.write(tag, value)
            return
        r = self.comm.Write(tag, value)
        if r.Status != "Success":
            raise EmulateError(f"write {tag} = {value}: {r.Status}")

    # ------------------------------------------------------------ time

    def _tick(self) -> None:
        now = self._clock()
        if self.plant is not None:  # the device models answer the commands, on the real clock
            dt = (now - self._last) * 1000.0
            cmds = {t: self._read(t) for t in self.plant.commands()}
            for tag, v in self.plant.step(dt, cmds).items():
                self.write(tag, int(v))
        self._last = now
        self.now_ms = (now - self._t0) * 1000.0

    def advance(self, ms: float) -> None:
        """Let ms of real time pass, at least one poll, stepping the device models on the way."""
        end = self._clock() + ms / 1000.0
        self._tick()
        while self._clock() < end:
            self._sleep(min(self.poll_ms / 1000.0, max(end - self._clock(), 0.0)))
            self._tick()

    def close(self) -> None:
        close = getattr(self.comm, "Close", None)
        if close:
            close()
