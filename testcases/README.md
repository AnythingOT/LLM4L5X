# testcases/

Test cases: requirement-level checks run against the program and its device models, with a traceable record and a PDF report.

| | |
|---|---|
| Page | Tests (`/tests`) |
| Command line | none |
| In | test cases in the step language (`SCENARIO`, `SET`, `WAIT`, `EXPECT`), requirements from the workbook |
| Out | pass or fail per step and per requirement; a run record (JSON) and a PDF that cannot be edited |
| May import | `core`, `l5x`, `generate` (to read the requirements workbook) |
| Docs | [docs/TESTCASES.md](../docs/TESTCASES.md) |
| Tests | `tests/test_testcases.py`, `test_evidence.py` |

## Rules

- The file format keeps the keyword `SCENARIO`. The folder carries the page's name.
- A run record holds fingerprints (SHA-256) of the program, the test cases and the code. The PDF is
  made from the record and nothing else.
- The report makes no regulatory claim.
- `backend.py` runs test cases on our simulator; `emulate.py` runs them on Logix Emulate or a controller
  through pylogix (installed separately), in real time.
