# l5x/

Read and write Studio 5000 L5X files: the only place that knows the XML.

| | |
|---|---|
| Page | none: used when a file is attached or downloaded |
| Command line | `python cli.py inspect` |
| In | an L5X export (controller, program, routine, rungs, UDT) |
| Out | a `Project`; new L5X for rungs, routines and UDTs |
| May import | `core` |
| Docs | [docs/DESIGN.md](../docs/DESIGN.md), section 9 (tested on public exports) |
| Tests | `tests/test_l5x*.py`, `tests/test_corpus.py` |

## Rules

- Reading is safe for any file: entities off, no network, a size cap (`MAX_L5X_BYTES`).
- Writing is deterministic: the same rungs give the same file, byte for byte.
