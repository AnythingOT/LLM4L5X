# devices/

Device models: what the field devices do when the program drives them (pumps, motors, valves), so a program can run without the machine.

| | |
|---|---|
| Page | Devices (`/devices`); used by Energize and Tests |
| Command line | none |
| In | a device list (YAML) |
| Out | feedback tags, after the time a real device takes; faults on request |
| May import | nothing in this repository |
| Docs | [docs/DEVICES.md](../docs/DEVICES.md) |
| Tests | `tests/test_devices.py`, `test_devices_page.py` |

## Rules

- A device only sees tag values. The same models work against the simulator, an emulator or a controller.
- The class is still called `Plant` (all the devices of one machine), and the YAML key and fault tags say
  `PLANT:`. The folder carries the page's name.
