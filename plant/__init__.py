"""Plant models: what the field devices do when the PLC drives them.

A plant model reads the PLC's command tags, waits the way real equipment waits, and writes the
feedback tags back: a pump's run contact closes a second after its contactor is energized; a valve
leaves its closed limit switch at once and reaches the open one after its travel time.

Everything is deterministic and driven by elapsed milliseconds, so the same scenario gives the same
result on every run. It does not need, or know, which PLC runs the logic: the scenario runner (or a
pylogix loop against an emulator or a controller) calls step() with the commands it read and writes
back the feedback it gets.

Faults are injected through plant tags, so a test needs no special action:
    SET PLANT:P101.fault = fail_to_start
"""

from __future__ import annotations

from .devices import FAULTS, Device, Motor, PlantError, Valve
from .plant import Plant, load_plant

__all__ = ["FAULTS", "Device", "Motor", "Plant", "PlantError", "Valve", "load_plant"]
