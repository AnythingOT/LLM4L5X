# LLM4L5X

Plain English → ladder logic for Rockwell Studio 5000, importable as L5X, and back again. Everything runs on your PC with a **small local model** via Ollama. No cloud, no fine-tuning.

The model only writes **LogicSpec**, a tiny boolean language. Deterministic code compiles that into rungs (branches included), checks them and writes the L5X. If the model's answer fails a check, the exact error goes back to it for another try. Nothing the model writes reaches an L5X unchecked.

```
English ─> local model ─> LogicSpec ─> compiler ─> rungs ─> validator ─> L5X
                 ▲ retry with the error  │
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

## Plain English (needs Ollama)

1. Install Ollama from ollama.com, then `ollama pull phi4-mini` (or any model; set it in ⚙️).
2. In the GUI, describe what you want: *"Start the pump with the start button and keep it running until stop is pressed or the pump faults."*
3. You get the **LogicSpec the model understood**, a plain-English read-back, the rungs and a Download button. Check the read-back: it tells you what the logic will actually do.

**Attach your project's .L5X first.** The model is then shown your real tags (matched by name and description) and asked to use them. A new tag that looks like a typo of an existing one is flagged (*"did you mean Pump_Run?"*).

Improve results without fine-tuning by adding examples in your plant's wording to `inputs/examples.yaml`. The most similar ones are shown to the model for each request.

**Compare models by measurement:** `python cli.py eval --model phi4-mini` scores a model on `eval/requests.yaml` by meaning (truth tables), not text. Add your own requests there.

## GUI

A chat-style page, same look as LLM4L5XGen:

- **Describe logic in plain English** (needs Ollama), or type LogicSpec directly for testing. You get a read-back to check, the rungs, new tags, checks and a **Download L5X** button.
- **Paste existing rungs** in either text form Studio 5000 uses. You get the other form, LogicSpec and English back:
  - neutral text `XIC(a)[XIC(b) ,XIO(c) ]OTE(d);`, which is what L5X files contain
  - ASCII text `XIC a BST XIC b NXB XIO c BND OTE d`, the editor's ASCII mode (one rung per line; `SOR … EOR` accepted)
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
python cli.py ask "run the pump from start, stop with stop" --project plant.L5X --model phi4-mini -o pump.L5X
python cli.py eval --model qwen3.6:35b-a3b --no-think
python cli.py rung "XIC(a)[XIC(b) ,XIO(c) ]OTE(d);"
python cli.py rung "XIC a BST XIC b NXB XIO c BND OTE d"
```

## Repo layout

```
app.py              GUI server (python app.py)
cli.py              command line (python cli.py ...)
core/               catalog.py + instructions.yaml (124 instructions), rung.py, ascii.py, logicspec.py,
                    compiler.py, validator.py, simulator.py
l5x/                reader.py, writer.py, xref.py
explain/            decompiler.py (rungs -> LogicSpec), describe.py (English), survey.py
inputs/             llm.py (Ollama, English -> LogicSpec), examples.yaml (few-shot), gbnf.py
eval/               requests.yaml (English + expected LogicSpec), run.py (scoring)
gui/                templates/index.html, static/ (style.css, app.js, favicon.ico)
tests/              pytest (170 tests); fixtures/ is hand-written, not a real export
examples/  docs/
requirements.txt  start.bat  start.sh
```

Run the tests with `pytest` from the repo folder.

## Neutral text vs ASCII text

| | Neutral | ASCII |
|---|---|---|
| Example | `XIC(a)[XIC(b) ,XIO(c) ]OTE(d);` | `XIC a BST XIC b NXB XIO c BND OTE d` |
| Branches | `[` `,` `]` | `BST` `NXB` `BND` |
| In L5X files | **yes, always** | never |

LLM4L5X always writes neutral text into L5X. Generated rungs are also shown as ASCII, so you can paste a single rung into the editor's ASCII mode. Reading ASCII needs each instruction's operand count, so Add-On Instructions are only understood when the project defining them is attached. An operand containing spaces (e.g. a `CPT` expression) is written in double quotes; whether the editor expects exactly that is **unverified**.

## Checked against real exports

The parser was checked against 179 public L5X exports (3,160 rungs, including Rockwell's own samples):
**100% parse, 99.9% print back byte-for-byte, 99.9% survive neutral → ASCII → neutral**, and the timer format `TON(T,?,?)`, the timer
data layout and the AOI call format are all confirmed. Details are in docs/DESIGN.md section 9.
Run the same check on your own exports:

```
python cli.py survey C:\path\to\your\exports
```

**Import verified:** generated Rung and Routine L5X files import cleanly into Studio 5000.
Still to confirm: a timer import keeps its preset.

## Safety

Generated code is a draft for an engineer. Read the English read-back, verify offline, and never download straight to a running controller. Keep safety routines out of scope.

## License

MIT
