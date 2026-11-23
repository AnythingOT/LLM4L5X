"""A company coding-standards profile: rules that differ per company, checked like any other rule.

    name: Example Co.
    naming:                       # data type -> pattern the tag name must match ("any" = every tag)
      TIMER: '_(TMR|TON|TOF)$'
      COUNTER: '_CTR$'
      any: '^[A-Z]'
    banned_instructions: [JMP, LBL]
    restricted:                   # instruction -> pattern its first operand must match
      OTL: '_(ALM|Fail)$'         # latches only for alarms and faults
    rung_comments: required
    disabled_rules: [INF004]

A profile adds rules (STD001-STD004) and switches rules off; it cannot soften a code: a code means
the same thing in every report, whichever company ran it. Loose rungs (generated logic) are checked
for naming on the tags they use; a project export on the tags it defines.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

from core.rung import base_tag, is_literal, walk

from .context import Context, Finding

_KEYS = {"name", "naming", "banned_instructions", "restricted", "rung_comments", "disabled_rules"}


class ProfileError(ValueError):
    pass


@dataclass
class Profile:
    name: str = ""
    naming: dict[str, re.Pattern] = field(default_factory=dict)  # DATATYPE or "ANY" -> pattern
    banned: set[str] = field(default_factory=set)
    restricted: dict[str, re.Pattern] = field(default_factory=dict)
    rung_comments: bool = False
    disabled_rules: set[str] = field(default_factory=set)


def _rx(text, where: str) -> re.Pattern:
    try:
        return re.compile(str(text))
    except re.error as e:
        raise ProfileError(f"{where}: {text!r} is not a valid pattern ({e})") from None


def load_profile(text: str) -> Profile:
    try:
        d = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise ProfileError(f"profile is not valid YAML: {e}") from None
    if not isinstance(d, dict):
        raise ProfileError("a profile is a set of keys: " + ", ".join(sorted(_KEYS)))
    if "severity" in d or "severities" in d:
        raise ProfileError("severity cannot be changed: a code means the same thing in every report "
                           "(switch a rule off with disabled_rules instead)")
    extra = set(d) - _KEYS
    if extra:
        raise ProfileError(f"unknown {', '.join(sorted(extra))}; a profile has {', '.join(sorted(_KEYS))}")
    p = Profile(str(d.get("name") or ""))
    for kind, pat in (d.get("naming") or {}).items():
        p.naming[str(kind).upper()] = _rx(pat, f"naming {kind}")
    p.banned = {str(i).upper() for i in d.get("banned_instructions") or []}
    for ins, pat in (d.get("restricted") or {}).items():
        p.restricted[str(ins).upper()] = _rx(pat, f"restricted {ins}")
    rc = d.get("rung_comments")
    if rc not in (None, "required", "optional", True, False):
        raise ProfileError("rung_comments: required or optional")
    p.rung_comments = rc in ("required", True)
    from .rules import BY_CODE
    p.disabled_rules = {str(c).upper() for c in d.get("disabled_rules") or []}
    unknown = sorted(p.disabled_rules - set(BY_CODE) - set(PROFILE_CODES))
    if unknown:
        raise ProfileError(f"disabled_rules: no such rule {', '.join(unknown)}")
    return p


PROFILE_CODES = {  # code -> (severity, title)
    "STD001": ("warning", "Tag name does not follow the naming standard"),
    "STD002": ("error", "Instruction banned by the coding standard"),
    "STD003": ("error", "Instruction used outside what the standard allows"),
    "STD004": ("warning", "Rung without a comment"),
}


def _naming(p: Profile, name: str, datatype: str) -> str | None:
    for key in (datatype.upper(), "ANY"):
        pat = p.naming.get(key)
        if pat and not pat.search(name):
            return f"{name} ({datatype}) does not match the {key.lower()} pattern {pat.pattern!r}"
    return None


def check_profile(ctx: Context, p: Profile, defined_only: bool = True) -> list[Finding]:
    out: list[Finding] = []
    on = {c for c in PROFILE_CODES if c not in p.disabled_rules}
    if "STD001" in on and p.naming:
        if defined_only:  # a project: the tags it defines
            tags = [(t, "Controller") for t in ctx.ctrl_tags.values()] + \
                   [(t, prog) for prog, ts in ctx.prog_tags.items() for t in ts.values()]
            for t, where in tags:
                if ":" in t.name:
                    continue  # module tags are named by Logix, not by the programmer
                why = _naming(p, t.name, t.datatype)
                if why:
                    out.append(Finding("STD001", why, f"{where} / Tag {t.name}"))
        else:  # loose rungs: the tags they use, typed where known
            seen = set()
            for ref in ctx.rungs:
                for i in walk(ref.rung.body):
                    for a in i.args:
                        b = base_tag(a) if not is_literal(a) else None
                        if not b or b in seen or ":" in b:
                            continue
                        seen.add(b)
                        t = ctx.tag(b, ref.owner)
                        why = _naming(p, b, t.datatype if t else "any")
                        if why:
                            out.append(Finding("STD001", why, ref.location))
    for ref in ctx.rungs:
        for i in walk(ref.rung.body):
            n = i.name.upper()
            if "STD002" in on and n in p.banned:
                out.append(Finding("STD002", f"{i.name} is banned by the {p.name or 'company'} standard",
                                   ref.location))
            pat = p.restricted.get(n)
            if "STD003" in on and pat and i.args and not pat.search(i.args[0]):
                out.append(Finding("STD003", f"{i.name}({i.args[0]}): the standard allows {i.name} only on "
                                             f"operands matching {pat.pattern!r}", ref.location))
        if "STD004" in on and p.rung_comments and not (ref.comment or "").strip():
            out.append(Finding("STD004", "rung has no comment; the standard requires one", ref.location))
    return out
