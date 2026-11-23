# Block library

A block is one YAML file that gives a device everything at once: rungs, tag types, a plant model and
scenario tests. Code fills in the names; nothing is written by a model.

```python
from library import load_library
inst = load_library()["Motor"].instantiate({"name": "P101"})
inst.rungs      # 4 rungs, commented      inst.tags      # P101_Cmd BOOL, P101_FTS_TMR TIMER ...
inst.plant      # motor model entry       inst.scenarios # start/stop, fail-to-start, no false alarm
```

| block | what it does | its scenarios |
|---|---|---|
| **Motor** | start/stop with seal-in, run feedback, fail-to-start alarm that stops it until reset | runs and stops; fail to start alarms and stops; normal start raises no alarm |
| **Valve2Pos** | single solenoid, open/closed limit switches, travel alarm that drops the command until reset | opens and closes; stuck alarms and drops the command |
| **AlarmLatch** | on-delay alarm that latches and resets only once the condition has cleared | raises after its delay; ignores a blip; cannot be reset while present |

## A block file

```yaml
name: Motor
version: "1.0"
params:                       # name is required in every block; defaults may use earlier params
  name: {description: instance name, e.g. P101}
  cmd: {default: "{name}_Cmd"}
  fts_ms: {default: 5000}
rungs:
  - rung: "XIC({cmd})XIO({running})TON({name}_FTS_TMR,{fts_ms},0);"
    comment: "{name}: no run feedback within {fts_ms} ms"
tags: {"{cmd}": BOOL, "{name}_FTS_TMR": TIMER}
plant: {name: "{name}", type: motor, cmd: "{cmd}", running: "{running}"}
scenarios: |
  SCENARIO {name}-OK "{name} normal start raises no alarm"
    ...
```

- Every value must be a tag name or a number. A placeholder that is not a parameter is an error.
- A block is checked **when the library loads**: built once from its defaults, its rungs must parse
  and pass the rung rules (no errors), its plant entry and scenarios must load. A broken block never
  reaches a project.
- `load_library("C:/Company/Blocks")` adds a company folder; a company block with the same name as a
  starter replaces it. Keep company libraries outside this repo.
- A block passes its own scenarios with its own plant model; that is tested for every starter.

Next: requirement rows that name a block ("P-101 is a Motor"), instantiated by the compiler.
