# tests/

pytest: one file per area. A new test must fail on the code before the change.

| | |
|---|---|
| Run | `pytest` from the repository folder; `ruff check .` for the code checks |
| Fixtures | `fixtures/`: hand-written L5X files, except `studio_single_udt.L5X` (from the MIT-licensed L5X_UDTOptimizer) |
| Corpus | `test_corpus.py` runs on public exports when `LLM4L5X_CORPUS` points to them (CI does) |
| Structure | `test_structure.py`: which folder may import which, and that STRUCTURE.txt is current |
