# LLM4L5X

Plain logic → ladder for Rockwell Studio 5000, importable as L5X, and back again. Everything runs locally, and it's built so a **small local LLM** can be added later as one optional input.

You (or later a model) write **LogicSpec**, a tiny boolean language. Deterministic code compiles it into rungs (branches included), checks them and writes the L5X. **No AI is needed for any of this.**

```
LogicSpec ─> compiler ─> rungs ─> validator ─> L5X
                                     ▲
       existing L5X ─> reader ─> decompiler ─> LogicSpec + plain English
```

## Quick start (Windows)

1. Install **Python 3.10+** from python.org and tick **"Add python.exe to PATH"**.
2. Download or clone this repo.
3. Double-click **`start.bat`**. The first run installs everything into `.venv`; after that it just opens the GUI at http://127.0.0.1:5000.

Manual alternative from the repo folder (Linux/macOS: `./start.sh`):
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

## GUI

A chat-style page, same look as LLM4L5XGen:

- **Type LogicSpec.** You get a plain-English read-back to check, the rungs, any new tags, the checks, and a **Download L5X** button.
- **Paste rung text** (e.g. `XIC(a)[XIC(b) ,XIO(c) ]OTE(d);`). You get LogicSpec and English back.
- **Attach an `.L5X` export** (button or drag-and-drop). New logic is then checked against your real tags and AOIs. Project commands: `summary`, `decompile`, `validate`, `xref TagName`.
- **⚙️ Settings:** rungs vs. new routine, routine/program/controller names, software revision, tag scope, timer operand style, auto-tag prefix, rung comments.

The server listens on `127.0.0.1` only, so nothing leaves your PC.

## LogicSpec in one minute

| LogicSpec | Ladder |
|---|---|
| `X := expr;` | conditions then `OTE(X)` |
| `IF expr THEN action, action;` | conditions then the action(s); several become an output branch |
| `IF TRUE THEN action;` | unconditional |
| `A` / `NOT A` | `XIC(A)` / `XIO(A)` |
| `a AND b` / `a OR b` | series / branch |
| `N = 5` `<>` `>` `<` `>=` `<=` | `EQU NEQ GRT LES GEQ LEQ`, or `EQ NE GT LT GE LE` for v36+ |
| `RISE(expr)` | `ONS` with an auto storage bit |
| `DELAY(expr, 5s [, Timer])` | helper rung `expr TON(T,?,?)`, then `XIC(T.DN)` (`OFFDELAY` → `TOF`) |

Actions: `SET X`, `RESET X`, `CLEAR N`, `RESET_ACC T`, `COUNT_UP(C, 10)`, `COUNT_DOWN(C, 10)`, `START_TIMER(T, 5s)`, `START_OFF_TIMER(T, 5s)`, `N := A`, `N := A + B` (`-` `*` `/`).

Rules:
- **AND and OR can't be mixed without parentheses**, so precedence mistakes are impossible.
- `:=` at statement level is a coil; inside `IF … THEN` it's a move or math.
- Tag types are inferred from use. Attach your project so existing tags are reused instead of created.
- **Instruction names follow your Logix Designer version.** v36 renamed `GRT`→`GT`, `EQU`→`EQ`, `MOV`→`MOVE` and others. Set ⚙️ *Logix Designer version*; attaching a project sets it automatically.

Full reference and design: [docs/DESIGN.md](docs/DESIGN.md).

## Command line

Run from the repo folder with `.venv` active:
```
python cli.py compile examples\pump_station.spec -o pump.L5X
python cli.py compile spec.txt --routine Generated --project plant.L5X --program MainProgram -o r.L5X
python cli.py inspect plant.L5X --decompile
python cli.py inspect plant.L5X --xref Pump
python cli.py validate plant.L5X
python cli.py survey folder_of_exports
python cli.py rung "XIC(a)[XIC(b) ,XIO(c) ]OTE(d);"
```

## Repo layout

```
app.py              GUI server (python app.py)
cli.py              command line (python cli.py ...)
core/               catalog.py + instructions.yaml, rung.py, logicspec.py,
                    compiler.py, validator.py, simulator.py
l5x/                reader.py, writer.py, xref.py
explain/            decompiler.py (rungs -> LogicSpec), describe.py (English), survey.py
inputs/             front ends that produce LogicSpec: gbnf.py now; Excel C&E and LLM later
gui/                templates/index.html, static/ (style.css, app.js, favicon.ico)
tests/              pytest (122 tests); fixtures/ is hand-written, not a real export
examples/  docs/
requirements.txt  start.bat  start.sh
```

Run the tests with `pytest` from the repo folder.

## Checked against real exports

The parser was checked against 179 public L5X exports (3,160 rungs, including Rockwell's own samples):
**100% parse, 99.9% print back byte-for-byte**, and the timer format `TON(T,?,?)`, the timer
data layout and the AOI call format are all confirmed. Details are in docs/DESIGN.md section 9.
Run the same check on your own exports:

```
python cli.py survey C:\path\to\your\exports
```

**Not yet tested: importing a generated file into Studio 5000.** That is the most useful next step.

## Safety

Generated code is a draft for an engineer. Read the English read-back, verify offline, and never download straight to a running controller. Keep safety routines out of scope.

## License

MIT
