# Handover

Read this first, then `docs/ROADMAP.md` for what is next. Written 24 Nov 2026, after PR #51.

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
| `generate/llm/` | model clients (local only unless allowed), prompt, tag-name helpers, **output checks** that send an answer back, the retry loop |
| `generate/spec_excel.py` | requirements workbook: one sheet = one routine, Req ID column, Expected rung column |
| `generate/iolist.py` | I/O list reader, device detection, proposed plant file, **MAP_IN / MAP_OUT** with Sim_Mode |
| `core/` | LogicSpec, compiler, plain-English read-back, validator, rung parser, **scan simulator** (time-based, records rung power), rung_compare (behaviour oracle), UDT layout |
| `l5x/` | L5X reader (size cap, no entities) and writer |
| `lint/` | 50 rules (CRT/ERR/WAR/INF) plus the company **profile** (STD001-STD004) |
| `devices/` | **device models** (the Devices page; the YAML still says `PLANT:`): motor/pump and 2-position valve, fault injection through `PLANT:` tags |
| `testcases/` | **test cases** (the Tests page; the file format still says `SCENARIO`): OpenVnV step language (SET/EXPECT/WAIT/RESET/COMMENT/CALL), runner, traceability |
| `library/` | blocks (Motor, Valve2Pos, AlarmLatch): rungs + tags + plant + scenarios from one file |
| `gui/` | Flask app on 127.0.0.1: chat, requirements jobs, **Lint** (was Rules), Settings, **Energize** (run the program live), **Tests** (test cases), **Devices** (device models) |
| `eval/` | expected-rung workbook, **oracle_run** (always-correct stand-in), suites, mutation, `structure.py` (makes STRUCTURE.txt) |
| `explain/` | ladder SVG, decompiler (rung → LogicSpec) |

Each folder has a README.md; [STRUCTURE.txt](../STRUCTURE.txt) lists every file. Docs per area: GUIDE (users), DEVELOPMENT, DESIGN, IOLIST, DEVICES, TESTCASES, LIBRARY, PROFILE.

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
  calling it done: API tests passed while the Energize page was completely broken.
- **The owner tests only new features**, not features already tested. Ask for a laptop run only when
  something new needs the real model, and say exactly what to run.

## Confidentiality

- There is a list of **confidential names** from the owner's employer. **Never write them** in code,
  tests, docs, commits, PR text or chat. The list lives only in the repository secret
  `CONFIDENTIAL_PATTERN`; CI fails if any tracked file matches (it prints file names only).
- The test fixture of the separate L5X_Lint repo contains one of those names: never copy it here.
- Corpus and Real_world test rows come **only from public GitHub L5X exports**, never company exports
  (`LLM4L5X_CORPUS` points at a folder of them; the corpus test skips without it). CI fetches the public
  set pinned in `eval/corpus_sources.txt` and runs it on every push; add a repository there only if its
  LICENSE is MIT or Apache and it is not an AnythingOT repository (only the L5X_Lint fixture is known to
  hold a confidential name, but CI logs are public, so all AnythingOT repositories stay off the list).
- Company libraries and profiles stay outside this repo.

## How results are measured

- **Test workbooks** (`python -m eval.expected_workbook OUT.xlsx --seed N --corpus FOLDER`): sheets of
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
| level 1, seed 41, 3 rows (fresh holdout) | 24/27 | three misses the checks let through: a no-op write, a swapped copy, an invented output. Fixed in #46; **spent** |

Not measured yet: the #46 checks on a fresh holdout (level 2, a seed never run with the model, e.g. 53).

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
  instructions stop Energize; the CI name check fails without its secret; a remote model server is
  refused unless allowed, and a banner shows while it is.
- **Sim_Mode**: logic uses mapped tags only; MAP_IN is skipped by its JSR (an OTE behind
  `XIO(Sim_Mode)` would write 0 every scan); MAP_OUT forces field outputs off in simulation.
- A profile adds rules and switches rules off but **cannot change a severity**.
- Blocks are **self-tested when loaded** and carry negative tests.
- v36+ mnemonics (`MOVE`, `LE`, `GT`) are emitted for v36+ revisions; the simulator maps them.
- **Timer and counter presets live in the tag's data** (an export writes `TON(T,?,?)`); Energize reads them
  from there (#48). A `MOV(preset, T.PRE)` rung is a **profile option**, off by default: it keeps the preset
  in the logic but stops HMI and online changes.
- **Who writes test cases**: rules first (standard test cases per block from the library), then the model
  drafts from the **requirement text only**, never from the generated rungs or LogicSpec (the same misreading
  would pass its own test: seed 41's swapped copy), then the engineer approves. Only the runner decides
  pass or fail.
- **Lint auto-fix**: every fix is checked in the simulator. Fixes that keep behaviour go in one batch with
  one y/n; fixes that change behaviour get their own y/n and say what changes; some are never automatic
  (ROADMAP item 1 has the list).
- **Hardware testing** goes through **pylogix against Logix Emulate** (the owner has Emulate; pylogix does
  not depend on its version), with the same test cases as the simulator.
- **Names**: Energize (manual console), Tests page, Device models, Test cases. Old `/energise` redirects.
- **One repository** (Nov 2026): lint, UDT tools and the generator stay here; split into packages only when
  a real need comes. L5X_Lint (still public) duplicates the rules; changes are made here.
- **Test evidence** (#57): requirements come from the instruction sheet; a run record is written once to
  `runs/` with SHA-256 of every input and of the tool's code; the PDF report is made from the record only,
  marked no-modify, with the record's SHA-256 on every page. No regulation (21 CFR 11, EN 50128): an
  open-source tool does not claim it unless someone pays for that work.

## Lessons

- Test data has bugs too: run the expected answer through our own lint (the SimpleBool row).
- Saturated tests show nothing; refresh the holdout when scores hit the ceiling.
- Count retries, not just passes: a pass on the third try is the first to fail on drift.
- A fix that never fired in a run is untested, whatever the score did.
- Tests at one layer cannot see the layer above (import vs Verify, simulator vs controller, API vs page).
- A new test proves something only if it fails on the old code: break the fix on purpose and watch it fail.
- Green CI can mean "skipped": check the test count (the corpus tests skipped in CI until #45).
- A message shown in a part of the page that gets hidden is no message (Energize errors, #49).
- Two checks from the same source fail together (common-mode failure): tests must not be derived from
  the code they test.
