# eval/

Measuring quality, for developers: the model's scores, the always-correct oracle run, the instruction suite, the public corpus, and this repository's map.

| | |
|---|---|
| Page | none |
| Command line | `python -m eval.oracle_run`, `python -m eval.structure`, `python -m eval.conformance`, `python -m eval.test_status`, `python cli.py eval`, `suite` |
| In | test workbooks, request lists, public L5X exports (fetched in CI, never committed) |
| Out | scores and reports |
| May import | anything. Nothing in the product may import `eval` |
| Docs | [docs/DEVELOPMENT.md](../docs/DEVELOPMENT.md) |
| Tests | `tests/test_oracle.py`, `test_suite.py`, `test_corpus*.py` |

## Rules

- After any change to a check, the oracle run must show `RETRIED 0`.
- `conformance.py` is the simulator's validation record: the same small programs on the simulator and on
  Logix Emulate, every recorded value compared. Its results, and `test_status.py`'s corpus numbers, go
  into `tests/TEST_STATUS.md`, never into the README.
- `corpus_sources.txt` lists only MIT- or Apache-licensed repositories, at pinned commits. Your own
  confidential exports never go there: CI logs are public.
