# Roadmap and to-do

Status 24 Nov 2026 (after #57). Each item: what, why, done when. Keep PRs small and from main.

## Done (Nov 2026)

Output checks (latch scope, OR-split, stray RISE, RESET_ACC; no-op writes, swapped copies, invented
outputs #46), attempts in Report.txt, Req ID + Traceability, I/O list reader + MAP_IN/MAP_OUT, device
models, test-case runner, Energize engine and page (live ladder #49, tag presets #48), Tests page (#51),
block library, coding-standards profile, security hardening (local model only, size cap, pinned versions,
ignored output, CI with the confidential-name check), oracle run in CI with full marks required (#41),
level-2 workbooks (#43), 858 public L5X exports in CI (#45), a requirements run survives leaving the chat
page (#50).

## Next

1. **Lint auto-fix, with y/n; and the near-name policy (old item 6).** Generated L5X is fixed by its own
   lint before export; L5X brought in from elsewhere (Lint as a product) gets the same offer. Every fix is
   re-checked in the simulator.
   - *Safe, behaviour unchanged, one batch:* WAR006 empty rung (delete), ERR010 same instruction twice in
     series (drop one), ERR015 shared one-shot storage (one bit each), INF001 unused tag (delete),
     INF003/INF004/STD004 missing tag description or rung comment (from the requirement text, no model),
     WAR016 INT/SINT on a new tag (DINT), WAR010/WAR011 UDT order (the UDT optimizer), CRT001 forces
     (strip).
   - *Possible, changes behaviour, a y/n each:* WAR008 preset 0 (ask, write it to the tag; a MOV rung
     only if the profile says so), ERR012 division by a tag (`NEQ(divisor,0)` guard), ERR011 array index
     (LIM guard), INF007 literal (named constant tag, name from the profile), STD001 tag name (rename
     everywhere), ERR001 OTE in two places (one OR rung), ERR006 MSG not gated (one-shot).
   - *Never automatic:* ERR002/ERR003 several latches/unlatches, ERR005 writes to a timer bit, ERR014
     timer used twice, ERR016 counter never reset, WAR007 empty branch leg, CRT002 AFI, ERR018 safety tags,
     WAR015 REAL to integer, ERR013 backward jump, INF002 loose BOOLs; STD002/STD003 only where an exact
     equivalent exists. Controller-project rules (modules, tasks, fault handlers, watchdog, I/O mapping)
     do not apply to generated routines.
   - *Near-name policy:* on the last attempt, a near-twin of a tag the request names (`Flow_SP` for
     `Flow_Setpoint`) fails the row instead of warning (owner: yes, in this iteration).
   *Done when* every "safe" fix passes a before/after simulator comparison on the public corpus, and the
   y/n flow works in the chat and on a requirements run.
2. **Profile in the app, and generation follows it.** Choose a profile file on the Lint page; the
   compiler names helper tags, avoids banned instructions, and adds `MOV(preset, T.PRE)` only if the
   profile asks. *Done when* generated rungs pass their own profile with no STD findings.
3. **Test cases: rules first, then drafts.** Standard test cases per block (Motor: start, stop, fault,
   feedback timeout, interlock) from the library; then the model drafts test cases from the requirement
   text only (never from the rungs or LogicSpec), shown as drafts for the engineer to approve on the Tests
   page. *Done when* a workbook with blocks gets its standard test cases without typing, and a draft is
   never run until approved.
4. **Blocks in the workbook.** A row (or a Device/Block column) says "P101 is a Motor"; the compiler
   instantiates the block, and its device model and test cases are collected for Energize and Tests.
   *Done when* a workbook with block rows builds, and Tests runs the collected test cases green.
5. **Logix Emulate run.** A pylogix backend with the four test-case methods (has, read, write, advance)
   and the device models stepped in the poll loop; same test cases as the simulator. Emulate runs in real
   time: no fast-forward, and EXPECT timings need a tolerance (the poll loop adds tens of ms). L5X import
   and download through the Logix Designer SDK (the owner has the licence). Probably shared with OpenVnV.
   *Done when* the tank test cases pass on Emulate unchanged.
6. **Energize from the I/O list.** Load an I/O list: MAP routines and proposed device models come with it.
   Add a tank level model (analog), so fill test cases use a real level instead of set switches.

## Later

7. **AI/ML process models (in this repository).** Data-driven models of the process (tank level,
   temperature, pressure, flow response) used as device models in Energize and Tests, where a first-order
   or rule model is too coarse. Rules for when this starts:
   - A process model is a **test fixture, not a judge**: "no model in the verdict path" still holds (the
     runner decides pass or fail); a learned model only decides what the simulated plant does.
   - Model files are versioned inputs with their training data reference; the same model and inputs give
     the same result (deterministic inference, fixed seeds).
   - Each model states its validated range and error against recorded data, and refuses inputs outside it.
   - Test results say which process model (and version) they ran against.
   - Keep it in its own package (e.g. `process/`), behind the same device-model interface, so the rule
     models stay the default and need no ML dependencies.
   *Needs* recorded process data (sanitised) and the signals that matter.
8. **Step 1: operations text → rows (pilot).** Testability check on each requirement; draft rows
   with blocking questions, visible assumptions (always ask about power-restore behaviour) and Req
   IDs; draft test cases from the requirement text only, never from the drafted rows.
   *Needs* 5-10 sanitised operations requirements and what the engineer actually built.
9. **OpenVnV** (separate private repo): backend interface + fake PLC + unit tests, command-line runner
   with exit codes and JUnit/JSON, Excel import, tag picker from L5X, step templates. Same test-case
   format as here; qualification suite (must-pass / must-fail) as tool validation evidence.
10. **Simulator coverage**: JSR and AOI bodies (~95% of public rungs), CPT, strings; measure on the public
   corpus first; then a conformance suite against Emulate, kept as the simulator's validation record.
11. **Hash-pinned requirements**, generated on the laptop (`pip-compile --generate-hashes`).
12. **"Validated with" record**: Studio 5000 version, date, workbook, Verify errors/warnings.
13. **Test-case file format name**: accept `TESTCASE` as well as `SCENARIO`, if wanted (existing files
   keep working).

## Measurement (owner's laptop, when testing resumes)

- One fresh level-2 holdout (a seed never run with the model, e.g. 53) to measure the #46 checks. Write
  down the expected score before running it.

## Needs from the owner

- Real I/O list column names (or a sanitised sample layout).
- AOIs or rung patterns for devices, and a sample naming convention (pattern only).
- Studio 5000 version used for the import, and the Verify result.
- Controller families in use. (Emulate: available; pylogix does not depend on its version.)
- Pilot data for item 8; recorded process data for item 7.

## Not to do

- No model in the verdict path: the simulator, test cases and lint decide; the model only drafts.
- No generated module/hardware XML: Rockwell's EPLAN/AutoCAD Electrical import owns the I/O tree.
- No safety logic or safety I/O generation; ERR018 flags standard logic writing safety tags.
- No further tuning on saturated workbooks.
- No test case derived from the code it tests.
