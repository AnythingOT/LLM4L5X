"""Controller, task, program and AOI rules: they need the whole project."""

from __future__ import annotations

import re
from collections import defaultdict

from core.rung import base_tag, walk
from lint.context import Context, Finding
from lint.registry import check


@check("CRT001")
def forces(ctx: Context) -> list[Finding]:
    if ctx.project.has_forces:
        return [Finding("CRT001", "The project has forced tags. Remove every force before release.",
                        "Controller / Forces")]
    return []


@check("ERR007")
def controller_fault_handler(ctx: Context) -> list[Finding]:
    p = ctx.project
    mfp = p.major_fault_program
    if mfp is None:
        ctx.not_verified["ERR007"] = ("the export has no MajorFaultProgram attribute; check the Controller "
                                      "Fault Handler in Studio 5000")
        return []
    if not mfp:
        return [Finding("ERR007", "No Controller Fault Handler program: a major fault stops the controller "
                                  "with no recovery or logging logic.", f"Controller:{p.controller}")]
    if mfp not in {pr.name for pr in p.programs}:
        return [Finding("ERR007", f"The Controller Fault Handler is '{mfp}', which is not in the project.",
                        f"Controller:{p.controller}")]
    return []


def _handlers(ctx: Context) -> set[str]:
    return {ctx.project.major_fault_program, ctx.project.power_loss_program} - {None, ""}


@check("ERR008")
def program_fault_routine(ctx: Context) -> list[Finding]:
    out = []
    routines = defaultdict(set)
    for rt in ctx.project.routines:
        routines[rt.program].add(rt.name)
    for pr in ctx.project.programs:
        if pr.name in _handlers(ctx):
            continue
        if not pr.fault_routine:
            out.append(Finding("ERR008", f"Program '{pr.name}' has no Fault Routine.", f"Program:{pr.name}"))
        elif pr.fault_routine not in routines[pr.name]:
            out.append(Finding("ERR008", f"Program '{pr.name}' names fault routine '{pr.fault_routine}', "
                                         "which does not exist.", f"Program:{pr.name}"))
    return out


@check("ERR009")
def aoi_controller_tags(ctx: Context) -> list[Finding]:
    out = []
    for r in ctx.rungs:
        if not r.owner.startswith("AOI:"):
            continue
        local = ctx.aoi_scope.get(r.owner, {})
        reported = set()
        for ins in walk(r.rung.body):
            for a, role in ctx.roles(ins):
                if role in ("display", "other"):
                    continue
                b = base_tag(a)
                if b and b in ctx.ctrl_tags and b not in local and b not in reported:
                    reported.add(b)
                    out.append(Finding("ERR009", f"{r.owner} uses controller tag '{b}': pass it in as a parameter.",
                                       r.location))
    return out


@check("WAR003")
def task_period_name(ctx: Context) -> list[Finding]:
    out = []
    for t in ctx.project.tasks:
        if t.type != "PERIODIC" or not t.period:
            continue
        ms = t.period
        ms_s = str(int(ms)) if ms == int(ms) else str(ms)
        forms = [rf"(?<!\d){re.escape(ms_s)}\s*MS(?![A-Z])"]
        if ms >= 1000 and ms % 1000 == 0:
            forms.append(rf"(?<!\d){int(ms // 1000)}\s*S(?![A-Z])")
        if not any(re.search(f, t.name, re.I) for f in forms):
            out.append(Finding("WAR003", f"Periodic task '{t.name}' runs every {ms_s} ms but its name does not say "
                                         f"so (e.g. '{t.name}_{ms_s}MS').", f"Task:{t.name}"))
    return out


def _calls(ctx: Context) -> dict[tuple[str, str], set[str]]:
    """(owner, routine) -> routines it calls by JSR."""
    graph = defaultdict(set)
    for r in ctx.rungs:
        for ins in walk(r.rung.body):
            if ins.name.upper() in ("JSR", "JXR") and ins.args:
                graph[(r.owner, r.routine)].add(ins.args[0].strip())
    return graph


@check("WAR004")
def uncalled_routine(ctx: Context) -> list[Finding]:
    called = defaultdict(set)
    for (owner, _), targets in _calls(ctx).items():
        called[owner] |= targets
    st_names = set(re.findall(r"[A-Za-z_]\w*", ctx.usage_text))
    out = []
    for pr in ctx.project.programs:
        entry = {pr.main_routine, pr.fault_routine}
        for rt in ctx.project.routines:
            if rt.program != pr.name or rt.protected:
                continue
            if rt.name not in entry and rt.name not in called[pr.name] and rt.name not in st_names:
                out.append(Finding("WAR004", f"Routine '{rt.name}' is never called: not the main or fault routine "
                                             "and no JSR to it.", f"{pr.name} / {rt.name}"))
    return out


@check("WAR005")
def unscheduled_program(ctx: Context) -> list[Finding]:
    scheduled = {p for t in ctx.project.tasks for p in t.programs}
    children = {p.name: p.children for p in ctx.project.programs}
    stack = list(scheduled)
    while stack:  # child programs run under their parent
        for c in children.get(stack.pop(), []):
            if c not in scheduled:
                scheduled.add(c)
                stack.append(c)
    return [Finding("WAR005", f"Program '{p.name}' is not scheduled in any task, so it never runs.",
                    f"Program:{p.name}")
            for p in ctx.project.programs if p.name not in scheduled and p.name not in _handlers(ctx)]


@check("WAR009")
def watchdog(ctx: Context) -> list[Finding]:
    out = []
    for t in ctx.project.tasks:
        if t.type != "PERIODIC" or not t.period or t.watchdog is None:
            continue
        if t.watchdog <= t.period:
            out.append(Finding("WAR009", f"Watchdog {t.watchdog:g} ms is not more than the period {t.period:g} ms: "
                                         f"any overrun faults. Suggest about {t.period * 2:g} ms.", f"Task:{t.name}"))
        elif t.watchdog < 1.5 * t.period:
            out.append(Finding("WAR009", f"Watchdog {t.watchdog:g} ms leaves less than 50% margin over the period "
                                         f"{t.period:g} ms. Suggest about {t.period * 2:g} ms.", f"Task:{t.name}"))
    return out


@check("WAR014")
def jsr_depth(ctx: Context, limit: int = 4) -> list[Finding]:
    graph = _calls(ctx)
    out = []

    def depth(owner, node, path):
        if node in path:  # recursion: stop rather than loop
            return 0
        return 1 + max((depth(owner, c, path | {node}) for c in graph.get((owner, node), ())), default=0)

    for pr in ctx.project.programs:
        if pr.main_routine and depth(pr.name, pr.main_routine, frozenset()) > limit:
            out.append(Finding("WAR014", f"The JSR chain from '{pr.main_routine}' is more than {limit} levels deep.",
                               f"{pr.name} / {pr.main_routine}"))
    return out


@check("INF004")
def rung_comment(ctx: Context) -> list[Finding]:
    return [Finding("INF004", "Rung has no comment.", r.location)
            for r in ctx.rungs if not (r.comment or "").strip()]


@check("INF005")
def aoi_descriptions(ctx: Context) -> list[Finding]:
    out = []
    for a in ctx.project.aois.values():
        if not a.description:
            out.append(Finding("INF005", f"AOI '{a.name}' has no description.", f"AOI:{a.name}"))
        for prm in a.params:
            if prm.name in ("EnableIn", "EnableOut"):
                continue
            if not prm.description:
                out.append(Finding("INF005", f"Parameter '{prm.name}' of AOI '{a.name}' has no description.",
                                   f"AOI:{a.name}"))
    return out
