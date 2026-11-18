"""Physical I/O rules: unmapped points, aliases, point comments, electronic keying."""

from __future__ import annotations

import re

from l5x.reader import ModuleInfo
from lint.context import Context, Finding
from lint.registry import check

IO_CATALOG = re.compile(r"^(1756|1769|1734|1794|5069|5094)-(I|O)")


def io_tag_name(m: ModuleInfo, suffix: str) -> str:
    """Logix name of a module I/O tag: Ethernet modules use their own name (Drive1:I),
    backplane modules the chassis owner and slot (Local:4:I, or <adapter>:4:I remotely)."""
    if (m.upstream_type or "").lower() == "ethernet" or m.slot is None:
        prefix = m.name
    else:
        parent = m.parent or "Local"
        prefix = f"Local:{m.slot}" if parent == "Local" else f"{parent}:{m.slot}"
    return f"{prefix}:{suffix}"


def _point_count(catalog: str) -> int:
    """Digital points from the catalog number: 1756-IB16 -> 16."""
    m = re.search(r"-[A-Z]+(\d+)", catalog.upper())
    return int(m.group(1)) if m else 0


def _points(m: ModuleInfo, data_members: list[str]) -> list[str]:
    pts = []
    for mem in data_members:
        if mem.lower() == "data":
            n = _point_count(m.catalog)
            pts += [f".{mem}.{b}" for b in range(n)] if n else [f".{mem}"]
        else:
            pts.append(f".{mem}")
    return pts


def _io_tags(ctx: Context):
    for m in ctx.project.modules:
        if IO_CATALOG.search(m.catalog):
            for io in m.io_tags:
                name = io_tag_name(m, io.suffix)
                yield m, io, name, name.upper()


def _aliases(ctx: Context) -> list[tuple[str, str, str]]:
    """(alias, scope label, resolved target in upper case); alias chains followed."""
    raw = {t.name.upper(): t.alias_for for t in ctx.ctrl_tags.values() if t.alias_for}
    entries = [(t.name, "Controller" if t.scope == "controller" else t.scope, t.alias_for)
               for t in ctx.project.tags.values() if t.alias_for]

    def resolve(target: str, depth: int = 0) -> str:
        tgt = re.sub(r"\s+", "", target)
        base = re.split(r"[.\[]", tgt, maxsplit=1)[0].upper()
        if depth < 10 and base in raw:
            return resolve(raw[base] + tgt[len(base):], depth + 1)
        return tgt.upper()

    return [(n, sc, resolve(a)) for n, sc, a in entries]


def _direct_refs(corpus_upper: str, name_u: str) -> set[str]:
    pat = re.compile(r"(?<![\w:])" + re.escape(name_u) + r"((?:\.[A-Z0-9_]+|\[[^\]]*\])*)(?![\w:])")
    return set(pat.findall(corpus_upper))


def _alias_cover(aliases, name_u: str) -> set[str]:
    return {tgt[len(name_u):] for _n, _s, tgt in aliases
            if tgt == name_u or tgt.startswith(name_u + ".") or tgt.startswith(name_u + "[")}


def _covers(point_u: str, refs: set[str]) -> bool:
    """A point is covered by a reference to it or to anything that contains it."""
    if point_u in refs or "" in refs:
        return True
    parts = point_u.split(".")
    return any(".".join(parts[:i]) in refs for i in range(2, len(parts)))


@check("WAR017")
def io_unmapped(ctx: Context) -> list[Finding]:
    corpus = ctx.corpus().upper()
    aliases = _aliases(ctx)
    out = []
    for m, io, name, name_u in _io_tags(ctx):
        direct, aliased = _direct_refs(corpus, name_u), _alias_cover(aliases, name_u)
        for pt in _points(m, io.data_members):
            if not _covers(pt.upper(), direct) and not _covers(pt.upper(), aliased):
                out.append(Finding("WAR017", "No logic references this I/O point directly.", f"IO:{name}{pt}"))
    return out


@check("WAR018")
def io_without_comment(ctx: Context) -> list[Finding]:
    corpus = ctx.corpus().upper()
    out = []
    for m, io, name, name_u in _io_tags(ctx):
        direct = _direct_refs(corpus, name_u)
        for pt in _points(m, io.data_members):
            if pt.upper() in direct and pt.upper() not in io.comments:
                out.append(Finding("WAR018", "This I/O point is used but has no comment.", f"IO:{name}{pt}"))
    return out


@check("WAR022")
def io_alias(ctx: Context) -> list[Finding]:
    names = [(n, nu) for _m, _io, n, nu in _io_tags(ctx)]
    corpus = ctx.corpus()
    out = []
    for alias, scope, tgt in _aliases(ctx):
        hit = next((n for n, nu in names if tgt == nu or tgt.startswith(nu + ".") or tgt.startswith(nu + "[")), None)
        if not hit:
            continue
        used = re.search(r"(?<![\w.:])" + re.escape(alias) + r"(?![\w])", corpus) is not None
        target = hit + tgt[len(hit):].replace(".DATA", ".Data")
        why = "is used in logic: replace it with direct mapping." if used else "is not used in logic: delete it."
        out.append(Finding("WAR022", f"Alias '{alias}' -> {target} {why}", f"{scope}:{alias}"))
    return out


@check("INF008")
def electronic_keying(ctx: Context) -> list[Finding]:
    out = []
    for m in ctx.project.modules:
        if m.ekey is None or m.name == "Local":
            continue  # nothing exported / the controller itself
        if re.sub(r"[\s_]", "", m.ekey).lower() != "compatiblemodule":
            out.append(Finding("INF008", f"Module '{m.name}' ({m.catalog}) has keying '{m.ekey}'; use Compatible "
                                         "Module.", f"Module:{m.name}"))
    return out
