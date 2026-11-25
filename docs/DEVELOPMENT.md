# Development

## Repo layout

[STRUCTURE.txt](../STRUCTURE.txt) lists every folder and file with one line each. It is made from the
folders' README.md and the files' docstrings by `python -m eval.structure`, and `tests/test_structure.py`
fails when it is out of date, so it cannot drift from the code. Each folder's README.md says what it owns,
which page and command use it, and which folders it may import.

Folders carry the names of the pages: `devices/` (Devices), `testcases/` (Tests; `tests/` is pytest),
`lint/` (Lint), `generate/` (from English or Excel to logic). Dependencies point one way only:

```
core  <-  l5x  <-  explain, lint  <-  udt  <-  generate  <-  testcases  <-  library
devices (stands alone)          gui: uses them all, the only folder with Flask
eval: developers' measuring; uses anything, used by nothing in the product
```

`tests/test_structure.py` holds the exact table of which folder may import which. A new import across
folders is a design decision: change the table in the same PR and say why.

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
of every routine. The exports are never committed.

**CI runs it on every push** over public exports: `eval/corpus_sources.txt` pins 31 MIT- or Apache-licensed
GitHub repositories at a commit, and `python -m eval.fetch_corpus FOLDER` fetches only their .L5X files
(858 distinct files, about 77 MB; CI caches them until the list changes). Repositories with no licence, GPL
or "All rights reserved", and the AnythingOT repositories (one holds a confidential name, and CI logs are
public), are not on the list. Files broken on purpose, such as another tool's adversarial fixtures, are
excluded by a glob on their line. To run the same set, or your own folder:

```
python -m eval.fetch_corpus corpus
set LLM4L5X_CORPUS=corpus
pytest tests/test_corpus.py -q
```

CI run on the pinned list (Nov 2026): 858 files, 2574 checks, all passing.

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
`generate/examples.yaml`: the most similar ones are shown to the model for each request.

## Test workbook

`python -m eval.expected_workbook out.xlsx --seed 3 --rows 12 --level 1 --corpus folder_of_exports` writes a
requirements workbook in which every row has an **Expected rung**. Attach it in the app to score the model (see the guide).

`--level 2` keeps the same sheets with bigger rungs for when level 1 scores full marks: 4-5 condition series,
3-4 leg branches with 1-2 more conditions, two-group nests, 3-4 outputs (about 5.5 instructions a row against
3.8). It adds extra tag names (`MORE` in `eval/suite.py`); none may mean the same as a name already used, or
the model takes the near-twin for the named tag (`Flow_SP` for `Flow_Setpoint`) and the workbook, not the
model, fails the row.

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
