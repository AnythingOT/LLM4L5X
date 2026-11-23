# Plant models

A plant model plays the field devices: it reads the PLC's command tags and writes the feedback a real
device would give, after the time a real device takes. Used by scenario tests and the Energise page,
against our simulator, an emulator or a controller (the plant only sees tag values).

## Devices

| type | reads | writes | timing | faults (`PLANT:<name>.fault`) |
|---|---|---|---|---|
| `motor` / `pump` / `fan` | `cmd` | `running`, `overload` (both optional) | `start_ms`, `stop_ms` | `fail_to_start`, `trip`, `fb_stuck_on` |
| `valve` (2-position) | `open_cmd`, `close_cmd` (empty = spring return) | `open_ls`, `closed_ls` (each optional) | `travel_ms` | `stuck`, `slow`, `open_ls_off`, `open_ls_on`, `closed_ls_off`, `closed_ls_on` |

- A motor without `running` has no feedback: nothing is simulated, a test checks the command only.
- A double-solenoid valve holds with no command; both commands on holds too and is noted as a logic error.
- A command shorter than the start delay never runs the motor; the result does not depend on step size.

## File

```yaml
devices:
  - {name: P101, type: pump, cmd: P101_Cmd, running: P101_Running, overload: P101_OL, start_ms: 1000}
  - {name: XV101, type: valve, open_cmd: XV101_Open, open_ls: XV101_ZSO, closed_ls: XV101_ZSC, travel_ms: 3000}
```
See `examples/tank_plant.yaml`. Each feedback tag belongs to one device; errors say what to fix.

## In tests

```
SET    PLANT:P101.fault = fail_to_start
EXPECT P101_Fail == 1  within_ms 6000
SET    PLANT:P101.fault = none
```
`PLANT:XV101.position` (0..1) and `PLANT:P101.running` can be read for diagnosis.

## Wiring it to the PLC

Feedback must reach the logic through mapped tags (`P101_Running`), not raw I/O
(`Local:1:I.Data.3`): on a controller the I/O module overwrites raw inputs every update. The mapping
routine copies raw I/O to mapped tags and is skipped while `Sim_Mode` is on.
