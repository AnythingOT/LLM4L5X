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

## Plain English (needs a local model)

Pick where the model runs on the ⚙️ Settings page (or click the model badge in the header). The model list is read from the server.

| Runs on | Start it | Answers |
|---|---|---|
| **Ollama** (default) | install from ollama.com, `ollama pull phi4-mini` | free text; syntax mistakes are sent back to the model to fix |
| **llama.cpp server**, direct GGUF | `llama-server -m model.gguf --port 8080` (Windows CPU build from llama.cpp's GitHub releases, GGUF from Hugging Face) | **grammar-constrained**: every answer is valid LogicSpec using only allowed tag names |
| OpenAI-compatible (LM Studio, Jan, vLLM) | start its local server | free text, as Ollama |

**Measured:** Qwen3.6-35B-A3B (UD-Q4_K_M) on llama.cpp, CPU only: 238/240 on a fresh suite seed, about 12 s per request. With that model the grammar made no measurable difference (it is insurance); for a small model such as phi4-mini, malformed answers were 65 of its 98 failures. Thinking is always off on llama.cpp: forced think tags break the grammar.

1. Start a model server (above).
2. In the GUI, describe what you want: *"Start the pump with the start button and keep it running until stop is pressed or the pump faults."*
3. You get a plain-English read-back of what the rungs do, the rungs, the tags, the checks, **Copy** and **Download**. Check the read-back first: it says what the logic will actually do.

**Attach your project's .L5X first.** The model is then shown your real tags (matched by name and description) and asked to use them. A new tag that looks like a typo of an existing one is flagged (*"did you mean Pump_Run?"*).

Improve results without fine-tuning by adding examples in your plant's wording to `inputs/examples.yaml`. The most similar ones are shown to the model for each request.

**Compare models by measurement:** `python cli.py eval --model phi4-mini` scores a model on `eval/requests.yaml` by meaning (truth tables), not text. Add your own requests there.

## Instruction test suite (series, parallel, nested)

`eval/suite.py` generates English requests with expected rungs for 24 instructions (XIC XIO OTE OTL OTU ONS, EQ NE GT LT GE LE, ADD SUB MUL DIV, MOVE COP CLR, TON TOF CTU CTD RES) in five structures: single, series, parallel, nested and multi-output. Example:

> *When either both Door_Open is not active and Manual_Mode is on, or Scaled_Value is not equal to 10, set Ready_Light and keep it set.*
> → `[XIO(Door_Open) XIC(Manual_Mode) ,NEQ(Scaled_Value,10) ]OTL(Ready_Light);`

Answers are scored by **behaviour, not text**. Expected and produced rungs run in the scan simulator on the same random input sequences, over time for timers, and every output is compared. The comparator catches about 99% of deliberately broken rungs, and the old Excel `EXACT` would wrongly fail about 9% of correct answers.

```
python cli.py suite --self-test --per 10                                  # compiler vs reference, no model
python cli.py suite --model phi4-mini --per 2 --excel suite_phi4.xlsx      # your model, Excel report
python cli.py suite --model qwen3.6:35b-a3b --no-think --only ONS,TON,GT    # a subset
```
`--version 36` uses the v36 names (EQ, GT, MOVE …). On CPU, a model run costs roughly (cases × seconds per request). `--per 1` is 120 cases.

## GUI

Three pages, AnythingOT look, light and dark. Press **?** on the chat page for the help popup; **ⓘ** in the input box shows examples and project commands.

- **Chat** (`/`)
  - **Plain English → ladder** (needs a model). Read-back, rungs, tags, checks. **Copy** gives the rung text in the form chosen in Settings (neutral or ASCII); **Download** gives `Routine.L5X` or `Rung.L5X`, also chosen in Settings.
  - **Paste rungs** in either form: neutral `XIC(a)[XIC(b) ,XIO(c) ]OTE(d);` (as in L5X) or ASCII `XIC a BST XIC b NXB XIO c BND OTE d` (one rung per line; `SOR … EOR` accepted). You get the other form, what each rung does in English, the checks, **Copy** (the other form) and **Download**.
  - **Attach an `.L5X`** (controller, program, routine or rung export; button or drag-and-drop). New logic then uses your real tags, AOIs and version. Commands: `summary`, `decompile` (every rung in English), `validate`, `xref TagName`.
  - LogicSpec, the language the model writes, is not shown. Typing it still works, for testing.
  - **Logic | UDT** switch in the input box. In UDT mode you create data types (below).
- **Settings** (`/settings`): model (backend, address, model, thinking), output (rung text form, download type, names, version, tag scope), Advanced (timer operand style, helper tag prefix, rung comments). Saved in the browser as you change them.
- **Rules** (`/rules`): the 49 validation rules, grouped, with search and severity filter; switch each on or off.

## UDTs: create and optimize

Switch the input box to **UDT**.

| Input | Uses the model | Output |
|---|---|---|
| Plain English: *"a motor with running and faulted bits, speed in rpm and 32 alarm bits"* | yes | `Name.L5X`, or `UDTs.zip` for several |
| The UDT text form (`UDT Name "desc";` then `Member TYPE[n] "desc";` lines) | no | same |
| An Excel sheet (`.xlsx`, template under ⓘ: one row per member, blank UDT cell = same UDT as above) | no | same |
| An attached UDT export, or a program, then **optimize UDTs** | no | `Name_opt.L5X`, a zip of them, or the whole program |

- New UDTs are checked (names, types, BOOL arrays in multiples of 32, nesting loops, names already in the attached project) and written in the order that wastes no memory: BOOLs packed into hidden SINT hosts the way Studio 5000 names them, then members by alignment. The model writes only the UDT text form, under a grammar on llama.cpp; a failed check goes back to it, as for rungs.
- **Optimize** reorders members only. Every member's XML (descriptions, radix, external access, CDATA) is kept byte for byte; only BIT positions change. It shows per UDT the bytes now → after, instances (nested ones included) and the total saved, and flags what depends on byte offsets: COP/CPS, MSG local elements, produced/consumed tags. Only UDTs that save bytes and have no such risk are ticked.
- The **whole-program** file also has to move tag values: each tag value is stored twice, by member name (Decorated) and by position (L5K). For affected tags the L5K copy is removed and the Decorated copy kept. UDTs used inside an AOI, or with a tag that has only L5K values, are left out, and the download says so. **Not yet confirmed by an import test: test it on a copy before you rely on it.**
- Sizes are computed from the layout rules, not read from Studio 5000. A UDT can only be changed offline.

The optimizer gives the same orders and sizes as [L5X_UDTOptimizer](https://github.com/AnythingOT/L5X_UDTOptimizer) on its samples; this repo replaces it.

## Validate: import checks and rules

`validate` (GUI, or `python cli.py validate plant.L5X`) runs two layers:

1. **Import checks** (`core/validator.py`): will Studio 5000 accept it. Syntax, operand count and types, tags that exist, instruction names for the target version (GRT before v36, GT from v36).
2. **Rules** (`lint/`): 49 programming rules with fixed codes. The prefix is the severity: **CRT** critical, **ERR** error, **WAR** warning, **INF** info. A rule can be switched off (Rules page, or `--disable INF004,INF003`), never softened, so a code always means the same thing.
   - 19 *rung* rules (duplicate OTE, reused timer or one-shot, unguarded division, unchecked array index, writes to status bits ...) also check every generated or pasted rung. Two of them, a reused timer and a reused one-shot, send the model back for another attempt.
   - 30 *project* rules (fault handlers, task watchdogs and names, uncalled routines, unscheduled programs, I/O mapping and comments, aliases, electronic keying, module lifecycle, UDT padding and order, descriptions ...) need a full controller export; on a partial export only the rung rules run, and the report says so.
   - Accept one case by writing `lint:disable=ERR010` (or `lint:disable` for all rules) in that rung's comment or that tag's or AOI's description. Suppressed findings are listed separately, never dropped.
   - Rules that an export cannot answer (no MajorFaultProgram attribute, say) are reported as *not verified*, not as passed. A rule that crashes is reported too.
   - Module lifecycle uses `lint/lifecycle.json`: seed data from public Rockwell discontinuation notices, dated in its `_meta`. Check it against Rockwell's PCDC before buying anything, and edit the file to add your modules.

`python cli.py validate --rules` lists the rules. The rules are a rewrite, for this repo's parser and data model, of the checklist in [L5X_Lint](https://github.com/AnythingOT/L5X_Lint), with the same codes.

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

Actions: `SET X`, `RESET X`, `CLEAR N`, `RESET_ACC T`, `COUNT_UP(C, 10)`, `COUNT_DOWN(C, 10)`, `ON_DELAY_TIMER(T, 5s)`, `OFF_DELAY_TIMER(T, 5s)` (older `START_TIMER`/`START_OFF_TIMER` still accepted), `N := A`, `N := A + B` (`-` `*` `/`).

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
python cli.py validate plant.L5X --disable INF003,INF004
python cli.py validate --rules
python cli.py survey folder_of_exports
python cli.py ask "run the pump from start, stop with stop" --project plant.L5X --model phi4-mini -o pump.L5X
python cli.py eval --model qwen3.6:35b-a3b --no-think
python cli.py suite --backend llamacpp --per 1 --excel suite_llamacpp.xlsx   # grammar-constrained
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
lint/               rules.py (the 49-rule checklist), checks_*.py, context.py, paths.py, lifecycle.json
udt/                layout.py (sizes, alignment, best order), model.py (UDT text form, checks),
                    writer.py (DataType export), excel.py (sheet + template), optimize.py (reorder
                    an existing export, byte-preserving)
explain/            decompiler.py (rungs -> LogicSpec), describe.py (English), survey.py
inputs/             llm.py (Ollama/llama.cpp, English -> LogicSpec), examples.yaml (few-shot), gbnf.py,
                    udt_llm.py (English -> UDT text form)
eval/               requests.yaml + run.py (hand-written eval), suite.py + suite_run.py (generated
                    instruction suite), rung_compare.py (behavioural oracle), mutation.py
gui/                templates/ (base, index, settings, rules), static/ (style.css, common.js,
                    app.js, settings.js, rules.js, favicon.ico)
tests/              pytest (299 tests); fixtures/ are hand-written, except studio_single_udt.L5X (the public L5X_UDTOptimizer sample)
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
