# LLM4L5X

[![CI](https://github.com/AnythingOT/LLM4L5X/actions/workflows/ci.yml/badge.svg)](https://github.com/AnythingOT/LLM4L5X/actions/workflows/ci.yml)

Ladder logic and UDTs for Rockwell Studio 5000, from plain English, rung text or Excel, as L5X files you import;
then run the logic on your PC against device models and test cases before it goes near a controller.
Runs on your PC with a local model, completely offline. Nothing leaves the PC.

The model only writes. Fixed code draws every rung as ladder, checks it, simulates it and writes the L5X, so
nothing the model gets wrong reaches a file unchecked. Check the plain-English read-back before you import.

## What it does

**Chat** (the main page)

| Input | Output | Done by |
|---|---|---|
| Plain English: *"Start the pump with the start button and keep it running until stop is pressed."* | Rungs, read-back, checks; `Routine.L5X` or `Rung.L5X` | Model |
| Plain English, UDT mode: *"A motor with run and fault bits, speed and 32 alarms."* | UDT in the order that wastes no memory; `Name.L5X` | Model |
| Rung text: `XIC(a)[XIC(b) ,XIO(c) ]OTE(d);` or `XIC a BST XIC b NXB XIO c BND OTE d` | Ladder, read-back, checks; `Routine.L5X` or `Rung.L5X` | Fixed code |
| Requirements Excel: sheet = routine, row = requirement (Req ID, optional *Expected rung*) | One routine per sheet, requirement as rung comment; rows with an expected rung are scored by behaviour | Model (rows with rung text: fixed code) |
| UDT Excel: row = member | UDTs, checked and ordered | Fixed code |
| An L5X export (controller, program, routine, rungs or UDT) | Every rung in English above its ladder, and an L5X with the missing rung comments added; cross reference; validate (import checks and 50 coding rules); optimize UDTs | Fixed code |

**Other pages**

| Page | What it does |
|---|---|
| **Energize** | Runs the whole program on this PC in a scan simulator: flip inputs, watch power flow through the ladder, timers and counters count, outputs switch |
| **Devices** | Device models (pump, motor, valve) answer the outputs the way the machine would, after the time it takes, with faults on request |
| **Tests** | Test cases (`SET`, `WAIT`, `EXPECT P101_Cmd == 1 within_ms 100`) tied to requirement IDs, run against the program and the device models: pass or fail per requirement, a traceability matrix, and a PDF report that cannot be edited |
| **Lint** | The 50 rules on or off; `python cli.py fix` fixes findings where the fix is certain, each fix checked in the simulator |
| **Help** | What each part does |

Samples of both Excel files are in the app: the list button next to **Send**.

## Start

1. Install **Python 3.10+** from python.org (tick *Add python.exe to PATH*).
2. Download this repo and double-click **`start.bat`**. The first start installs the packages, once, into your user folder (`%LOCALAPPDATA%\LLM4L5X\venv`), not into the download: a newer download starts at once, and packages are installed again only when `requirements.txt` changes. No git needed. Then the app opens at http://127.0.0.1:5000.
   (Linux/macOS: `./start.sh`.)
3. For plain English, start a model server and pick it in ⚙️ Settings. Rung text, Excel UDTs and attached L5X files need no model.

## The model

What worked for us: **Qwen3.6-35B-A3B** ([`UD-Q4_K_M` GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF), about 22 GB)
on **llama.cpp**, CPU only, 64 GB RAM: about 12 s a request. On our instruction suite it got 238 of 240 right
(scored by behaviour in the simulator, not by text). Read that number for what it is: the suite's requests
are generated from templates that name every tag exactly, for 24 instructions. How it does on an engineer's
own wording, and with smaller models, is not measured yet.
Start it in its own window and keep that window open:

```
llama-server -m "C:\path\to\Qwen3.6-35B-A3B-UD-Q4_K_M.gguf" --alias Qwen3.6-35B-A3B --host 127.0.0.1 --port 8080 -c 32768 --jinja
```

Then choose **llama.cpp** in Settings. Keep `--jinja`; do not add `--reasoning-budget 0` (it breaks the grammar).
Ollama works too: set *Thinking* to off in Settings. Details: [docs/GUIDE.md](docs/GUIDE.md#the-model).

## Tips

- **Attach your project's L5X first.** New logic then uses your real tag names, AOIs and Logix Designer version.
- Name tags as they are in the project. Say "latch" for OTL; "turn on" means a normal coil.
- Switch coding rules on or off on the **Lint** page.

## Status

Measured on 858 public L5X exports (6,959 rungs) in CI, November 2026:

| | |
|---|---|
| Rungs read | 98.9% |
| Rungs explained in English | 55%. The rest use instructions the explainer does not have yet (CPT, string instructions, AOI calls) |
| Routines Energize can run whole | 49%. The simulator has 36 of the 124 catalog instructions: bits, timers, counters, compare, math, move. Missing ones (CPT, string instructions, AOI bodies, MSG, PID) stop the load with a list, never a silent skip |

- **Verified in Studio 5000:** generated routines and rungs import; UDTs from Excel and routines from a requirements Excel import.
- **Not verified yet:** a timer keeps its preset after import; tag values survive a whole-program UDT reorder
  (test on a copy).
- **The simulator is ours.** It has not yet been compared instruction by instruction with a real controller
  or Logix Emulate. Until it is, a passing test says the logic is right in our simulator, not on the controller.
- Generation covers 24 instructions; real programs also need JSR, CPT, AOI calls, MSG and PID, written by hand today.
- Tested on Windows by one user. CI runs on Linux.

A requirements Excel with an *Expected rung* column scores the model row by row; `python -m eval.expected_workbook`
makes one. See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

Planned: documentation written from an attached program; translating comments, descriptions and tag names to English.

## Safety

Generated code is a draft for an engineer. Read the read-back, test offline, and never download straight to a running
controller. Energize and Tests are a check before commissioning, not a replacement for it. Keep safety routines out of scope.
The test report states what was run and what passed; it makes no claim of compliance with any standard.

## More

- [docs/HANDOVER.md](docs/HANDOVER.md) and [docs/ROADMAP.md](docs/ROADMAP.md): start here when picking the work up: how the code fits, working rules, results so far, and what is next.
- [docs/GUIDE.md](docs/GUIDE.md): every feature in detail, rules, LogicSpec, command line.
- [STRUCTURE.txt](STRUCTURE.txt): every folder and file with one line each; each folder's README.md says what it owns and what it may use.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md): tests, the instruction test suite.
- [docs/DESIGN.md](docs/DESIGN.md): how it works inside.

This repo replaces [LLM4UDT](https://github.com/AnythingOT/LLM4UDT) and [L5X_UDTOptimizer](https://github.com/AnythingOT/L5X_UDTOptimizer), and
includes the [L5X_Lint](https://github.com/AnythingOT/L5X_Lint) rules.

MIT license. Icons and packages by others: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Studio 5000 and Logix Designer are trademarks of Rockwell Automation; this project is not affiliated with or endorsed by Rockwell Automation.
