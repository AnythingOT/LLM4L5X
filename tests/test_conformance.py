"""The conformance run (simulator against Logix Emulate) works end to end, here with a stand-in for Emulate."""
from types import SimpleNamespace

from eval import conformance as cf
from l5x.reader import read_l5x
from testcases.emulate import EmulateBackend, EmulateError


class FakeEmulate:
    """pylogix's PLC as Emulate would answer, played by our simulator on a clock the test controls."""

    def __init__(self, case=None):
        self.sims = [cf.sim_backend(c) for c in cf.CASES]
        self.t = 0.0
        self.flip = set()  # tags whose value this "controller" reports differently, to see a difference caught

    def _owner(self, tag):
        return next((s for s in self.sims if s.has(tag)), None)

    def Read(self, tag):  # noqa: N802 - pylogix's name
        s = self._owner(tag)
        if s is None:
            return SimpleNamespace(Value=None, Status="Path destination unknown")
        v = s.read(tag)
        return SimpleNamespace(Value=(not v) if tag in self.flip else v, Status="Success")

    def Write(self, tag, value):  # noqa: N802
        s = self._owner(tag)
        if s is None:
            return SimpleNamespace(Status="Path destination unknown")
        s.write(tag, value)
        return SimpleNamespace(Status="Success")

    def clock(self):
        return self.t

    def sleep(self, seconds):
        for s in self.sims:
            s.advance(seconds * 1000)
        self.t += seconds


def test_every_case_runs_on_the_simulator_and_agrees_with_itself():
    sim = cf.run_all(cf.sim_backend)
    rows = cf.compare(sim, sim)
    assert len(rows) == len(cf.CASES) and all(r["differ"] == 0 and r["values"] for r in rows)
    assert sim["ton"][1] == [1, 0, 1, 1000] and sim["edges"][-1] == [2, 2, 2]
    # what the simulator does today; Emulate decides whether it is right (a DINT/DINT DIV into a REAL, for one)
    assert sim["math"][0] == [9, 5, 14, 3, 3, 2, 5.0] and sim["cpt"][0][4] == 4  # 7/2.0 = 3.5 into a DINT: 4


def test_the_emulate_backend_runs_the_cases_and_a_difference_is_reported():
    fake = FakeEmulate()
    be = EmulateBackend(comm=fake, clock=fake.clock, sleep=fake.sleep, poll_ms=20)
    assert be.has("CT_T") and not be.has("Nope")
    real = cf.run_all(lambda c: be)
    sim = cf.run_all(cf.sim_backend)
    rows = cf.compare(sim, real)
    assert sum(r["differ"] for r in rows) == 0  # timer values within the tolerance
    fake.flip = {"CF_Q"}
    rows = cf.compare(sim, cf.run_all(lambda c: be))
    bits = next(r for r in rows if r["case"] == "bits")
    assert bits["differ"] == 4 and "CF_Q simulator" in cf.report(rows, "fake")


def test_emulate_errors_name_the_tag():
    fake = FakeEmulate()
    be = EmulateBackend(comm=fake, clock=fake.clock, sleep=fake.sleep)
    try:
        be.write("Nope", 1)
    except EmulateError as e:
        assert "Nope" in str(e)
    else:
        raise AssertionError("a failed write must raise")


def test_the_routine_to_import_reads_back_with_every_tag():
    for rev, mov in (("33", "MOV("), ("36", "MOVE(")):
        text = cf.routine_l5x(rev)
        p = read_l5x(text)
        rt = p.routines[0]
        assert rt.name == cf.ROUTINE and all(x.rung is not None for x in rt.rungs)
        assert len(rt.rungs) == sum(len(c.rungs) for c in cf.CASES)
        assert {t.name for t in p.tags.values()} == {n for c in cf.CASES for n in c.tags}
        assert any(mov in x.text for x in rt.rungs)
        assert p.presets()["CT_T"] == 1000
