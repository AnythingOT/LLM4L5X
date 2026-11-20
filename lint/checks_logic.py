"""Rung rules: they need only the rungs and the tag types, so they also run on
freshly generated logic."""

from __future__ import annotations

import re
from collections import defaultdict

from core.rung import Instr, base_tag, is_literal, walk
from lint.context import (COUNTERS, INT_TYPES, ONE_SHOTS, REAL_TYPES, TIMERS, Context, Finding, concrete,
                          guarded)
from lint.paths import branches, fmt, key, sequences, walk_series
from lint.registry import check

_MSG_BITS = {"EN", "DN", "ER", "ST", "TO", "EW", "TT", "EN_CC"}
_TC_BITS = {"DN", "EN", "TT", "CU", "CD", "OV", "UN"}
_MSG_ONLY = {"ER", "ST", "TO", "EW"}  # these names alone say MESSAGE
_TC_ONLY = {"CU", "CD", "OV", "UN"}  # these alone say COUNTER


def _scoped(ctx: Context, names: set[str], arg_index: int = 0):
    """{(scope, operand): [(instruction, location)]} for instructions in `names`.
    Operands with a variable index (Arr[i]) are left out: they are not one tag."""
    acc = defaultdict(list)
    for r in ctx.rungs:
        for ins in walk(r.rung.body):
            if ins.name.upper() in names and len(ins.args) > arg_index:
                op = re.sub(r"\s+", "", ins.args[arg_index])
                if concrete(op):
                    acc[(ctx.scope_of(base_tag(op) or op, r.owner), op)].append((ins.name.upper(), r.location))
    return acc


@check("CRT002")
def afi(ctx: Context) -> list[Finding]:
    return [Finding("CRT002", "AFI disables the whole rung.", r.location)
            for r in ctx.rungs if any(i.name.upper() == "AFI" for i in walk(r.rung.body))]


@check("ERR001", "ERR002", "ERR003")
def coil_conflicts(ctx: Context) -> list[Finding]:
    out = []
    for name, code, what in (("OTE", "ERR001", "driven by OTE"), ("OTL", "ERR002", "latched (OTL)"),
                             ("OTU", "ERR003", "unlatched (OTU)")):
        for (_scope, op), uses in _scoped(ctx, {name}).items():
            if len(uses) > 1:
                where = "; ".join(loc for _, loc in uses[:6]) + (" ..." if len(uses) > 6 else "")
                out.append(Finding(code, f"'{op}' is {what} in {len(uses)} places.", uses[0][1], where))
    return out


@check("ERR018")
def safety_std_write(ctx: Context) -> list[Finding]:
    """A standard program writes a safety tag: GuardLogix will not verify it, so say so before import.
    Reading a safety tag is allowed. Reports what the logic does; never rates safety."""
    safety = {p.name for p in ctx.project.programs if p.program_class == "Safety"}
    out = []
    for r in ctx.rungs:
        if r.owner.startswith("AOI:") or r.owner in safety:
            continue
        for ins in walk(r.rung.body):
            for a, role in ctx.roles(ins):
                if role not in ("write", "struct"):  # struct: RES, TON, CTU, ONS, MSG write their structure
                    continue
                tag = ctx.tag(base_tag(a) or "", r.owner)
                if tag is not None and tag.tag_class == "Safety":
                    out.append(Finding("ERR018", f"Standard program '{r.owner}' writes safety tag '{tag.name}' "
                                                 f"with {fmt(ins)}. Only safety logic may write safety tags; "
                                                 "Studio 5000 will not verify this.", r.location))
    return out


@check("ERR004", "ERR005")
def protected_writes(ctx: Context) -> list[Finding]:
    out = []
    for r in ctx.rungs:
        for ins in walk(r.rung.body):
            for tgt in ctx.writes(ins):
                tgt = tgt.strip()
                if "." not in tgt:
                    continue
                parent, member = tgt.rsplit(".", 1)
                member = member.upper()
                if member not in _MSG_BITS | _TC_BITS:
                    continue
                ptype = (ctx.resolve_type(parent, r.owner) or "").upper()
                if ptype == "MESSAGE" or (not ptype and member in _MSG_ONLY):
                    out.append(Finding("ERR004", f"{fmt(ins)} writes .{member} of MESSAGE '{parent}', "
                                                 "which the controller manages.", r.location))
                elif ptype in ("TIMER", "COUNTER") or (not ptype and member in _TC_ONLY):
                    out.append(Finding("ERR005", f"{fmt(ins)} writes .{member} of {ptype or 'COUNTER'} '{parent}', "
                                                 "which the instruction itself manages.", r.location))
    return out


@check("ERR006")
def msg_gated(ctx: Context) -> list[Finding]:
    out = []
    for r in ctx.rungs:
        instrs = list(walk(r.rung.body))
        if not any(i.name.upper() == "MSG" for i in instrs):
            continue
        has_ons = any(i.name.upper() in ONE_SHOTS for i in instrs)
        has_timer = any(i.name.upper() in ("XIC", "XIO") and i.args
                        and i.args[0].rsplit(".", 1)[-1].upper() in ("DN", "TT", "EN") for i in instrs)
        if not (has_ons or has_timer):
            out.append(Finding("ERR006", "MSG fires every scan: gate it with a one-shot or a timer bit.", r.location))
    return out


@check("ERR010")
def duplicate_instruction(ctx: Context) -> list[Finding]:
    out = []
    for r in ctx.rungs:
        for seq in sequences(r.rung.body):
            seen = set()
            for it in seq.items:
                if not isinstance(it, Instr) or not it.args:
                    continue
                k = key(it)
                if k in seen:
                    out.append(Finding("ERR010", f"{fmt(it)} appears twice in series.", r.location))
                seen.add(k)
        for br in branches(r.rung.body):
            legs = [key(leg) for leg in br.legs]
            for j, leg in enumerate(legs):
                if br.legs[j].items and leg in legs[:j]:
                    out.append(Finding("ERR010", "Identical parallel branch legs: "
                                       + "".join(fmt(i) for i in br.legs[j].items) + ".", r.location))
    return out


@check("ERR011")
def array_bounds(ctx: Context) -> list[Finding]:
    out = []
    for r in ctx.rungs:
        bad: list[str] = []
        for ins, before in walk_series(r.rung.body):
            for a, role in ctx.roles(ins) or [(x, "read") for x in ins.args]:
                if role == "display":
                    continue
                for inner in re.findall(r"\[([^\]]*)\]", a):
                    for ident in re.findall(r"[A-Za-z_][\w.:]*", inner):
                        if not guarded(before, ident) and ident not in bad:
                            bad.append(ident)
        for ident in bad:
            out.append(Finding("ERR011", f"Index '{ident}' is used without a range check (LIM, LES, GRT ...) "
                                         "before it on the same path.", r.location))
    return out


_CPT_DIV = re.compile(r"(?:/|\bMOD\b)\s*([A-Za-z_][\w.:\[\]]*|[-+]?\d+(?:\.\d*)?)", re.I)


@check("ERR012")
def division(ctx: Context) -> list[Finding]:
    out = []
    for r in ctx.rungs:
        for ins, before in walk_series(r.rung.body):
            name = ins.name.upper()
            divisors = []
            if name in ("DIV", "MOD") and len(ins.args) >= 2:
                divisors.append(ins.args[1].strip())
            elif name == "CPT" and len(ins.args) >= 2:
                divisors += _CPT_DIV.findall(",".join(ins.args[1:]))
            for d in divisors:
                if is_literal(d):
                    if float(d) == 0:
                        out.append(Finding("ERR012", "Division by literal zero.", r.location))
                elif not guarded(before, d):
                    out.append(Finding("ERR012", f"Divisor '{d}' is not compared with zero before the division "
                                                 "on the same path.", r.location))
    return out


@check("ERR013")
def backward_jump(ctx: Context) -> list[Finding]:
    out = []
    by_routine = defaultdict(list)
    for r in ctx.rungs:
        by_routine[(r.owner, r.routine)].append(r)
    for rungs in by_routine.values():
        labels = {}
        for r in rungs:
            for ins in walk(r.rung.body):
                if ins.name.upper() == "LBL" and ins.args:
                    labels.setdefault(ins.args[0].strip(), r.index)
        for r in rungs:
            for ins in walk(r.rung.body):
                if ins.name.upper() == "JMP" and ins.args:
                    tgt = ins.args[0].strip()
                    if tgt in labels and labels[tgt] <= r.index:
                        out.append(Finding("ERR013", f"JMP({tgt}) jumps back to a label at or above this rung.",
                                           r.location))
    return out


@check("ERR014")
def timer_reuse(ctx: Context) -> list[Finding]:
    out = []
    for (_scope, op), uses in _scoped(ctx, TIMERS | COUNTERS).items():
        names = sorted(n for n, _ in uses)
        if len(uses) > 1 and names != ["CTD", "CTU"]:
            out.append(Finding("ERR014", f"'{op}' is used by {len(uses)} timer/counter instructions.",
                               uses[0][1], "; ".join(f"{n} @ {loc}" for n, loc in uses[:6])))
    return out


@check("ERR015")
def oneshot_reuse(ctx: Context) -> list[Finding]:
    out = []
    storage = _scoped(ctx, ONE_SHOTS)
    writes = defaultdict(list)
    for r in ctx.rungs:
        for ins in walk(r.rung.body):
            if ins.name.upper() in ONE_SHOTS:
                continue
            for w in ctx.writes(ins):
                w = re.sub(r"\s+", "", w)
                writes[(ctx.scope_of(base_tag(w) or w, r.owner), w)].append((ins.name.upper(), r.location))
    for k, uses in storage.items():
        why = []
        if len(uses) > 1:
            why.append(f"shared by {len(uses)} one-shots")
        if writes.get(k):
            why.append("also written by " + ", ".join(sorted({n for n, _ in writes[k]})))
        if why:
            out.append(Finding("ERR015", f"Storage bit '{k[1]}' is " + " and ".join(why) + ".", uses[0][1]))
    return out


@check("ERR016")
def reset_missing(ctx: Context) -> list[Finding]:
    resets: set[str] = set()  # bases (and exact operands) reset or with .ACC written
    for r in ctx.rungs:
        for ins in walk(r.rung.body):
            if ins.name.upper() == "RES" and ins.args:
                resets.add(_array_base(ins.args[0]))
            for w in ctx.writes(ins):
                w = re.sub(r"\s+", "", w)
                if w.upper().endswith(".ACC"):
                    resets.add(_array_base(w[:-4]))
    # ST, FBD and unparsed rungs: RES(x) or a write to x.ACC
    for m in re.finditer(r"\bRES\s*\(\s*([^,)]+?)\s*\)|([\w:\[\].,]+?)\.ACC\s*:=", ctx.usage_text, re.I):
        resets.add(_array_base(m.group(1) or m.group(2)))
    out = []
    for (_scope, op), uses in _scoped(ctx, {"RTO", "RTOR"} | COUNTERS).items():
        if _array_base(op) not in resets:
            out.append(Finding("ERR016", f"'{op}' ({uses[0][0]}) is never reset: no RES and no write to .ACC.",
                               uses[0][1]))
    return out


def _array_base(op: str) -> str:
    """Arr[3] -> Arr[] (a reset of any element of an array counts, e.g. RES(Arr[i]) in a loop)."""
    op = re.sub(r"\s+", "", op)
    return re.sub(r"\[[^\]]*\]", "[]", op)


@check("WAR006")
def empty_rung(ctx: Context) -> list[Finding]:
    return [Finding("WAR006", "Rung has no instructions.", r.location)
            for r in ctx.rungs if not any(True for _ in walk(r.rung.body))]


@check("WAR007")
def empty_branch(ctx: Context) -> list[Finding]:
    out = []
    for r in ctx.rungs:
        if any(not leg.items for br in branches(r.rung.body) for leg in br.legs):
            out.append(Finding("WAR007", "A branch leg is empty: an always-true bypass of the other legs.",
                               r.location))
    return out


@check("WAR013")
def msg_stagger(ctx: Context) -> list[Finding]:
    by_trigger = defaultdict(list)
    for r in ctx.rungs:
        for ins, before in walk_series(r.rung.body):
            if ins.name.upper() == "MSG" and ins.args:
                by_trigger[tuple(key(i) for i in before)].append((ins.args[0], r.location))
    out = []
    for trig, items in by_trigger.items():
        if len(items) > 1:
            cond = "".join(f"{k[1]}({','.join(k[2])})" for k in trig) or "(unconditional)"
            out.append(Finding("WAR013", f"{len(items)} MSGs share the trigger {cond} and fire together.",
                               items[0][1], "; ".join(f"{t} @ {loc}" for t, loc in items[:10])))
    return out


@check("WAR015")
def mov_real_to_int(ctx: Context) -> list[Finding]:
    out = []
    for r in ctx.rungs:
        for ins in walk(r.rung.body):
            if ins.name.upper() not in ("MOV", "MOVE") or len(ins.args) < 2:
                continue
            src, dst = ins.args[0].strip(), ins.args[1].strip()
            st, dt = ctx.resolve_type(src, r.owner), ctx.resolve_type(dst, r.owner)
            if st in REAL_TYPES and dt in INT_TYPES:
                out.append(Finding("WAR015", f"{fmt(ins)} converts {st} to {dt}.", r.location))
    return out


_MATH = {"MOV", "MOVE", "ADD", "SUB", "MUL", "DIV", "MOD", "AND", "OR", "XOR", "CPT"}
_NUM = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w.])")


@check("INF007")
def hard_coded(ctx: Context) -> list[Finding]:
    out = []
    for r in ctx.rungs:
        for ins in walk(r.rung.body):
            if ins.name.upper() not in _MATH:
                continue
            lits = []
            for a, role in ctx.roles(ins):
                if role == "read" and is_literal(a):
                    lits.append(a)
                elif ins.name.upper() == "CPT" and role == "other":
                    lits += _NUM.findall(a)
            lits = [x for x in lits if x not in ("0", "1", "-1", "0.0", "1.0")]
            if lits:
                out.append(Finding("INF007", f"{fmt(ins)} uses the literal {lits[0]}: use a named tag.", r.location))
    return out
