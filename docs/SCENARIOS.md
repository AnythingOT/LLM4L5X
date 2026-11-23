# Scenario tests

Requirement-level tests for the logic, with a plant model, in OpenVnV's step language. The same
scenario file runs on our simulator now and, through a pylogix backend, on an emulator or a controller.

```
SCENARIO TC-07 "fail to start alarms and stops" REQ R3
SETUP:
  SET Start_PB = 1
  WAIT 50
  SET Start_PB = 0
MAIN:
  SET PLANT:P101.fault = fail_to_start
  SET Level_Low = 1
  EXPECT P101_Cmd == 1 within_ms 100
  EXPECT P101_Fail == 1 within_ms 5200
  EXPECT P101_Cmd == 0 within_ms 100
TEARDOWN:
  SET PLANT:P101.fault = none
  CALL RTN
```

| step | meaning |
|---|---|
| `SET tag = value` / `RESET tag` | write a value / write 0. `PLANT:<device>.fault` injects a fault |
| `EXPECT tag op value` | one scan, then one read. op: `== != < <= > >=` |
| `... within_ms N` | polled every scan; passes the first time it is true within N ms |
| `... within_ms N hold` | must stay true for all N ms: the negative test ("no alarm on a normal start") |
| `... tolerance X` | for analog values: `== 50 tolerance 0.5` |
| `WAIT N` | let N ms pass |
| `CALL id` | run another scenario's steps here (a return-to-normal block) |
| `COMMENT text` | note in the results |

- `REQ R3, R5` links the scenario to requirements; the report gives a verdict per requirement.
- TEARDOWN always runs, even after a failure. MAIN stops at its first failure; a SETUP failure skips MAIN.
- Every tag is checked before the first step: an unknown tag stops the scenario, so a typo cannot
  pass a negative test (the simulator would read it as 0).
- Each scenario gets a fresh backend: one test's leftovers cannot decide the next.
- On the simulator, logic and plant share one clock (scan_ms, default 10 ms), so `within_ms` is
  measured, not estimated. On real hardware the resolution is the poll period plus network jitter:
  a `within_ms` below about twice the poll period means little there.
