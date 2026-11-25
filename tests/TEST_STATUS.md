# Test status (internal)

Internal results only: what has been measured, how, and what has not been verified. Nothing here is a
release claim. A number goes here with its date and the command that produced it; a number nobody can
reproduce does not go here.

Last updated: 25 Nov 2026.

## Automated tests (every push, in CI)

| What | Result | How |
|---|---|---|
| Unit and integration tests | 3,183 passed on #61, with the public corpus | `pytest` in CI, Linux |
| Oracle run: every row of the test workbook answered by its expected rung | full marks, `RETRIED 0` | `python -m eval.oracle_run`, in CI |
| Code checks | clean | `ruff check .` |
| Windows | in CI from this change (tests without the corpus, conformance cases on the simulator); the app tried by one user | `windows-latest` |

## Public L5X corpus

<!-- CORPUS:BEGIN (python -m eval.test_status) -->
Measured 25 Nov 2026 with `python -m eval.test_status` on 858 exports (6,959 rungs), MIT/Apache repositories pinned in `eval/corpus_sources.txt`.

| What | Result |
|---|---|
| Files read | 858 of 858 |
| Rungs read (parsed) | 98.9% |
| Rungs explained in English | 54.7% |
| Ladder routines Energize can run whole | 74.3% (631 of 849) |
| Whole exports with ladder that Energize loads (every routine and JSR target must run) | 38.3% (69 of 180) |
| Catalog instructions the simulator has | 41 of 124, plus JSR and readable AOI logic |
| Most common instructions it lacks (rungs) | CONCAT (162), RTOS (153), ALMD (27), MSG (26), GSV (25), FOR (18), OP_PERMISSIVE (18), NXT (16), PF525_VFD_E_ENET (16), PID (10) |
<!-- CORPUS:END -->

## The model (generation)

| What | Result | Notes |
|---|---|---|
| Instruction suite, Qwen3.6-35B-A3B Q4_K_M, llama.cpp, CPU | 238 of 240 (earlier seeds: 226/240, 114/120) | Requests generated from templates that name every tag exactly; 24 instructions; scored by behaviour in the simulator |
| Requests in an engineer's own wording | **not measured** | needs 20-50 real requests in `eval/requests.yaml` |
| Smaller models | **not measured** | |
| Time per request | about 12 s | CPU only, 64 GB RAM |

## Studio 5000

| What | Status |
|---|---|
| Generated rungs and routines import | verified by hand |
| UDTs from Excel, routines from a requirements Excel import | verified by hand |
| A timer keeps its preset after import | **not verified** |
| Tag values survive a whole-program UDT reorder | **not verified** (test on a copy) |

## The simulator against a real controller

| What | Status |
|---|---|
| Conformance with Logix Emulate: 12 cases (bits, latches, edges, TON, TOF, RTO, counters, compare, math, CPT, CMP, branches) | **not run yet** (`python -m eval.conformance`, steps in its docstring) |
| JSR, AOI logic | in the simulator; not in the conformance cases yet (they need a second routine and an AOI definition in the import) |

Until the conformance run is done, a passing test or Energize run means "right in our simulator", not
"right on the controller". Each difference it finds is either fixed in the simulator or listed here as a limit.
