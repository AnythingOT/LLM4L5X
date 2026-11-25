# Test status (internal)

Internal results only: what has been measured, how, and what has not been verified. Nothing here is a
release claim. A number goes here with its date and the command that produced it; a number nobody can
reproduce does not go here.

Last updated: 25 Nov 2026.

## Automated tests (every push, in CI)

| What | Result | How |
|---|---|---|
| Unit and integration tests | 3,183 passed (#61, with the public corpus) | `pytest` in CI, Linux |
| Oracle run: every row of the test workbook answered by its expected rung | full marks, `RETRIED 0` | `python -m eval.oracle_run`, in CI |
| Code checks | clean | `ruff check .` |
| Windows | not in CI; tried by one user | |

## Public L5X corpus (858 exports, 6,959 rungs, MIT/Apache repositories)

Measured 25 Nov 2026 on `eval/corpus_sources.txt` at its pinned commits.

| What | Result |
|---|---|
| Files read | 858 of 858 |
| Rungs read (parsed) | 98.9% |
| Rungs explained in English | 55% |
| Ladder routines Energize can run whole | 49% (416 of 849) |
| Instructions the simulator has | 36 of the 124 in the catalog |
| Most common instructions it lacks | CONCAT, RTOS, CPT, AOI calls, ALMD, MSG, GSV, FOR, CMP, OSR |

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
| Instruction-by-instruction comparison with Logix Emulate | **not run yet** |

Until this is run, a passing test or Energize run means "right in our simulator", not "right on the controller".
