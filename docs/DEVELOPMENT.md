# Development

## Repo layout

```
app.py              starts the GUI (python app.py)
cli.py              command line (python cli.py ...)
core/               catalog.py + instructions.yaml (124 instructions), rung.py, ascii.py, logicspec.py,
                    compiler.py, validator.py, simulator.py
l5x/                reader.py, writer.py, xref.py
lint/               rules.py (the 50-rule checklist), checks_*.py, context.py, paths.py, lifecycle.json
udt/                layout.py (sizes, alignment, best order), model.py (UDT text form, checks),
                    writer.py (DataType export), excel.py (sheet + template), optimize.py (reorder
                    an existing export, byte-preserving)
explain/            decompiler.py (rungs -> LogicSpec), describe.py (English), ladder.py (rungs -> SVG
                    ladder diagrams), survey.py
inputs/             llm.py (Ollama/llama.cpp, English -> LogicSpec), examples.yaml (few-shot), gbnf.py,
                    udt_llm.py (English -> UDT text form), spec_excel.py (requirements workbook)
eval/               requests.yaml + run.py (hand-written eval), suite.py + suite_run.py (generated
                    instruction suite), rung_compare.py (behavioural oracle), mutation.py
gui/                __init__.py (routes), state.py (attached file, settings), logic.py (rungs),
                    project.py (the attached L5X), udts.py, spec.py + jobs.py (requirements workbook
                    in the background); templates/ and static/ (pages, CSS, JS)
tests/              pytest (318 tests, plus 3 per file with a corpus); fixtures/ are hand-written, except studio_single_udt.L5X
                    (the public L5X_UDTOptimizer sample); test_corpus.py runs on a folder of exports
examples/  docs/
requirements.txt  ruff.toml  start.bat  start.sh
```

Run the tests with `pytest` from the repo folder, and `ruff check .` for the code checks.

## Tested on real exports

The parser was checked against 179 public L5X exports (3,160 rungs, including Rockwell's own samples):
**100% parse, 99.9% print back byte-for-byte, 99.9% survive neutral → ASCII → neutral**, and the timer format `TON(T,?,?)`, the timer
data layout and the AOI call format are all confirmed. Details are in [DESIGN.md](DESIGN.md), section 9.
Run the same check on your own exports:

```
python cli.py survey C:\path\to\your\exports
```

**Every feature, on every file:** `tests/test_corpus.py` attaches each export in a folder and runs summary,
explain, validate, every ladder drawing, the UDT plan and its downloads, and a write-and-read round trip
of every routine. The exports are never committed:

```
set LLM4L5X_CORPUS=C:\path\to\your\exports
pytest tests/test_corpus.py -q
```

Last run: 241 files (234 public exports from 16 GitHub repositories, plus every L5X in the AnythingOT
repositories), 723 checks, all passing. On the same files the rules agree with L5X_Lint rule for rule, except that INF007 also sees the
v36 `MOVE` (L5X_Lint missed it), and the UDT optimizer agrees with L5X_UDTOptimizer except where a nested
UDT shrinks (this repo carries the saving up to the parent; L5X_UDTOptimizer did not).

**Import verified:** generated Rung and Routine L5X files import cleanly into Studio 5000.
Still to confirm: a timer import keeps its preset.

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

## Comparing models

`python cli.py eval --model phi4-mini` scores a model on `eval/requests.yaml` by meaning (truth tables), not text.
Add your own requests there. To improve results without fine-tuning, add examples in your plant's wording to
`inputs/examples.yaml`: the most similar ones are shown to the model for each request.

## Test workbook

`python -m eval.test_workbook out.xlsx --seed 3 --rows 12 --corpus folder_of_exports` writes a requirements
workbook in which every row has an **Expected rung**. Attach it in the app to score the model (see the guide).

| Sheet | Rows |
|---|---|
| Series, Parallel, Nested, Multi_output | generated by `eval/suite.py`, every instruction family, no tag written by two rows |
| Referenced | three chains where later rows use what earlier rows made: a timer's `.DN`, a latched alarm and its reset, a counter and its reset, a total compared and acted on |
| Real_world | complex rungs (branches, or 4+ instructions) from the exports in `--corpus`, with LLM4L5X's own read-back as the requirement, so this sheet favours this tool's wording |

All sheets become routines of one program and share one tag table, so a tag is written on one sheet only:
a timer run from two routines would be one timer with two owners and two presets. A row that asks for a
different preset on a timer or counter made by an earlier row fails with that reason.

Every expected answer is checked when the file is written: the same logic in LogicSpec must compile and behave
like the Expected rung, and the app must be able to build it without a project. Array copies (COP) are left
out, because they need array tags from a project. With a model that always answers correctly, every row scores.
