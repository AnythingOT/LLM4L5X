# lint/

The 50 programming rules (CRT/ERR/WAR/INF), the company profile, and auto-fix where a fix is certain.

| | |
|---|---|
| Page | Lint (`/lint`): switch rules on or off; Chat: *validate* |
| Command line | `python cli.py validate`, `fix` |
| In | a `Project` (whole export) or rungs alone |
| Out | findings; fixed rungs, each fix checked in the simulator |
| May import | `core`, `l5x` |
| Docs | [docs/PROFILE.md](../docs/PROFILE.md) |
| Tests | `tests/test_lint*.py`, `test_autofix.py`, `test_profile.py` |

## Rules

- A rule registers in `registry.py` with the codes it can emit, and its text lives in `rules.py`.
- An auto-fix is applied only when the routine behaves the same before and after (`core/rung_compare.py`).
- The same rules exist in the older L5X_Lint repository. Changes are made here.
