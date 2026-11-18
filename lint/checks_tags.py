"""Tag rules: naming, data types, presets, usage, descriptions."""

from __future__ import annotations

import re

from core.rung import walk
from l5x.reader import TagInfo
from lint.context import Context, Finding
from lint.registry import check

SAFETY_PREFIX, STANDARD_PREFIX = "SFTY_", "STD_"
_DESC_REQUIRED = {"BOOL", "SINT", "INT", "DINT", "LINT", "USINT", "UINT", "UDINT", "ULINT", "REAL", "LREAL"}
_BIT_CAPABLE = {"SINT", "INT", "DINT", "LINT", "USINT", "UINT", "UDINT", "ULINT"}
_SPARE = re.compile(r"(?i)\bspare\b|\bunused\b")  # whole words: SPARE_1 does not match


def _where(t: TagInfo) -> str:
    return f"Controller:{t.name}" if t.scope == "controller" else f"{t.scope}:{t.name}"


def _user_tags(ctx: Context):
    """Controller and program tags (AOI locals are the AOI's own business)."""
    return list(ctx.project.tags.values())


@check("WAR001")
def safety_map_naming(ctx: Context) -> list[Finding]:
    safety = {t.name for t in _user_tags(ctx) if t.tag_class == "Safety"}
    out = []
    for a, b in ctx.project.safety_tag_map:
        if b in safety:
            std, saf = a, b
        elif a in safety:
            std, saf = b, a
        else:
            ctx.not_verified["WAR001"] = f"neither side of the safety mapping '{a}={b}' is a Safety-class tag"
            continue
        expected = STANDARD_PREFIX + (saf[len(SAFETY_PREFIX):] if saf.startswith(SAFETY_PREFIX) else saf)
        if std != expected:
            out.append(Finding("WAR001", f"Standard tag '{std}' is mapped to safety tag '{saf}' and must be named "
                                         f"'{expected}'.", f"Controller:{std}"))
    return out


@check("WAR002")
def produced_consumed_naming(ctx: Context) -> list[Finding]:
    tok = lambda s: re.compile(r"(?<![A-Za-z0-9])" + s + r"(?![A-Za-z0-9])")  # noqa: E731
    pro = tok("PRO")
    out = []
    for t in ctx.ctrl_tags.values():
        tt = t.tag_type.lower()
        if tt == "produced" and not pro.search(t.name):
            out.append(Finding("WAR002", f"Produced tag '{t.name}' has no 'PRO' in its name.", _where(t)))
        elif tt == "consumed" and t.remote_tag:
            if not pro.search(t.remote_tag):
                out.append(Finding("WAR002", f"Consumed tag '{t.name}' maps to '{t.remote_tag}', which has no 'PRO' "
                                             "in its name.", _where(t)))
                continue
            expected = pro.sub("CON", t.remote_tag)
            if t.name != expected:
                out.append(Finding("WAR002", f"Consumed tag '{t.name}' maps to '{t.remote_tag}' and must be named "
                                             f"'{expected}'.", _where(t)))
    return out


def _preset_of(t: TagInfo) -> dict[str, int] | None:
    if t.decorated_presets:
        return t.decorated_presets
    if t.datatype.upper() == "TIMER" and t.preset is not None and not t.dimensions:
        return {"": t.preset}
    return None


@check("WAR008")
def timer_preset(ctx: Context) -> list[Finding]:
    out = []
    for t in _user_tags(ctx):
        presets = _preset_of(t)
        if not presets:
            continue
        used, pre_written, any_var, pre_var = set(), set(), False, False
        for r in ctx.rungs:
            if t.scope != "controller" and r.owner != t.scope:
                continue
            if t.scope == "controller" and t.name in ctx.prog_tags.get(r.owner, {}):
                continue  # shadowed by a program tag of the same name
            for ins in walk(r.rung.body):
                for a, role in ctx.roles(ins):
                    m = re.match(r"\s*" + re.escape(t.name) + r"\s*(\[[^\]]*\])?(.*)$", a)
                    if not m or (m.group(2) and not m.group(2).startswith(".")):
                        continue
                    idx = re.sub(r"\s+", "", m.group(1) or "")
                    var = bool(idx) and not re.fullmatch(r"\[[\d,]+\]", idx)
                    if role == "write" and m.group(2).upper().startswith(".PRE"):
                        pre_written.add(idx)
                        pre_var = pre_var or var
                    used.add(idx)
                    any_var = any_var or var
        if not used or pre_var:
            continue  # unused is INF001's business; a write to Arr[i].PRE covers every element
        for ix, pre in sorted(presets.items()):
            if pre == 0 and (any_var or ix in used) and ix not in pre_written:
                out.append(Finding("WAR008", f"Timer '{t.name}{ix}' has preset 0 and logic never sets .PRE.",
                                   _where(t)))
    return out


@check("WAR016")
def small_integers(ctx: Context) -> list[Finding]:
    return [Finding("WAR016", f"'{t.name}' is {t.datatype.upper()}" + (f"[{t.dimensions}]" if t.dimensions else "")
                    + "; use DINT.", _where(t))
            for t in _user_tags(ctx) if t.tag_type.lower() != "alias" and t.datatype.upper() in ("INT", "SINT")]


def _used_operands(ctx: Context) -> set[str]:
    return {re.sub(r"\s+", "", a).upper() for r in ctx.rungs for ins in walk(r.rung.body) for a in ins.args}


@check("WAR019")
def used_but_spare(ctx: Context) -> list[Finding]:
    used = ctx.used_bases()
    ops = _used_operands(ctx)
    out = []
    for t in _user_tags(ctx):
        if t.name in used and _SPARE.search(t.description or ""):
            out.append(Finding("WAR019", f"'{t.name}' is used in logic but described as \"{(t.description or '')[:60]}\".",
                               _where(t)))
        for operand, text in t.comments.items():
            full = (t.name + operand).upper()
            if _SPARE.search(text or "") and any(o == full or o.startswith(full + ".") for o in ops):
                out.append(Finding("WAR019", f"'{t.name}{operand}' is used in logic but commented \"{text[:60]}\".",
                                   _where(t)))
    return out


def _used_in_scope(ctx: Context, t: TagInfo, cache: dict) -> bool:
    if t.scope == "controller":
        if "*" not in cache:
            cache["*"] = ctx.used_bases()
        return t.name in cache["*"]
    if t.scope not in cache:
        cache[t.scope] = ctx.used_bases(t.scope)
    return t.name in cache[t.scope]


@check("INF001")
def unused_tag(ctx: Context) -> list[Finding]:
    cache: dict = {}
    out = []
    for t in _user_tags(ctx):
        if t.tag_type.lower() in ("produced", "consumed") or _used_in_scope(ctx, t, cache):
            continue
        where = "anywhere in the project" if t.scope == "controller" else f"in program {t.scope}"
        msg = f"'{t.name}' is not used {where}."
        if (t.external_access or "").lower() not in ("", "none"):
            msg += f" (External access {t.external_access}: an HMI or SCADA may still use it.)"
        out.append(Finding("INF001", msg, _where(t)))
    return out


@check("INF002")
def loose_bools(ctx: Context, minimum: int = 1) -> list[Finding]:
    by_scope: dict[str, list[str]] = {}
    for t in _user_tags(ctx):
        if t.datatype.upper() == "BOOL" and not t.dimensions and t.tag_type.lower() != "alias":
            by_scope.setdefault(t.scope, []).append(t.name)
    out = []
    for scope, names in by_scope.items():
        if len(names) >= minimum:
            label = "Controller" if scope == "controller" else scope
            out.append(Finding("INF002", f"{len(names)} standalone BOOL tags in {label}: pack them into a DINT, "
                                         "a BOOL array or a UDT.", label,
                               ", ".join(names[:20]) + (" ..." if len(names) > 20 else "")))
    return out


@check("INF003")
def tag_description(ctx: Context) -> list[Finding]:
    cache: dict = {}
    ops = _used_operands(ctx)
    out = []
    for t in _user_tags(ctx):
        dt = t.datatype.upper()
        if not _used_in_scope(ctx, t, cache):
            continue
        if (not t.description and not t.dimensions and dt in _DESC_REQUIRED
                and t.tag_type.lower() != "alias"):
            out.append(Finding("INF003", f"'{t.name}' has no description.", _where(t)))
        if dt in _BIT_CAPABLE:  # bits that logic addresses one by one need a comment
            comments = {re.sub(r"\s+", "", k).upper() for k in t.comments}
            prefix = t.name.upper()
            bits = sorted({o[len(prefix):] for o in ops if o.startswith(prefix)
                           and re.fullmatch(r"(\[\d+(,\d+)*\])?\.\d+", o[len(prefix):])})
            for b in bits:
                if b not in comments:
                    out.append(Finding("INF003", f"'{t.name}{b}' has no comment.", _where(t)))
    return out
