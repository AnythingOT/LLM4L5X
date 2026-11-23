"""Run scenarios on a Backend and record what happened, step by step."""

from __future__ import annotations

from dataclasses import dataclass, field

from .dsl import Scenario, Step

MAX_CALL_DEPTH = 8


@dataclass
class StepResult:
    line: int
    phase: str
    action: str
    text: str
    passed: bool | None  # None: SET, WAIT, COMMENT (nothing to judge)
    actual: object = None
    t_ms: float = 0.0  # scenario time when it passed or failed
    message: str = ""


@dataclass
class ScenarioResult:
    id: str
    title: str
    reqs: tuple[str, ...]
    steps: list[StepResult] = field(default_factory=list)
    error: str = ""  # could not run at all (unknown tags)

    @property
    def passed(self) -> bool:
        return not self.error and all(s.passed is not False for s in self.steps)

    @property
    def teardown_failed(self) -> bool:
        return any(s.phase == "TEARDOWN" and s.passed is False for s in self.steps)


def _num(v):
    return int(v) if isinstance(v, bool) else v


def _holds(actual, op: str, want, tol: float) -> bool:
    a, w = _num(actual), _num(want)
    if isinstance(w, str) or isinstance(a, str):
        a, w = str(a or "none"), str(w)
        return a == w if op == "==" else a != w if op == "!=" else False
    if op == "==":
        return abs(a - w) <= tol
    if op == "!=":
        return abs(a - w) > tol
    return {"<": a < w, "<=": a <= w + tol, ">": a > w, ">=": a >= w - tol}[op]


def _tags(sc: Scenario, by_id: dict[str, Scenario], depth: int = 0) -> set[str]:
    out = {st.tag for st in sc.steps if st.tag}
    if depth < MAX_CALL_DEPTH:
        for st in sc.steps:
            if st.action == "CALL":
                out |= _tags(by_id[st.text], by_id, depth + 1)
    return out


def _flat(sc: Scenario, by_id: dict[str, Scenario], phase: str, stack: tuple[str, ...]) -> list[Step]:
    """Steps of one phase with CALLs inlined (a called scenario contributes all its steps, in phase order)."""
    out = []
    for st in sc.steps:
        if st.phase != phase:
            continue
        if st.action != "CALL":
            out.append(st)
            continue
        if st.text in stack or len(stack) >= MAX_CALL_DEPTH:
            raise RecursionError(f"CALL {st.text} loops: {' -> '.join(stack + (st.text,))}")
        called = by_id[st.text]
        for ph in ("SETUP", "MAIN", "TEARDOWN"):
            for inner in _flat(called, by_id, ph, stack + (st.text,)):
                out.append(Step(**{**inner.__dict__, "phase": phase}))
    return out


def _run_step(st: Step, be, t0: float) -> StepResult:
    r = StepResult(st.line, st.phase, st.action, st.text or st.action, None)
    try:
        if st.action in ("SET", "RESET"):
            be.write(st.tag, st.value)
        elif st.action == "WAIT":
            be.advance(float(st.value))
        elif st.action == "COMMENT":
            r.text = st.text
        elif st.action == "EXPECT":
            if st.within_ms is None:  # one scan so the logic sees earlier writes, then one read
                be.advance(0)
                r.actual = be.read(st.tag)
                r.passed = _holds(r.actual, st.op, st.value, st.tolerance)
            else:
                end = be.now_ms + st.within_ms
                while True:
                    r.actual = be.read(st.tag)
                    ok = _holds(r.actual, st.op, st.value, st.tolerance)
                    if st.hold and not ok:
                        r.passed, r.message = False, f"did not hold: changed after {be.now_ms - (end - st.within_ms):.0f} ms"
                        break
                    if not st.hold and ok:
                        r.passed, r.message = True, f"after {be.now_ms - (end - st.within_ms):.0f} ms"
                        break
                    if be.now_ms >= end:
                        r.passed = st.hold
                        r.message = f"held {st.within_ms:.0f} ms" if st.hold else f"not within {st.within_ms:.0f} ms"
                        break
                    be.advance(0)
            if r.passed is False and not r.message:
                r.message = f"expected {st.tag} {st.op} {st.value}, got {r.actual}"
            elif r.passed is False:
                r.message = f"expected {st.tag} {st.op} {st.value}, got {r.actual}: {r.message}"
    except Exception as e:  # a plant fault name, a simulator error: the step fails, teardown still runs
        r.passed, r.message = False, f"{type(e).__name__}: {e}"
    r.t_ms = round(be.now_ms - t0, 1)
    return r


def run_scenario(sc: Scenario, be, scenarios: list[Scenario] | None = None, stop_on_fail: bool = True
                 ) -> ScenarioResult:
    by_id = {s.id: s for s in (scenarios or [])} | {sc.id: sc}
    res = ScenarioResult(sc.id, sc.title, sc.reqs)
    missing = sorted(t for t in _tags(sc, by_id) if not be.has(t))
    if missing:  # before touching anything: a typo must not pass a negative test
        res.error = f"unknown tags: {', '.join(missing)}"
        return res
    try:
        phases = {ph: _flat(sc, by_id, ph, (sc.id,)) for ph in ("SETUP", "MAIN", "TEARDOWN")}
    except RecursionError as e:
        res.error = str(e)
        return res
    t0 = be.now_ms
    ok = True
    for ph in ("SETUP", "MAIN"):
        if not ok:
            res.steps.append(StepResult(0, ph, "SKIP", f"{ph} skipped after a failure", None))
            continue
        for st in phases[ph]:
            r = _run_step(st, be, t0)
            res.steps.append(r)
            if r.passed is False and (stop_on_fail or ph == "SETUP"):
                ok = False
                break
    for st in phases["TEARDOWN"]:  # always: a failed test must not leave the plant in an unsafe state
        res.steps.append(_run_step(st, be, t0))
    return res


def run_scenarios(scenarios: list[Scenario], make_backend, stop_on_fail: bool = True) -> list[ScenarioResult]:
    """Each scenario on a fresh backend: one test's leftovers cannot pass or fail the next."""
    return [run_scenario(sc, make_backend(), scenarios, stop_on_fail) for sc in scenarios]


def trace(results: list[ScenarioResult]) -> dict[str, list[tuple[str, bool]]]:
    """Requirement -> [(scenario id, passed)]: the scenario half of a traceability matrix."""
    out: dict[str, list[tuple[str, bool]]] = {}
    for r in results:
        for req in r.reqs:
            out.setdefault(req, []).append((r.id, r.passed))
    return out


def report(results: list[ScenarioResult]) -> list[str]:
    lines = []
    for r in results:
        head = "PASS" if r.passed else "FAIL"
        lines.append(f"{head}  {r.id} {r.title}".rstrip() + (f"  [{', '.join(r.reqs)}]" if r.reqs else ""))
        if r.error:
            lines.append(f"      cannot run: {r.error}")
        for s in r.steps:
            if s.passed is False:
                lines.append(f"      line {s.line} {s.phase} at {s.t_ms:.0f} ms: {s.text}  ->  {s.message}")
        if r.teardown_failed:
            lines.append("      WARNING: teardown failed; the plant may not be back to normal")
    t = trace(results)
    if t:
        lines.append("")
        lines.append("Requirements by scenario:")
        for req, rows in t.items():
            verdict = "passes" if all(p for _, p in rows) else "FAILS"
            lines.append(f"  {req}: {verdict} ({', '.join(f'{i} {chr(10003) if p else chr(10007)}' for i, p in rows)})")
    return lines
