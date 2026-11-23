# Roadmap and to-do

Status 24 Nov 2026 (after #39). Each item: what, why, done when. Keep PRs small and from main.

## Done (Nov 2026)

Output checks (latch scope, OR-split, stray RISE, RESET_ACC), attempts in Report.txt, Req ID +
Traceability, I/O list reader + MAP_IN/MAP_OUT, plant models, scenario runner, Energise engine and
page, block library, coding-standards profile, security hardening (local model only, size cap,
pinned versions, ignored output, CI with the confidential-name check), oracle run in CI.

## Next

1. **Blocks in the workbook.** A row (or a Device/Block column) says "P101 is a Motor"; the compiler
   instantiates the block, and its plant entry and scenarios are collected for Energise.
   *Done when* a workbook with block rows builds, and Energise runs the collected scenarios green.
2. **Profile in the app, and generation follows it.** Choose a profile file on the Rules page; the
   compiler names helper tags and avoids banned instructions by it.
   *Done when* generated rungs pass their own profile with no STD findings.
3. **Hardware/emulator run.** A pylogix backend with the four scenario methods (has, read, write,
   advance) and the plant stepped in the poll loop; L5X import and download through the Logix
   Designer SDK (the owner has the licence). Probably shared with OpenVnV.
   *Done when* the tank scenarios pass on an emulator or bench controller unchanged.
4. **Energise from the I/O list.** Load an I/O list: MAP routines and a proposed plant come with it.
   Add a tank level model (analog), so fill scenarios use a real level instead of set switches.
5. ~~Level 2 workbooks on main.~~ Done: `--level 2`, with `Flow_SP` and four other near-twin names
   removed from its pool. Next: one fresh level-2 holdout on the laptop, a seed never run with the model.
6. **Near-name policy.** On the last attempt, a near-twin of a tag the request names (Flow_SP for
   Flow_Setpoint) fails the row instead of warning. Owner's decision: stricter vs fewer failures.

## Later

7. **Step 1: operations text → rows (pilot).** Testability check on each requirement; draft rows
   with blocking questions, visible assumptions (always ask about power-restore behaviour) and Req
   IDs; draft scenarios from the requirement text only, never from the drafted rows.
   *Needs* 5-10 sanitised operations requirements and what the engineer actually built.
8. **OpenVnV** (separate private repo): backend interface + fake PLC + unit tests, command-line runner
   with exit codes and JUnit/JSON, Excel import, tag picker from L5X, step templates. Same scenario
   format as here; qualification suite (must-pass / must-fail) as tool validation evidence.
9. **Simulator coverage**: JSR and AOI bodies (~95% of public rungs), CPT, strings; then a
   conformance suite against a bench controller, kept as the simulator's validation record.
10. **Hash-pinned requirements**, generated on the laptop (`pip-compile --generate-hashes`).
11. **"Validated with" record**: Studio 5000 version, date, workbook, Verify errors/warnings.

## Needs from the owner

- Real I/O list column names (or a sanitised sample layout).
- AOIs or rung patterns for devices, and a sample naming convention (pattern only).
- Studio 5000 version used for the import, and the Verify result.
- Controller families in use, and Echo/Emulate availability.
- Pilot data for item 7.

## Not to do

- No model in the verdict path: the simulator, scenarios and lint decide; the model only drafts.
- No generated module/hardware XML: Rockwell's EPLAN/AutoCAD Electrical import owns the I/O tree.
- No safety logic or safety I/O generation; ERR018 flags standard logic writing safety tags.
- No further tuning on saturated workbooks.
