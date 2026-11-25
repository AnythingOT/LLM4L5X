# LLM4L5X guide

Everything the app does, in detail. The short version is the [README](../README.md).

- [How it works](#how-it-works)
- [The model](#the-model)
- [The app](#the-app)
- [UDTs: create and optimize](#udts-create-and-optimize)
- [Requirements Excel to ladder](#requirements-excel-to-ladder)
- [Validate: import checks and rules](#validate-import-checks-and-rules)
- [Neutral text and ASCII text](#neutral-text-and-ascii-text)
- [LogicSpec](#logicspec)
- [Command line](#command-line)
- [Energize: run the whole program before any controller](#energize-run-the-whole-program-before-any-controller)
- [Tests: test cases, pass or fail per requirement](#tests-test-cases-pass-or-fail-per-requirement)
- [Device models](#device-models)

## How it works

The model only writes **LogicSpec**, a small boolean language. Fixed code compiles it into rungs (branches
included), checks them and writes the L5X. If an answer fails a check, the error goes back to the model for
another try.

```
English ─> local model ─> LogicSpec ─> compiler ─> rungs ─> checks ─> L5X
                 ▲ retry with the error  │
       existing L5X ─> reader ─> decompiler ─> LogicSpec + plain English
```

The app listens on `127.0.0.1` only, so other machines cannot reach it. Other web pages in your own browser could still send it requests, so it refuses any request that changes something unless it comes from its own page, and any request addressed to a host name other than `127.0.0.1`, `localhost` or `::1`. To serve it on your network on purpose, list the extra names in `LLM4L5X_ALLOWED_HOSTS` (comma-separated).

The model server must be on this PC too: every request sends your tag names, rung comments and requirement text to it. An address that is not `localhost`, `127.x.x.x` or `::1` is refused unless **Allow a model server on another computer** is ticked in Settings (command line: `--allow-remote`); while it is, every page shows a banner naming the host, and Report.txt says so in its second line. Only `http://` and `https://` addresses are accepted. L5X files above 200 MB are refused.

## The model

Pick where the model runs on the ⚙️ Settings page (or click the model badge in the header). The model list is read from the server.

| Runs on | Start it | Answers |
|---|---|---|
| **Ollama** (default) | install from ollama.com, `ollama pull phi4-mini` | free text; syntax mistakes are sent back to the model to fix |
| **llama.cpp server**, direct GGUF | `llama-server -m model.gguf --port 8080` (Windows CPU build from llama.cpp's GitHub releases, GGUF from Hugging Face) | **grammar-constrained**: every answer is valid LogicSpec using only allowed tag names |
| OpenAI-compatible (LM Studio, Jan, vLLM) | start its local server | free text, as Ollama |

Keep the model server on this PC. llama-server and Ollama listen on `127.0.0.1` by default: do not add `--host 0.0.0.0` (or set `OLLAMA_HOST=0.0.0.0`). That opens the model to the whole network, and every request carries your tag names and requirements.

### The setup that worked for us

**Qwen3.6-35B-A3B, `UD-Q4_K_M` GGUF ([unsloth/Qwen3.6-35B-A3B-GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF), about 22 GB) on llama.cpp's `llama-server`, CPU only, 64 GB RAM, no GPU.**

- 238/240 on a fresh instruction-suite seed (226/240 and 114/120 on earlier seeds, before suite fixes), about 12 s per request.
- With this model the grammar made no measurable difference (113 vs 114 of 120 on the same seed): it is insurance against unparseable answers. For a small model it matters: with phi4-mini, malformed answers were 65 of its 98 failures.

Start the server in its own terminal and keep it open while you use the app:

```
llama-server -m "C:\path\to\Qwen3.6-35B-A3B-UD-Q4_K_M.gguf" --alias Qwen3.6-35B-A3B --host 127.0.0.1 --port 8080 -c 32768 --jinja
```

- `--jinja` is required: the app switches thinking off through the model's chat template.
- Do **not** add `--reasoning-budget 0`: it breaks the grammar ("Unexpected empty grammar stack"). The app turns thinking off per request instead.
- `--host 127.0.0.1` keeps the server reachable from this PC only; llama-server has no password.
- `-c 32768` is the context window: the prompt, examples, your project's tags and the answer. Use 16384 to save RAM on small projects, 65536 for very large ones. With Ollama the same setting is in ⚙️ Settings, Context window.
- `--alias` only sets the model name shown in the app.

Then start the app (`start.bat`) and choose **llama.cpp** in ⚙️ Settings; `http://127.0.0.1:8080` is the default address. Settings only says where the server is; it does not start it.

Ollama's `qwen3.6:35b-a3b` is the same model but untested here. If you use it, set **Thinking: off** in Settings (Ollama's default for Qwen3.6 is on, which is much slower on a CPU), and note that Ollama accepts no GBNF grammar.

1. Start a model server (above).
2. In the GUI, describe what you want: *"Start the pump with the start button and keep it running until stop is pressed or the pump faults."*
3. You get a plain-English read-back of what the rungs do, the rungs, the tags, the checks, **Copy** and **Download**. Check the read-back first: it says what the logic will actually do.

**Attach your project's .L5X first.** The model is then shown your real tags (matched by name and description) and asked to use them. A new tag that looks like a typo of an existing one is flagged (*"did you mean Pump_Run?"*). If the request names a tag and the logic uses a look-alike in its place (`Flow_SP` for `Flow_Setpoint`), the model is sent back; if it still does it on its last attempt, the row **fails** instead of building with the wrong tag.

Improve results without fine-tuning by adding examples in your plant's wording to `generate/examples.yaml`. The most similar ones are shown to the model for each request.

To compare models by measurement, see [DEVELOPMENT.md](DEVELOPMENT.md#comparing-models).

## The app

Three pages, light and dark. Every rung, generated, pasted or read from your file, is drawn as a **ladder diagram** (rails, contacts, coils, instruction boxes with their operands, branches) next to its plain-English read-back. Press the help button in the header for what it can do; the list button next to **Send** shows examples and project commands.

- **Chat** (`/`)
  - **Plain English → ladder** (needs a model). Read-back, the rungs drawn as ladder, their text, tags, checks. **Copy** gives the rung text in the form chosen in Settings (neutral or ASCII); **Download** gives `Routine.L5X` or `Rung.L5X`, also chosen in Settings.
  - **Paste rungs** in either form: neutral `XIC(a)[XIC(b) ,XIO(c) ]OTE(d);` (as in L5X) or ASCII `XIC a BST XIC b NXB XIO c BND OTE d` (one rung per line; `SOR … EOR` accepted). You get the ladder, what each rung does in English, the checks and **Download**.
  - **Attach an `.L5X`** (controller, program, routine or rung export; button or drag-and-drop). New logic then uses your real tags, AOIs and version. Commands: `summary`, `decompile` (every rung in English), `validate`, `optimize`, `xref TagName`.
  - LogicSpec, the language the model writes, is not shown. Typing it still works, for testing.
  - **Logic | UDT** switch in the input box. In UDT mode you create data types (below).
- **Settings** (`/settings`): model (backend, address, model, thinking, context window), output (rung text form, download type, names, version, tag scope), Advanced (timer operand style, helper tag prefix, rung comments). Saved in the browser as you change them.
- **Lint** (`/lint`; `/rules` still works): the 50 lint rules, grouped, with search and severity filter; switch each on or off.

## UDTs: create and optimize

Switch the input box to **UDT**.

| Input | Uses the model | Output |
|---|---|---|
| Plain English: *"a motor with running and faulted bits, speed in rpm and 32 alarm bits"* | yes | `Name.L5X`, or `UDTs.zip` for several |
| The UDT text form (`UDT Name "desc";` then `Member TYPE[n] "desc";` lines) | no | same |
| An Excel sheet (`.xlsx`, sample in the examples list in UDT mode: one row per member, blank UDT cell = same UDT as above) | no | same |
| An attached UDT export, or a program, then **optimize UDTs** | no | `Name_opt.L5X`, a zip of them, or the whole program |

- New UDTs are checked (names, types, BOOL arrays in multiples of 32, nesting loops, names already in the attached project) and written in the order that wastes no memory: BOOLs packed into hidden SINT hosts the way Studio 5000 names them, then members by alignment. The model writes only the UDT text form, under a grammar on llama.cpp; a failed check goes back to it, as for rungs.
- **Optimize** reorders members only. Every member's XML (descriptions, radix, external access, CDATA) is kept byte for byte; only BIT positions change. It shows per UDT the bytes now → after, instances (nested ones included) and the total saved, and flags what depends on byte offsets: COP/CPS, MSG local elements, produced/consumed tags. Only UDTs that save bytes and have no such risk are ticked.
- The **whole-program** file also has to move tag values: each tag value is stored twice, by member name (Decorated) and by position (L5K). For affected tags the L5K copy is removed and the Decorated copy kept. UDTs used inside an AOI, or with a tag that has only L5K values, are left out, and the download says so. **Not yet confirmed by an import test: test it on a copy before you rely on it.**
- Sizes are computed from the layout rules, not read from Studio 5000. A UDT can only be changed offline.

This replaces two archived repos: [LLM4UDT](https://github.com/AnythingOT/LLM4UDT) (UDTs from English, L5X and CSV/Excel) and [L5X_UDTOptimizer](https://github.com/AnythingOT/L5X_UDTOptimizer). The optimizer here gives the same orders and sizes as L5X_UDTOptimizer on its samples.

## Requirements Excel to ladder

Attach an `.xlsx` where **each sheet is one routine** (the sheet name becomes the routine name) and **each row one requirement**:

| Rung | Req ID | Requirement | Rung comment | Rung text |
|---|---|---|---|---|
| 1 | R1 | Start the pump with the start button and keep it running until the stop button is pressed or the pump faults. | | |
| 2 | R1 | Turn on the pump running lamp while the pump runs. | Running lamp | |
| 5 | INFRA | | Hand-written | `XIC(Pump_Run)XIO(Pump_Fault)OTE(Pump_Healthy);` |

- **Requirement** goes to the model, like the chat box. **Rung text** (neutral or ASCII), when filled, is used as written and the model is not asked. **Rung comment** empty = the requirement becomes the rung comment. **Rung** is your row reference for the report. **Req ID** (optional) links the row to the requirement(s) it implements: `R1`, or `R1, R3`; several rows may share one ID, and `INFRA` marks a row that serves no requirement on its own (I/O mapping, first scan). The IDs go into the rung comment, so Studio 5000 shows them, and Report.txt ends with a **Traceability** section: one verdict per requirement (*passes test*, *FAILS TEST*, *built, not tested*, *NOT BUILT*; one bad rung fails the whole requirement) and a warning listing rows that trace to none. Header names are matched loosely (*Description*, *Functional description*, *No.* ...).
- Rows run one by one in the background; each appears drawn as it finishes, and **Stop after this row** keeps what is done. Tags created by a row are known to the rows below it. A row that fails (no valid logic, a tag type clash, an import error) is reported and left out; the rest still build.
- The run keeps going if you open another page (Rules, Settings, Energise); come back to the chat and it shows again, rows so far first. A question to the model cannot be picked up again, so leaving while one is on its way asks first.
- Output: `SheetName.L5X` (Import Routine), or `Routines.zip` with one routine per sheet and `Report.txt`. The rung rules run on each whole routine, so a timer used by two rows is caught.
- Sample: *Requirements Excel sample* in the examples list (next to Send). Attach your project first so the rows use its tag names.
- **As a test:** add an **Expected rung** column. Each built row is then run against it in the scan simulator and marked *Behaves as expected* or *Differs*, with the reason; the summary and `Report.txt` give a score per routine. A different but equivalent rung counts as right; a row that isn't built counts as wrong. A ready-made test workbook: [DEVELOPMENT.md](DEVELOPMENT.md#test-workbook).

## Validate: import checks and rules

`validate` (GUI, or `python cli.py validate plant.L5X`) runs two layers:

1. **Import checks** (`core/validator.py`): will Studio 5000 accept it. Syntax, operand count and types, tags that exist, instruction names for the target version (GRT before v36, GT from v36).
2. **Rules** (`lint/`): 50 programming rules with fixed codes. The prefix is the severity: **CRT** critical, **ERR** error, **WAR** warning, **INF** info. A rule can be switched off (Lint page, or `--disable INF004,INF003`), never softened, so a code always means the same thing.
   - 19 *rung* rules (duplicate OTE, reused timer or one-shot, unguarded division, unchecked array index, writes to status bits ...) also check every generated or pasted rung. Two of them, a reused timer and a reused one-shot, send the model back for another attempt.
   - 30 *project* rules (fault handlers, task watchdogs and names, uncalled routines, unscheduled programs, I/O mapping and comments, aliases, electronic keying, module lifecycle, UDT padding and order, descriptions ...) need a full controller export; on a partial export only the rung rules run, and the report says so.
   - Accept one case by writing `lint:disable=ERR010` (or `lint:disable` for all rules) in that rung's comment or that tag's or AOI's description. Suppressed findings are listed separately, never dropped.
   - Rules that an export cannot answer (no MajorFaultProgram attribute, say) are reported as *not verified*, not as passed. A rule that crashes is reported too.
   - Module lifecycle uses `lint/lifecycle.json`: seed data from public Rockwell discontinuation notices, dated in its `_meta`. Check it against Rockwell's PCDC before buying anything, and edit the file to add your modules.

`python cli.py validate --rules` lists the rules. The rules are a rewrite, for this repo's parser and data model, of the checklist in [L5X_Lint](https://github.com/AnythingOT/L5X_Lint), with the same codes.

### Fix: where the fix is certain

`python cli.py fix plant.L5X` proposes fixes for six rules and writes `plant_fixed.L5X` next to the file (never over it):

| Rule | Fix | Kind |
|---|---|---|
| WAR006 empty rung | deleted; a rung with a comment (a heading) keeps it and gets a `NOP()` | safe |
| ERR010 the same condition twice in series, identical legs of conditions | the repeat removed | safe |
| INF001 unused tag with External Access None | deleted | safe |
| INF001 unused tag an HMI, SCADA or another controller could read | deleted, one question for all of them | changes |
| ERR012 DIV or MOD by a tag nothing compares with 0 | `NEQ(divisor,0)` before it | changes |
| ERR015 one storage bit shared by several one-shots | each one-shot after the first gets its own bit | changes |
| WAR008 timer or counter preset 0, set by nothing | the preset you type, written into the tag | changes |

- **Safe** means the program behaves exactly as before: a rung fix is run in the scan simulator before and after, and offered as safe only if nothing differs. If the simulator cannot run that routine, the fix is offered as one that may change behaviour, with the reason. All safe fixes come as one batch, one question.
- **Changes** fixes are asked one by one, each with what behaves differently afterwards.
- `--safe` applies the safe batch and asks nothing; `-o` names the output file.
- Everything a fix does not touch is the same XML afterwards. The lint runs again at the end and lists what is still open.
- Not fixed here, because the right fix depends on intent: several latches or unlatches, a timer used twice, a counter never reset, an empty branch leg, AFI, safety tags, REAL to integer moves, backward jumps.

## Neutral text and ASCII text

| | Neutral | ASCII |
|---|---|---|
| Example | `XIC(a)[XIC(b) ,XIO(c) ]OTE(d);` | `XIC a BST XIC b NXB XIO c BND OTE d` |
| Branches | `[` `,` `]` | `BST` `NXB` `BND` |
| In L5X files | **yes, always** | never |

LLM4L5X always writes neutral text into L5X. Generated rungs are also shown as ASCII, so you can paste a single rung into the editor's ASCII mode. Reading ASCII needs each instruction's operand count, so Add-On Instructions are only understood when the project defining them is attached. An operand containing spaces (e.g. a `CPT` expression) is written in double quotes; whether the editor expects exactly that is **unverified**.

## LogicSpec

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

Full reference and design: [DESIGN.md](DESIGN.md).

## Command line

Run from the repo folder with the app's Python, the one `start.bat` set up (`start.sh`:
`~/.local/share/llm4l5x/venv`). Once per command window:
```
"%LOCALAPPDATA%\LLM4L5X\venv\Scripts\activate"
```
then:
```
python cli.py compile examples\pump_station.spec -o pump.L5X
python cli.py compile spec.txt --routine Generated --project plant.L5X --program MainProgram -o r.L5X
python cli.py inspect plant.L5X --decompile
python cli.py inspect plant.L5X --xref Pump
python cli.py validate plant.L5X --disable INF003,INF004
python cli.py validate --rules
python cli.py fix plant.L5X              # safe fixes in one batch, the others one by one
python cli.py survey folder_of_exports
python cli.py ask "run the pump from start, stop with stop" --project plant.L5X --model phi4-mini -o pump.L5X
python cli.py eval --model qwen3.6:35b-a3b --no-think
python cli.py suite --backend llamacpp --per 1 --excel suite_llamacpp.xlsx   # grammar-constrained
python cli.py rung "XIC(a)[XIC(b) ,XIO(c) ]OTE(d);"
python cli.py rung "XIC a BST XIC b NXB XIO c BND OTE d"
```

## Energize: run the whole program before any controller

**Energize** (top bar) loads L5X routines, a project export or the `Routines.zip` from a requirements run.
The program stays loaded: leave the page (or use Tests) and come back, and it is as you left it (Run
pauses while you are away). Outputs that need an answer from the machine get it from the device models on
the **Tests** page.

The page reads left to right like a rung: **inputs**, the **rungs**, **outputs**.

- Every routine runs once per scan with `Sim_Mode = 1`. MAP_IN and MAP_OUT are not run (the plant
  gives the feedback, field outputs stay off), and rungs that only call a subroutine are skipped
  (listed under **Not run in simulation**).
- An instruction the simulator does not have (PID, MSG ...) stops the load with a list: skipping it
  would make the program look like it works.
- **Inputs:** a bit is a switch; a number is a field (type it, press Enter). The tag's data type decides;
  a tag the files do not declare is a bit if the logic uses it as a contact or coil.
- **Rungs** are drawn as ladder diagrams, as Logix Designer shows them online, from the simulator's own
  trace of each scan: a wire is green and moving up to where power stops (a dashed green line in the
  key), the left rail (the supply) is always green, a true contact and a coil that is on are drawn in green,
  and a coil that is on glows. A rung that is true has a green right rail and number. Timer and counter
  boxes show their accumulator live instead of `?`. With "reduce motion" set in the system, nothing moves.
- Long tag names are shortened in the middle (`BUG01_SFT…UP_LIMIT_LF`), so the end that tells them apart
  stays; the full name is in the tooltip.
- **Outputs:** a bit is a lamp, a number its value. **Timers and counters** show the accumulator against
  the preset, with DN lit when done.
- Timers and counters take their preset from the tag's data, as the controller does: an export writes
  `TON(T,?,?)` in the rung, so the rung alone has no preset.
- **Run** advances in real time; **Step 100 ms** one step at a time; **Reset** starts again. Changes made
  while a step is under way are sent with the next one, never dropped.

## Tests: test cases, pass or fail per requirement

**Tests** (top bar) holds the test cases, next to the program Energize runs (load it on either page).

- **Test cases** set inputs, wait and expect outputs, each tied to a requirement ID. Format:
  [TESTCASES.md](TESTCASES.md) (the file format still says `SCENARIO`).
- **Load requirements**: the instruction sheet (the requirements workbook the program was built from).
  A requirement is a Req ID with the text of its rows; a row with no Req ID is a requirement of its own
  ("Pump row 6"); INFRA rows serve none. Without it, the requirements are the Req IDs the rungs and test
  cases name.
- **Save** checks the test cases and keeps them; **Run tests** saves what is on the screen, runs every test
  case on a fresh copy of the program, and shows:
  - the **traceability matrix**: each requirement, its rungs (a generated rung carries its Req IDs in its
    comment, `[R1, R3] ...`), its test cases and the result: Pass, Fail, No test, Not built;
  - the **gaps**: requirements with no test case or no rung, Req IDs the workbook does not have, test cases
    tied to no requirement, rungs that serve no requirement;
  - each test case, and why a failed one failed.
- **Evidence**: every run is kept as a record in the `runs` folder, one file each, never changed: every
  step with what was expected and what was read and when, and the SHA-256 of every input (program files,
  requirements, device models, test cases) and of the tool's own code. Two runs on different inputs never
  look the same.
- **Download report (PDF)**: made from the record; marked "no changes" for PDF readers, and every page prints
  the record's SHA-256, so a report can be checked against its record. **Record (JSON)** is the record
  itself. Earlier runs are listed with their reports.
- What a report is: evidence from the scan simulator on this PC, not a test of the controller, and not a
  validated record under any regulation. It says so on its first page.
- The live Energize session is not touched by a run.
- Outputs that need an answer from the machine get it from the device models (next section).
- Text not saved yet is kept if you leave the page, and shown again when you come back.

## Device models

**Devices** (top bar) holds the device models: stand-ins for the machine. A pump's running contact closes
a second after it is commanded; a valve's limit switches follow its solenoids. Format: [DEVICES.md](DEVICES.md).

- **Save** checks them, keeps them, and the loaded program answers with them at once; Energize and Tests
  both use them.
- **What each device does** lists, from the saved models, the PLC output each device reads, the PLC input
  it answers, and how long it takes: check it against the I/O list before trusting a test.
