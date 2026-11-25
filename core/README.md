# core/

The engine everything else stands on: LogicSpec, the compiler, rung text, the scan simulator, UDT memory layout.

| | |
|---|---|
| Page | none: used by every page |
| Command line | `python cli.py compile`, `explain`, `rung` |
| In | LogicSpec text, rung text (neutral or ASCII) |
| Out | rungs, English read-back, scan results |
| May import | nothing in this repository |
| Docs | [docs/DESIGN.md](../docs/DESIGN.md) |
| Tests | `tests/test_compiler.py`, `test_rung*.py`, `test_simulator.py`, `test_udt.py` |

## Rules that keep it the base

- No model, no Flask, no files: plain functions on plain data. Same input, same output.
- `rung_compare.py` (do two sets of rungs behave the same) is here because Lint's auto-fix and the
  requirements workbook use it in the product, not only in evaluation.
- `instructions.yaml` is the instruction catalog. An attached project's AOIs extend it at run time.
