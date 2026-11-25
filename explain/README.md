# explain/

From existing logic to words and pictures: rungs back to LogicSpec, ladder drawings, rung comments.

| | |
|---|---|
| Page | Chat: *explain all rungs*, every ladder drawing; Energize draws with it too |
| Command line | `python cli.py inspect --decompile`, `survey` |
| In | parsed rungs (from `l5x` or pasted text) |
| Out | LogicSpec, English, SVG ladder, an L5X with the missing rung comments added |
| May import | `core`, `l5x` |
| Docs | [docs/GUIDE.md](../docs/GUIDE.md) |
| Tests | `tests/test_decompiler.py`, `test_ladder.py`, `test_rung_comments.py` |

## Rules

- `comments.py` adds a comment only where a rung has none. Each one starts `AUTO:`, and the file is edited
  in place, not rebuilt.
- The SVG is built and escaped here. Pages insert it as it is and style it with CSS (`lad-*` classes).
