"""Energize: run a whole program with its plant, live, before any controller is involved.

Every routine runs once per scan, in file order, with Sim_Mode = 1. MAP_IN and MAP_OUT are skipped:
in simulation the plant model owns the mapped inputs and the field outputs stay off. A rung that only
calls a subroutine (JSR) is skipped too, because every routine already runs each scan. Any other
instruction the simulator does not know stops the load with a list, rather than being skipped
quietly: a missing instruction would make the program look like it works when it does not.

This module has no Flask: the page (and tests) drive it through load, step and run_scenarios.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core import simulator as sim
from core.rung import Instr, Rung, base_tag, is_literal, walk
from l5x.reader import read_l5x
from scenario import SimBackend, parse_scenarios, report, run_scenarios, trace

SKIPPED_ROUTINES = {"MAP_IN", "MAP_OUT"}
_CALLS = {"JSR", "SBR", "RET"}
_SUPPORTED = set(sim._HANDLERS) | set(sim._COMPARE) | set(sim._MATH) | set(sim._V36)
_STRUCTS = {"TON", "TOF", "RTO", "CTU", "CTD"}
_FIRST_ARG_WRITES = {"OTE", "OTL", "OTU", "TON", "TOF", "RTO", "CTU", "CTD", "RES", "ONS", "CLR"}


class EnergizeError(ValueError):
    pass


def _writes(i: Instr) -> list[str]:
    n = sim._V36.get(i.name.upper(), i.name.upper())
    if n in _FIRST_ARG_WRITES and i.args:
        return [i.args[0]]
    if n in sim._MATH and len(i.args) > 2:
        return [i.args[2]]
    if n in ("MOV", "COP") and len(i.args) > 1:
        return [i.args[1]]
    return []


@dataclass
class Place:
    routine: str
    number: int  # rung number in its routine
    text: str


@dataclass
class Session:
    rungs: list[Rung]
    places: list[Place]
    inputs: list[str]  # read by the logic, written by nobody: the user (or a test) drives them
    outputs: list[str]  # written by the logic
    feedbacks: list[str]  # written by the plant
    skipped: list[str] = field(default_factory=list)
    plant_text: str = ""
    scenarios_text: str = ""
    scan_ms: float = 10.0
    watched: list[str] = field(default_factory=list)  # other tags the page shows live: contacts, coils, presets
    backend: SimBackend | None = None
    presets: dict = field(default_factory=dict)  # {"T.PRE": 5000} from the tags' data: rungs may show "?"

    def _new_backend(self) -> SimBackend:
        from plant import load_plant
        plant = load_plant(self.plant_text) if self.plant_text.strip() else None
        be = SimBackend(self.rungs, {**self.presets, "Sim_Mode": 1}, plant, self.scan_ms)
        be.sim.trace = True  # the page draws where power flows in each rung
        return be

    def reset(self) -> dict:
        self.backend = self._new_backend()
        return self.snapshot()

    def step(self, ms: float = 0, writes: dict | None = None) -> dict:
        """Apply the user's writes, let ms pass (at least one scan), return what the page shows."""
        be = self.backend or self._new_backend()
        self.backend = be
        for tag, value in (writes or {}).items():
            if not be.has(tag):
                raise EnergizeError(f"{tag} is not used by this program or plant")
            if tag in self.outputs or base_tag(tag) in {base_tag(o) for o in self.outputs}:
                raise EnergizeError(f"{tag} is written by the logic; a value set here would be overwritten")
            be.write(tag, value)
        be.advance(ms)
        return self.snapshot()

    def snapshot(self) -> dict:
        be = self.backend
        tags = {t: be.read(t) for t in self.inputs + self.outputs + self.feedbacks + self.watched}
        return {"now_ms": be.now_ms, "tags": tags, "power": list(be.sim.power), "flow": list(be.sim.flow),
                "notes": be.plant.notes() if be.plant else []}

    def results(self) -> list:
        """Every test case on a fresh program and device models: the live session is left as it is."""
        return run_scenarios(parse_scenarios(self.scenarios_text), self._new_backend)

    def run_scenarios(self) -> dict:
        """Every scenario on a fresh program and plant: the live session is left as it is."""
        results = self.results()
        return {"passed": sum(r.passed for r in results), "total": len(results),
                "report": report(results), "trace": trace(results),
                "results": [{"id": r.id, "title": r.title, "reqs": list(r.reqs), "passed": r.passed,
                             "error": r.error} for r in results]}


def load(l5x_files: list[str | bytes], plant_text: str = "", scenarios_text: str = "", scan_ms: float = 10.0
         ) -> Session:
    from core.rung import format_rung
    rungs, places, skipped, unsupported = [], [], [], []
    presets: dict[str, int] = {}
    for data in l5x_files:
        project = read_l5x(data)
        # a timer or counter keeps its preset in the tag: an export (v36 and later) writes TON(T,?,?) in the rung
        presets.update({f"{name}.PRE": pre for name, pre in project.presets().items()})
        for rt in project.routines:
            if rt.name.upper() in SKIPPED_ROUTINES:
                skipped.append(f"{rt.name}: not run in simulation (Sim_Mode = 1)")
                continue
            for n, info in enumerate(rt.rungs):
                r = info.rung
                if r is None:
                    unsupported.append(f"{rt.name} rung {n}: could not be read")
                    continue
                names = {i.name.upper() for i in walk(r.body)}
                if names & _CALLS:
                    if names - _CALLS <= {"XIC", "XIO"}:
                        skipped.append(f"{rt.name} rung {n}: subroutine call (every routine runs each scan)")
                        continue
                bad = sorted(names - _SUPPORTED)
                if bad:
                    unsupported.append(f"{rt.name} rung {n}: {', '.join(bad)}")
                    continue
                rungs.append(r)
                places.append(Place(rt.name, n, format_rung(r)))
    if unsupported:
        raise EnergizeError("the simulator cannot run every rung, so it would not behave like the controller: "
                            + "; ".join(unsupported[:10]) + (" ..." if len(unsupported) > 10 else ""))
    if not rungs:
        raise EnergizeError("no ladder rungs to run")
    written = {base_tag(w) for r in rungs for i in walk(r.body) for w in _writes(i) if not is_literal(w)}
    # a timer or counter is a structure: its elapsed/count and done bits are what a person watches
    structs = {i.args[0] for r in rungs for i in walk(r.body)
               if sim._V36.get(i.name.upper(), i.name.upper()) in _STRUCTS and i.args}
    read = {base_tag(a) for r in rungs for i in walk(r.body) for a in i.args if not is_literal(a)}
    outputs = sorted(t for t in written if t not in structs) + [f"{t}.{m}" for t in sorted(structs)
                                                                for m in ("ACC", "DN")]
    s = Session(rungs, places, [], outputs, [], skipped, plant_text, scenarios_text, scan_ms, presets=presets)
    probe = s._new_backend()  # validates the plant and scenarios before the page shows anything
    if scenarios_text.strip():
        parse_scenarios(scenarios_text)
    s.feedbacks = sorted(probe.plant.feedbacks()) if probe.plant else []
    s.inputs = sorted(read - written - set(s.feedbacks) - {"Sim_Mode"} - {None})
    s.backend = probe
    return s


_BIT_INSTR = {"XIC", "XIO", "OTE", "OTL", "OTU", "ONS"}
_BIT_MEMBERS = {"DN", "EN", "TT", "CU", "CD", "OV", "UN"}


def view(ses: Session, l5x_files: list[str | bytes]) -> dict:
    """What the page needs besides the snapshot: each tag's kind, the timers and counters, rung drawings.

    kind: "BOOL" (a switch or a lamp) or "NUM" (a number). A tag's own data type wins; a tag the files do not
    declare is a bit if the logic uses it as one (a contact or a coil), otherwise a number.
    """
    from explain.ladder import to_svg
    types: dict[str, str] = {}
    for data in l5x_files:
        types.update({t.name: t.datatype.upper() for t in read_l5x(data).tags.values() if t.datatype})
    bits, structs = set(), {}
    for r in ses.rungs:
        for i in walk(r.body):
            n = sim._V36.get(i.name.upper(), i.name.upper())
            if n in _BIT_INSTR and i.args and not is_literal(i.args[0]):
                bits.add(i.args[0])
            if n in _STRUCTS and i.args:
                structs[i.args[0]] = "COUNTER" if n in ("CTU", "CTD") else "TIMER"

    def kind(tag: str) -> str:
        if "." in tag and base_tag(tag) in structs:
            return "BOOL" if tag.rsplit(".", 1)[1].upper() in _BIT_MEMBERS else "NUM"
        t = types.get(tag) or types.get(base_tag(tag))
        if t:
            return "BOOL" if t == "BOOL" else "NUM"
        return "BOOL" if tag in bits else "NUM"

    shown = set(ses.inputs + ses.outputs + ses.feedbacks)
    ses.watched = sorted((bits - shown) | {f"{t}.PRE" for t in structs})
    be = ses.backend
    presets = {t: be.read(f"{t}.PRE") for t in structs}
    svgs = []
    for r, p in zip(ses.rungs, ses.places):
        try:
            svgs.append(to_svg(r, number=p.number, presets=presets))
        except Exception:  # noqa: BLE001 - a rung the drawing cannot lay out still runs; the page shows its text
            svgs.append(None)
    return {"kinds": {t: kind(t) for t in sorted(shown | set(ses.watched))},
            "structs": [{"name": t, "kind": k} for t, k in sorted(structs.items())],
            "svgs": svgs, "snapshot": ses.snapshot()}
