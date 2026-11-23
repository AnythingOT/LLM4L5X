# Handover

Read this first, then `docs/ROADMAP.md` for what is next. Written 24 Nov 2026, after PR #39.

## What the tool is

LLM4L5X turns requirements into Studio 5000 ladder (L5X), offline, with a local model. It is a
**drafting tool for engineers**, not a replacement: it shortens the first layer (writing and checking
logic), before software-in-the-loop, hardware-in-the-loop and site testing, which stay as they are.

The design has **two steps**, kept apart on purpose:
1. **Operations text → instruction rows** (design: which signals, latches, timers). *Not built yet*;
   the engineer writes the rows today. Planned as a draft with questions and visible assumptions.
2. **Instruction rows → ladder** (translation). Built and measured: the model writes LogicSpec under
   a grammar; deterministic code compiles, validates, lints and simulates it.

## Map of the code

| package | owns |
|---|---|
| `inputs/llm/` | model clients (local only unless allowed), prompt, tag-name helpers, **output checks** that send an answer back, the retry loop |
| `inputs/spec_excel.py` | requirements workbook: one sheet = one routine, Req ID column, Expected rung column |
| `inputs/iolist.py` | I/O list reader, device detection, proposed plant file, **MAP_IN / MAP_OUT** with Sim_Mode |
| `core/` | LogicSpec, compiler, validator, rung parser, **scan simulator** (time-based, records rung power) |
| `l5x/` | L5X reader (size cap, no entities) and writer |
| `lint/` | 50 rules (CRT/ERR/WAR/INF) plus the company **profile** (STD001-STD004) |
| `plant/` | motor/pump and 2-position valve models, fault injection through `PLANT:` tags |
| `scenario/` | OpenVnV step language (SET/EXPECT/WAIT/RESET/COMMENT/CALL), runner, traceability |
| `library/` | blocks (Motor, Valve2Pos, AlarmLatch): rungs + tags + plant + scenarios from one file |
| `gui/` | Flask app on 127.0.0.1: chat, requirements jobs, Rules, Settings, **Energise** |
| `eval/` | test workbook generator, **oracle_run** (always-correct stand-in), suites, mutation |
| `explain/` | ladder SVG, decompiler (rung → LogicSpec), plain-English read-back |

Docs per area: GUIDE (users), DEVELOPMENT, DESIGN, IOLIST, PLANT, SCENARIOS, LIBRARY, PROFILE.

## Working rules with the owner

- **Small PRs, each branched from main, never stacked.** A stacked PR is closed when its base branch
  is deleted (that happened to #29). Wait for the merge before building on a PR.
- The owner reviews and merges (merge commits) and deletes branches. Never commit to main.
- Every PR: `python -m pytest -q` and `ruff check .` green, CI green, tests for new behaviour.
- Commit messages end with the Co-Authored-By and Claude-Session trailers given by the session.
- The owner runs the real model on the laptop (`D:\LLM\LLM4L5X`, a downloaded copy without git;
  Qwen on llama.cpp). Do not drive the laptop unless asked: it costs usage. The owner sends back
  `Routines_N.zip` (L5X files + Report.txt) to analyse.
- Run a UI change in a real browser (headless Chrome is available in the cloud workspace) before
  calling it done: API tests passed while the Energise page was completely broken.

## Confidentiality

- There is a list of **confidential names** from the owner's employer. **Never write them** in code,
  tests, docs, commits, PR text or chat. The list lives only in the repository secret
  `CONFIDENTIAL_PATTERN`; CI fails if any tracked file matches (it prints file names only).
- The test fixture of the separate L5X_Lint repo contains one of those names: never copy it here.
- Corpus and Real_world test rows come **only from public GitHub L5X exports**, never company exports
  (`LLM4L5X_CORPUS` points at a folder of them; the corpus test skips without it).
- Company libraries and profiles stay outside this repo.

## How results are measured

- **Test workbooks** (`python -m eval.test_workbook OUT.xlsx --seed N --corpus FOLDER`): sheets of
  generated requests with expected rungs; the report scores behaviour in the simulator, not text.
  Tune on one seed, keep another as **holdout**, run it once; a holdout used for diagnosis is spent.
- **Oracle run** (`python -m eval.oracle_run WORKBOOK`): every answer correct by construction;
  must show RETRIED 0 after any change to checks, compiler or simulator. CI runs a small one.
- Report.txt shows attempts per row and a Traceability section when the Req ID column is used.

Latest real-model results (Qwen, laptop):

| workbook | score | note |
|---|---|---|
| level 1, seed 3 v3 / holdout seed 7 v3 | 71/71 / 71/71 | saturated: regression checks now, not progress |
| level 2, seed 11 (tuning) | 71/71 | after the three output checks (#24) |
| level 2, seed 17 | 64/71 | led to the RESET_ACC fix (#25); now spent as a holdout |
| level 2, seed 23 (fresh holdout) | 70/71 | only miss: model used `Flow_SP` for the named `Flow_Setpoint` |

Studio 5000 accepted an import of generated routines (owner, Nov 2026); the version and the Verify
result were not recorded. Level 2 (`--level 2`) is on main since the near-twin names were removed from
its name pool, so a level-2 seed now gives other rows than the workbooks above: their scores do not compare
by seed, and the next holdout needs a seed never run with the model.

## Decisions worth keeping (and why)

- The model writes **only LogicSpec**, under a GBNF grammar; code does everything after. Checks that
  fail send the answer back with the reason; on the last attempt they only warn.
- **A fallback that makes output compile is a hidden error**: RESET_ACC on a tag that is no timer or
  counter is refused (it once turned three tags into COUNTERs and broke a fourth row).
- **Fail loudly**: unknown tags stop a scenario (a typo would pass a negative test); unsupported
  instructions stop Energise; the CI name check fails without its secret; a remote model server is
  refused unless allowed, and a banner shows while it is.
- **Sim_Mode**: logic uses mapped tags only; MAP_IN is skipped by its JSR (an OTE behind
  `XIO(Sim_Mode)` would write 0 every scan); MAP_OUT forces field outputs off in simulation.
- A profile adds rules and switches rules off but **cannot change a severity**.
- Blocks are **self-tested when loaded** and carry negative tests.
- v36+ mnemonics (`MOVE`, `LE`, `GT`) are emitted for v36+ revisions; the simulator maps them.

## Lessons

- Test data has bugs too: run the expected answer through our own lint (the SimpleBool row).
- Saturated tests show nothing; refresh the holdout when scores hit the ceiling.
- Count retries, not just passes: a pass on the third try is the first to fail on drift.
- A fix that never fired in a run is untested, whatever the score did.
- Tests at one layer cannot see the layer above (import vs Verify, simulator vs controller, API vs page).
