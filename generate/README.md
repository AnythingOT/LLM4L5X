# generate/

From what the user gives to LogicSpec or UDTs: the local model, its prompt and checks, and the Excel readers.

| | |
|---|---|
| Page | Chat (`/`): plain English, the requirements workbook, the UDT mode |
| Command line | `python cli.py ask`, `probe`, `grammar` |
| In | plain English, a requirements workbook, an I/O list |
| Out | LogicSpec and compiled rungs; the UDT text form |
| May import | `core`, `l5x`, `lint` (the model's answer is linted before it is accepted), `udt` |
| Docs | [docs/IOLIST.md](../docs/IOLIST.md), [docs/GUIDE.md](../docs/GUIDE.md) |
| Tests | `tests/test_llm.py`, `test_gbnf.py`, `test_spec.py`, `test_iolist.py` |

## Rules

- The model only writes LogicSpec or the UDT text form. Everything after that is fixed code.
- Local models only, unless the user allows otherwise in Settings. Never start a model server on `0.0.0.0`.
- `examples.yaml` holds the few-shot examples; add your plant's wording there.
