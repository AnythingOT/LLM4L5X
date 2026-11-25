# explain/

From existing logic to words and pictures: rungs back to LogicSpec, and ladder drawings.

| | |
|---|---|
| Page | Chat: *explain all rungs*, every ladder drawing; Energize draws with it too |
| Command line | `python cli.py inspect --decompile`, `survey` |
| In | parsed rungs (from `l5x` or pasted text) |
| Out | LogicSpec, English, SVG ladder |
| May import | `core`, `l5x` |
| Docs | [docs/GUIDE.md](../docs/GUIDE.md) |
| Tests | `tests/test_decompiler.py`, `test_ladder.py` |

## Rules

- The SVG is built and escaped here. Pages insert it as it is and style it with CSS (`lad-*` classes).
