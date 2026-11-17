# LLM4L5X — design and handoff

This file is the full brief for whoever continues the work (human or model). It records what the
owner wants, what was decided and why, what is still unverified, and the build order with
acceptance criteria. Read it fully before writing code.

## 1. Goal

Turn plain-English requests into Rockwell Studio 5000 ladder logic that imports cleanly as L5X,
and go the other way: read an L5X export and pull out useful, structured information.

The owner's constraints, all firm:

- **Local LLMs only**, under about 14B parameters (the old code used phi4-mini through Ollama).
  Nothing leaves the machine.
- **No fine-tuning.** Out of budget. Quality has to come from task design, retrieval and
  constraints.
- **Parallel logic (branches) is required.** The previous attempt could not do it.
- **The XML/L5X wrapper is deterministic.** The model only ever contributes the logic.
- **Reuse Rockwell's instruction help** (the help shipped with Studio 5000, or manual 1756-RM003)
  as the source for the instruction catalog instead of hand-writing one.

## 2. Central rule

**No model output reaches an L5X file without being parsed, validated and compiled by code.**
The model is the last component to build, not the first. Everything before it is ordinary,
testable software and is useful on its own.

## 3. Terminology

- What sits in `<Rung><Text><![CDATA[...]]>` is Rockwell **ladder neutral text**, e.g.
  `XIC(a)[XIC(b) ,XIO(c) ]OTE(d);`. The owner calls it "IL". It is not IEC 61131-3 Instruction
  List. Use "neutral text" or "rung text" in code, prompts and docs.
- **RungAST**: our parsed tree of a rung (instructions, series, branches).
- **LogicSpec**: the small boolean mini-language the model writes (section 6).

## 4. Repositories

- `AnythingOT/LLM4L5X` — the active repo. Currently only README and MIT LICENSE. All new work
  goes here.
- `AnythingOT/LLM4L5XGen` — archived prototype (system prompt + keyword validator + f-string
  XML). Reference only. Do not port its code. Its known faults, so they are not repeated:
  - Invalid comparison mnemonics (`EQ, NE, GT, LT, GE, LE`). Logix uses
    `EQU, NEQ, GRT, LES, GEQ, LEQ`.
  - The prompt's timer-done section says `XIC(A.DN)` but its examples output `OTE(A.DN)`.
  - `ONS` treated as acting on the input tag; it needs its own storage bit per instance.
  - No branches. Every rung written with `Number="0"`.
  - Timer preset passed as an operand (`TON(T,5000,0)`); see section 9.
  - `Chat_ProcessSingleInput.py` raises NameError when nothing parses; re-prompt is disabled.
  - Tag typing guessed from the instruction, inconsistently; numeric literals become tags.
  - Instruction knowledge duplicated in three places (prompt, keyword dict, tag module) that
    disagree with each other.
  - English keyword matching used as the main logic rather than as a sanity check.

Neither repo contains a sample L5X export. **Ask the owner for real exports early** (routines
with branches, timers, counters, ONS, AOIs, rung comments). They are the test corpus and the
few-shot source. Nothing below can be fully verified without them.

## 5. Architecture

Build in this order. Each layer has a test that does not need a model.

1. **Instruction catalog** — one data file (YAML or JSON) that is the single source of truth.
   Per instruction: mnemonic, operands (name, data type, role read/write/control-structure,
   whether shown as `?` in neutral text), input vs output instruction, short description.
   The grammar, validator, prompt snippets and tag typing are all generated from it.
   - Draft it by parsing the operand tables in the help/manual with plain code, not an LLM.
   - Check it against the corpus: every instruction seen in real exports must match the
     catalog's operand count. Disagreements are reported, not silently resolved.
   - AOI and UDT definitions found in an L5X extend the catalog at load time.
   - Rockwell's help text is copyrighted. Do not commit raw help text to the public repo;
     commit only our own catalog. Keep any extraction script pointed at a local path.
2. **Rung parser and printer** — neutral text ↔ RungAST, branches at any depth.
   - Acceptance: `print(parse(x)) == x` for every rung in the corpus. Aim for byte-exact. If
     exports vary in whitespace, define one normalisation and document it.
3. **L5X reader and writer** — lxml in, templates out.
   - Reader yields routines, rungs (number, text, comment), tags (type, description, data),
     UDTs, AOIs.
   - Writer produces Rung- and Routine-target imports with correct rung numbering, CDATA,
     comments, and tags including initial data (timer presets live here).
   - Acceptance: read → write → read gives equal structures; output imports into Studio 5000.
4. **Project index** — tag database and cross-reference graph (which rung reads/writes which
   tag). Feeds retrieval and the validator.
5. **Validator** — on RungAST: operand count and type per catalog, operand roles, unknown tags,
   unique storage bit per ONS, duplicate destructive coils (two OTEs on one tag), output
   instruction present, timer/counter tag types.
6. **LogicSpec compiler and decompiler** — section 6. The core of branch support.
7. **Scan simulator** — evaluates a RungAST for bits, comparisons, ONS, TON/TOF, CTU/CTD.
   Used for truth-table equivalence and behavioural tests.
8. **Eval harness** — section 8. Must exist before any model tuning.
9. **LLM layer** — section 7.

Suggested layout: `l5x/` (reader, writer), `rung/` (ast, parser, printer), `catalog/`,
`logicspec/` (grammar, parser, compiler, decompiler), `validate/`, `sim/`, `llm/`, `eval/`,
`tests/`. Python. In the session this was written in (Python 3.13), lxml, pytest and PyYAML were
installed; lark and hypothesis were not, and package installs were blocked. Both grammars are
small, so a hand-written recursive-descent parser is fine and removes the lark dependency;
write property tests with plain `random` if hypothesis is unavailable.

## 6. LogicSpec: how branches are handled

Reasoning: in ladder, series is AND and parallel is OR. Logix rungs cannot express bridge
circuits, so the condition side of every rung is exactly an AND/OR tree. Small models have seen
huge amounts of boolean-expression text and almost no bracketed neutral text. So the model
writes a boolean expression and code builds the branches.

### 6.1 Grammar (v0 — refine against the corpus)

```
program    := statement+
statement  := tag ":=" expr ";"                        # OTE
            | "IF" expr "THEN" action ("," action)* ";"
action     := "SET" tag | "RESET" tag                  # OTL / OTU
            | tag ":=" arith                           # MOV / ADD / SUB / MUL / DIV
            | "CLEAR" tag                              # CLR
            | "COUNT_UP(" tag "," int ")"              # CTU, preset into tag data
            | "COUNT_DOWN(" tag "," int ")"            # CTD
expr       := unary | unary ("AND" unary)+ | unary ("OR" unary)+
unary      := "NOT" unary | atom
atom       := tag | comparison | "(" expr ")"
            | "RISE(" expr ")"                         # one-shot
            | "DELAY(" expr "," duration ")"           # on-delay
            | "OFFDELAY(" expr "," duration ")"        # off-delay
comparison := operand ("=" | "<>" | ">" | "<" | ">=" | "<=") operand
```

`expr` deliberately cannot mix AND and OR at one level, so parentheses are mandatory when they
mix and precedence errors are impossible. Tags may include members and bits (`T1.DN`,
`Word.3`, `Arr[2]`). The decoding grammar given to the model is built per request: the tag
terminal is restricted to retrieved candidate tags plus an explicit new-tag form.

### 6.2 Compile rules (LogicSpec → RungAST)

- AND → children in series. OR → a branch with one leg per child. Flatten nested same-operator
  nodes; do not otherwise minimise. The rung should mirror what was asked.
- `tag` → `XIC(tag)`. `NOT tag` → `XIO(tag)`.
- NOT on a group → push down with De Morgan until it reaches atoms.
- Comparisons → `EQU NEQ GRT LES GEQ LEQ`. NOT flips to the complement.
- `RISE(e)` → compile `e`, then `ONS(bit)` with an auto-allocated, unique BOOL storage tag.
  `NOT RISE(...)` is rejected with a clear error.
- `DELAY(e, d)` → emit a separate earlier rung `e TON(T)` with an auto-allocated TIMER tag whose
  preset is written into the tag data in ms; the atom becomes `XIC(T.DN)`.
  `NOT DELAY(...)` → `XIO(T.DN)`. `OFFDELAY` likewise with TOF.
- One statement → one rung (plus helper timer rungs). Several statements → several rungs, in
  order. Merging shared conditions into output branches is cosmetic and deferred.
- Every auto-allocated tag is added to the L5X tag list with the right type.

Example:

```
Pump := (Start_PB OR Pump) AND NOT Stop_PB AND NOT Fault;
→ [XIC(Start_PB) ,XIC(Pump) ]XIO(Stop_PB)XIO(Fault)OTE(Pump);
```

### 6.3 Decompile (RungAST → LogicSpec)

Reverse of the above, run over the corpus to produce few-shot examples and readable
explanations. Rungs that are not pure condition-then-outputs (output instructions mid-rung,
JSR, instructions with no LogicSpec form) are marked non-convertible and skipped, not forced.

### 6.4 Acceptance

- Property test: for random LogicSpec expressions with up to about 12 boolean atoms, the
  truth table of the expression equals the truth table of the compiled rung under the
  simulator. Treat a comparison and its complement as one atom and its negation.
- Round trip: `decompile(compile(s))` is equivalent to `s` for convertible forms.
- Every compiled rung passes the validator.

## 7. LLM layer

Runtime: llama.cpp (GBNF grammars per request). Ollama's structured output is JSON-schema
only, which is not enough for a custom language. Verify current capabilities before relying on
this note. Embeddings for retrieval also run locally.

**Explain / extract** (build first, low risk): input is LogicSpec or RungAST plus tag
descriptions, never raw XML. Output is text or JSON.

**Generate**, one statement per call:

1. Retrieve 3–5 similar examples (description → LogicSpec) and candidate tags from the tag
   database. Tag matching is retrieval, not generation.
2. Build the per-request grammar. Prompt contains only the examples and the few constructs they
   use. Keep it short; small models degrade with long system prompts.
3. Decode under the grammar. Few-shot examples must use exactly the grammar's format, otherwise
   constrained decoding forces the model down low-probability paths and output is valid but
   wrong.
4. Compile, validate. On failure, re-prompt once or twice with the specific validator error.
5. Read back: a deterministic template describer turns the LogicSpec into plain English, plus
   a truth table for small cases. The user confirms intent.
6. Write L5X. A human imports it. Never auto-download to a controller. Exclude safety routines.

Ambiguity guard: if the request mixes "and" and "or" with no clear grouping, ask the user
rather than guessing.

Few-shot data without fine-tuning: the template describer generates base descriptions for
corpus rungs; the local model may paraphrase them offline for variety (paraphrasing is much
easier than describing). Real rung comments are used when they are good, which is rare.

Fallback for requests LogicSpec cannot express: constrained decoding directly to neutral text
with a catalog-generated grammar. Lower reliability; build last.

## 8. Evaluation

Hold out part of the corpus. Report, per model and per prompt variant:

- Validator pass rate.
- Equivalence to the reference rung (truth table / simulator), not string match.
- Tag selection accuracy.
- Import success in Studio 5000 on a sample (manual unless automated).

Parse rate is 100% by construction and is not a metric. Without this harness there is no way to
tell whether a model swap or prompt change helped.

## 9. Claims to verify against real exports

These were stated from memory during design. Confirm each one on real files before depending
on it, and correct this document where it is wrong.

- Timer and counter operands export as `TON(Timer1,?,?)`; preset and accum are tag members,
  set in tag data, not operands.
- Exact whitespace of branches in exported text (believed `[XIC(a) ,XIC(b) ]`).
- How TIMER/COUNTER initial data must be written for import (L5K vs Decorated data forms).
- Which `SoftwareRevision` the owner targets (the old code hard-coded 32.04) and whether
  imports are tolerant of minor mismatches.
- Any branch nesting or rung size limits in Logix.
- Whether the Rockwell Logix Designer SDK supports the owner's version for automated import
  tests.
- That the help/manual operand tables are regular enough to parse with code.

## 10. Non-goals for now

Fine-tuning. Multi-rung sequence design from one request. FBD, SFC and ST routines. Whole
project generation. Logic minimisation. Automatic download to hardware.

## 11. Open questions for the owner

- Can you supply real L5X exports, and may any be committed as test fixtures (sanitised)?
- Which Studio 5000 version, and which local model and hardware (RAM/VRAM)?
- Is the Flask UI from the old repo wanted again, or is a CLI enough at first?
- Is there a tag naming convention the new-tag generator should follow?

## 12. First milestones

**Status (2026-11-17):** M1 and M2 done. M3 done except the real import test. M4 done except the
corpus round trip, which is blocked on real exports. M5 not started; an experimental GBNF builder
exists in `logicspec/gbnf.py` (checked with a small GBNF interpreter in `tests/helpers.py`, not yet
with llama.cpp). The README lists exactly what is unverified.

- **M1** (done): catalog schema with a hand-checked core set (XIC XIO OTE OTL OTU ONS TON TOF CTU CTD
  MOV ADD SUB MUL DIV CLR COP EQU NEQ GRT LES GEQ LEQ), rung parser/printer with round-trip
  tests on synthetic rungs including nested branches.
- **M2** (done): LogicSpec parser, compiler, simulator for bits/comparisons, truth-table property
  tests.
- **M3** (needs import test): L5X writer (Rung and Routine targets) with tags and timer data; owner test-imports.
- **M4** (needs real exports): L5X reader, decompiler, corpus round-trip once exports arrive; catalog checked
  against corpus.
- **M5**: eval harness, then the LLM layer (explain first, generate second).

M1–M4 need no model.

## 13. Working with the owner

- Usually on a phone: lead with the answer, keep replies short, lists over prose.
- Wants critical, strict answers. Say what is wrong plainly.
- Wants every reply to end by teaching one relevant thing.
- Do not commit or push unless asked. The current clone is read-only; pushing needs the repo
  attached with push access.
