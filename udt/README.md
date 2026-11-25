# udt/

UDTs: create them (text form, Excel, plain English through `generate`) and reorder an export's UDTs so no memory is wasted.

| | |
|---|---|
| Page | Chat in UDT mode; *optimize UDTs* on an attached file |
| Command line | none |
| In | the UDT text form, an Excel sheet, an attached export |
| Out | DataType L5X files; the reordered export |
| May import | `core`, `l5x`, `lint` (the project index used to find layout risks) |
| Docs | [docs/DESIGN.md](../docs/DESIGN.md), UDT sections |
| Tests | `tests/test_udt*.py` |

## Rules

- Sizes and the best member order come from `core/udt_layout.py`, which Lint uses too.
- Optimizing never changes a UDT that something copies by byte offset (COP/CPS, MSG, produced/consumed)
  without saying so: those are shown as layout risks.
