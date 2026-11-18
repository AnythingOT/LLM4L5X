"""Data type rules: padding, member order, unused definitions, member descriptions."""

from __future__ import annotations

from core.rung import walk
from lint import udt_layout
from lint.context import Context, Finding
from lint.registry import check
from lint.udt_layout import HOST_PREFIX, M, natural_key


def _user_udts(ctx: Context):
    """User data types; string types are laid out by Studio 5000 and left alone."""
    return {n: d for n, d in ctx.project.datatypes.items() if (d.family or "NoFamily") != "StringFamily"}


def _members(d) -> list[M]:
    return [M(m.name, m.datatype, m.dimension) for m in d.members if not m.name.startswith(HOST_PREFIX)]


@check("WAR010")
def udt_padding(ctx: Context) -> list[Finding]:
    types = {n: _members(d) for n, d in _user_udts(ctx).items()}
    if not types:
        return []
    aoi_sizes = {a.name: udt_layout.size_of([M(p.name, p.datatype or "DINT") for p in a.params], {})
                 for a in ctx.project.aois.values()}
    try:
        results = udt_layout.analyse(types, aoi_sizes)
    except ValueError as e:
        ctx.not_verified["WAR010"] = str(e)
        return []
    out = []
    for r in results:
        if r.unknown_types:
            ctx.not_verified.setdefault("WAR010", f"'{r.name}' uses types not defined in this export "
                                                  f"({', '.join(r.unknown_types[:4])}); export the full project")
        saved = r.size_now - r.size_best
        if r.order_changes and saved >= 4:
            out.append(Finding("WAR010", f"'{r.name}' is {r.size_now} bytes; ordering its members by type would make "
                                         f"it {r.size_best} bytes ({saved} bytes saved).", f"DataType:{r.name}"))
    return out


@check("WAR011")
def udt_member_order(ctx: Context) -> list[Finding]:
    out = []
    for name, d in _user_udts(ctx).items():
        mem = [m for m in d.members if not m.hidden]
        if len(mem) < 2:
            continue
        groups: dict[tuple, list[str]] = {}
        seen, cur, split = set(), None, False
        for m in mem:
            k = ("BOOL" if m.datatype.upper() == "BIT" else m.datatype.upper(), m.dimension > 0)
            groups.setdefault(k, []).append(m.name)
            if k != cur:
                split = split or k in seen
                seen.add(k)
                cur = k
        unsorted = any(n != sorted(n, key=natural_key) for n in groups.values())
        why = (["members of one data type are not together"] if split else []) + \
              (["members are not in natural alphabetical order"] if unsorted else [])
        if why:
            out.append(Finding("WAR011", f"'{name}': " + "; ".join(why) + ".", f"DataType:{name}"))
    return out


@check("WAR020")
def unused_definitions(ctx: Context) -> list[Finding]:
    p = ctx.project
    used = {t.datatype.upper() for t in p.tags.values() if t.datatype}
    used |= {m.datatype.upper() for d in p.datatypes.values() for m in d.members}
    for a in p.aois.values():
        used |= {(prm.datatype or "").upper() for prm in a.params}
        used |= {t.datatype.upper() for t in a.local_tags if t.datatype}
    called = {ins.name.upper() for r in ctx.rungs for ins in walk(r.rung.body)}
    st = ctx.usage_text.upper()
    out = []
    for name in _user_udts(ctx):
        if name.upper() not in used:
            out.append(Finding("WAR020", f"UDT '{name}' is not used anywhere.", f"DataType:{name}"))
    for name in p.aois:
        if name.upper() not in used and name.upper() not in called and name.upper() + "(" not in st:
            out.append(Finding("WAR020", f"AOI '{name}' is defined but never used.", f"AOI:{name}"))
    return out


@check("INF006")
def udt_member_description(ctx: Context) -> list[Finding]:
    return [Finding("INF006", f"Member '{name}.{m.name}' has no description.", f"DataType:{name}")
            for name, d in _user_udts(ctx).items() for m in d.members
            if not m.hidden and not (m.description or "").strip()]
