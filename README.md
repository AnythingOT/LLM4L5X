# LLM4L5X

Plain English → ladder logic for Rockwell Studio 5000, importable as L5X, built for **small local LLMs** (under ~14B, no fine-tuning). It also reads L5X exports back into structured data.

The model never writes rung text or XML. It writes **LogicSpec**, a tiny boolean language. Deterministic code compiles that into rungs (branches included), validates them and writes the L5X.

```
English ──(local LLM, grammar-constrained)──> LogicSpec ──(compiler)──> rung AST ──> validator ──> L5X
                                                  ▲                                     │
                        few-shot examples <── decompiler <── rungs from your exports <──┘
```

**Status:** the deterministic core is done and tested (108 tests). The LLM layer is not built yet. Nothing has been import-tested in Studio 5000 yet; see [Unverified](#unverified). Full design and roadmap: [HANDOFF.md](HANDOFF.md).

## Why a boolean language instead of rung text

In ladder logic, series is AND and parallel is OR. Logix rungs can't express bridge circuits, so the condition side of every rung is exactly an AND/OR tree. Small models have seen huge amounts of boolean expressions and very little bracketed rung text, so they write the expression and the compiler builds the branches:

```
Pump := (Start_PB OR Pump) AND NOT Stop_PB AND NOT Fault;
→ [XIC(Start_PB) ,XIC(Pump) ]XIO(Stop_PB)XIO(Fault)OTE(Pump);

Lamp := NOT (A AND (B OR C > 5));          # NOT pushed down with De Morgan
→ [XIO(A) ,XIO(B)LEQ(C,5) ]OTE(Lamp);
```

The compiler is checked by truth-table equivalence. For random expressions, the compiled rung run through a scan simulator must match the expression for every input combination.

## Install and use

```bash
pip install -e .[test]      # needs lxml, PyYAML; pytest for tests
pytest
```

```bash
# LogicSpec -> rungs (+ L5X). Read-back of each statement goes to stderr.
llm4l5x compile "Pump := (Start_PB OR Pump) AND NOT Stop_PB;" -o pump.L5X
llm4l5x compile spec.txt --routine Generated -o routine.L5X          # whole routine
llm4l5x compile spec.txt --project plant.L5X --program MainProgram  # use real tag types

# Existing code -> information
llm4l5x inspect plant.L5X                 # summary
llm4l5x inspect plant.L5X --decompile     # every rung as LogicSpec, or why not
llm4l5x inspect plant.L5X --xref Pump     # who reads/writes Pump
llm4l5x validate plant.L5X
llm4l5x rung "XIC(a)[XIC(b) ,XIO(c) ]OTE(d);"

# llama.cpp grammar restricted to a project's real tags (experimental)
llm4l5x grammar --project plant.L5X --program MainProgram > logicspec.gbnf
```

## LogicSpec reference

| LogicSpec | Ladder |
|---|---|
| `X := expr;` | conditions then `OTE(X)` |
| `IF expr THEN action, action;` | conditions then the action, or an output branch for several |
| `IF TRUE THEN action;` | unconditional |
| `A` / `NOT A` | `XIC(A)` / `XIO(A)` |
| `a AND b` | series |
| `a OR b` | branch |
| `N = 5`, `<>`, `>`, `<`, `>=`, `<=` | `EQU NEQ GRT LES GEQ LEQ` |
| `RISE(expr)` | `ONS` with an auto storage bit (helper rung if not first on the rung) |
| `DELAY(expr, 5s [, Timer])` | helper rung `expr TON(T,?,?)`, then `XIC(T.DN)` |
| `OFFDELAY(expr, 2s [, Timer])` | same with `TOF` |

Actions: `SET X`, `RESET X`, `CLEAR N`, `RESET_ACC T`, `COUNT_UP(C, 10)`, `COUNT_DOWN(C, 10)`, `START_TIMER(T, 5s)`, `START_OFF_TIMER(T, 5s)`, `N := A`, `N := A + B` (`-`, `*`, `/`).

Rules:
- **AND and OR can't be mixed at one level without parentheses.** `A AND B OR C` is rejected, so precedence mistakes can't happen.
- At statement level `:=` is always a boolean output. Inside `IF ... THEN` it's a move or arithmetic.
- Durations: `ms`, `s`, `min` (or `m`), `h`. Keywords are case-insensitive and reserved.
- **Tag types are inferred** from use: contacts and coils are BOOL, comparisons and math are DINT (REAL if a decimal literal is involved), plus TIMER and COUNTER. Pass `--project` to use the real types and avoid creating tags that already exist.
- Compiler-made tags are named `L4X_ONS_n`, `L4X_EDGE_n`, `L4X_TMR_n` (`--prefix` changes it).
- **Each rung gets an English comment** generated from the LogicSpec. Use it to check intent before importing.

## Layout

```
src/llm4l5x/
  catalog/      instructions.yaml (single source of truth) + loader; AOIs extend it
  rung/         neutral-text AST, parser, printer (lossless round trip)
  logicspec/    parser, compiler, decompiler, English describer, GBNF builder
  sim/          scan simulator (bits, compares, ONS, TON/TOF/RTO, CTU/CTD, math)
  validate/     operand counts/types/roles, ONS reuse, duplicate coils, timer reuse, unknown tags
  l5x/          reader (secure lxml), writer (Rung and Routine targets), cross-reference
  cli.py
tests/          108 tests incl. truth-table property tests; fixtures/ is hand-written, not a real export
```

## Unverified

These details come from memory, not from real exports, and need confirming by importing into Studio 5000 (HANDOFF.md section 9):

- **Timer/counter operands:** written as `TON(T,?,?)` with the preset in tag data. If import rejects this, use `--display values` to get `TON(T,5000,0)`.
- **TIMER/COUNTER L5K data layout** `[0,PRE,0]`.
- **Exact export whitespace inside branches.** The parser accepts any whitespace; the printer emits `[A ,B ]`.
- **AOI call operands:** assumed to be the instance tag plus required parameters, in definition order.
- **Rung-export element layout** (`Use` attributes, where tags go).

**Real L5X exports are the next thing needed.** Run `llm4l5x inspect your.L5X --decompile` and `validate` on them and fix whatever disagrees.

## Safety

Generated code is a draft for an engineer to review. Read the rung comments, verify offline, and never auto-download to a running controller. Keep safety routines out of scope.

## License

MIT
