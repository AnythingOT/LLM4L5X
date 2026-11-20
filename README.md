# LLM4L5X

Ladder logic and UDTs for Rockwell Studio 5000, from plain English, rung text or Excel, as L5X files you import.
Runs on your PC with a local model, completely offline.

The model only writes. Fixed code draws every rung as ladder, checks it and writes the L5X, so nothing the
model gets wrong reaches a file unchecked. Check the plain-English read-back before you import.

## What it does

| Input | Output | Done by |
|---|---|---|
| Plain English: *"Start the pump with the start button and keep it running until stop is pressed."* | Rungs, read-back, checks; `Routine.L5X` or `Rung.L5X` | Model |
| Plain English, UDT mode: *"A motor with run and fault bits, speed and 32 alarms."* | UDT in the order that wastes no memory; `Name.L5X` | Model |
| Rung text: `XIC(a)[XIC(b) ,XIO(c) ]OTE(d);` or `XIC a BST XIC b NXB XIO c BND OTE d` | Ladder, read-back, checks; `Routine.L5X` or `Rung.L5X` | Fixed code |
| Requirements Excel: sheet = routine, row = requirement | One routine per sheet | Model (rows with rung text: fixed code) |
| UDT Excel: row = member | UDTs, checked and ordered | Fixed code |
| An L5X export (controller, program, routine, rungs or UDT) | Explain every rung, cross reference, validate (import checks and 50 coding rules), optimize UDTs | Fixed code |

Samples of both Excel files are in the app: the list button next to **Send**.

## Start

1. Install **Python 3.10+** from python.org (tick *Add python.exe to PATH*).
2. Download this repo and double-click **`start.bat`**. The first run installs everything; then the app opens at http://127.0.0.1:5000.
   (Linux/macOS: `./start.sh`.)
3. For plain English, start a model server and pick it in ⚙️ Settings. Rung text, Excel UDTs and attached L5X files need no model.

## The model

What worked for us: **Qwen3.6-35B-A3B** ([`UD-Q4_K_M` GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF), about 22 GB)
on **llama.cpp**, CPU only, 64 GB RAM: 238 of 240 test requests right, about 12 s each.
Start it in its own window and keep that window open:

```
llama-server -m "C:\path\to\Qwen3.6-35B-A3B-UD-Q4_K_M.gguf" --alias Qwen3.6-35B-A3B --host 127.0.0.1 --port 8080 -c 32768 --jinja
```

Then choose **llama.cpp** in Settings. Keep `--jinja`; do not add `--reasoning-budget 0` (it breaks the grammar).
Ollama works too: set *Thinking* to off in Settings. Details: [docs/GUIDE.md](docs/GUIDE.md#the-model).

## Tips

- **Attach your project's L5X first.** New logic then uses your real tag names, AOIs and Logix Designer version.
- Name tags as they are in the project. Say "latch" for OTL; "turn on" means a normal coil.
- Switch coding rules on or off on the **Rules** page.

## Status

- Verified: generated routines and rungs import into Studio 5000; UDTs from Excel and routines from a requirements Excel work.
- Not yet verified: a timer keeps its preset after import; tag values survive a whole-program UDT reorder (test on a copy).
- Tested on 241 real exports. A requirements Excel with an *Expected rung* column scores the model row by row;
  `python -m eval.test_workbook` makes one. See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

Planned: documentation written from an attached program; translating comments, descriptions and tag names to English.

## Safety

Generated code is a draft for an engineer. Read the read-back, test offline, and never download straight to a running
controller. Keep safety routines out of scope.

## More

- [docs/GUIDE.md](docs/GUIDE.md): every feature in detail, rules, LogicSpec, command line.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md): repo layout, tests, the instruction test suite.
- [docs/DESIGN.md](docs/DESIGN.md): how it works inside.

This repo replaces [LLM4UDT](https://github.com/AnythingOT/LLM4UDT) and [L5X_UDTOptimizer](https://github.com/AnythingOT/L5X_UDTOptimizer), and
includes the [L5X_Lint](https://github.com/AnythingOT/L5X_Lint) rules.

MIT license.
