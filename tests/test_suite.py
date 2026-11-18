import random

import openpyxl

from eval.mutation import mutate
from eval.rung_compare import Side, compare
from eval.suite import INSTRUCTIONS, STRUCTURES, generate
from eval.suite_run import model_run, self_test, summary, write_excel
from core.compiler import Compiler
from core.logicspec import parse_spec
from core.rung import parse_rung


def test_every_instruction_in_every_structure():
    cases = generate(per_combo=1, seed=4)
    assert {(c.feature, c.structure) for c in cases} == {(i, s) for i in INSTRUCTIONS for s in STRUCTURES}
    for c in cases:  # the featured instruction really is in the expected rungs
        name = {"MOVE": "MOV", "EQ": "EQU", "NE": "NEQ", "GT": "GRT", "LT": "LES", "GE": "GEQ", "LE": "LEQ"}.get(
            c.feature, c.feature)
        assert f"{name}(" in " ".join(c.rungs), c.id


def test_parallel_cases_have_branches():
    for c in generate(per_combo=3, seed=5, structures=["parallel", "nested"]):
        assert "[" in c.rungs[-1], c.id


def test_self_test_passes_v35_and_v36():
    for v in (35, 36):
        out = self_test(generate(per_combo=2, seed=9, version=v), v)
        assert all(o.ok for o in out), [o.reason for o in out if not o.ok][:3]


def test_comparator_catches_mutations():
    rng, caught, total = random.Random(3), 0, 0
    for n, c in enumerate(generate(per_combo=4, seed=3)):
        res = Compiler(known_tags=c.tags, comments=False).compile(parse_spec(c.spec))
        pre = {t.name: t.preset for t in res.tags.values() if t.preset is not None}
        m = mutate(res.rungs, pre, rng)
        if m:
            total += 1
            caught += not compare(Side([parse_rung(t) for t in c.rungs], c.presets), Side(m[0], m[1]), seed=n)[0]
    assert caught / total > 0.95, (caught, total)


class Oracle:
    """Fake model: answers with the expected LogicSpec, or a wrong one every Nth time."""
    def __init__(self, cases, wrong_every=0):
        self.spec = {c.english: c.spec for c in cases}
        self.wrong_every, self.n = wrong_every, 0

    def chat(self, messages):
        self.n += 1
        # the request is the last user message that is a case (later ones are retry prompts)
        request = next(m["content"] for m in reversed(messages) if m["role"] == "user" and m["content"] in self.spec)
        spec = self.spec[request]
        if self.wrong_every and self.n % self.wrong_every == 0:
            return spec.replace(" AND ", " OR ", 1) if " AND " in spec else spec.replace("NOT ", "", 1) or spec
        return spec


def test_model_run_and_excel(tmp_path):
    cases = generate(per_combo=1, seed=6, instructions=["XIC", "GT", "TON", "ONS", "COP"])
    out = model_run(cases, Oracle(cases), 35)
    assert all(o.ok for o in out)
    out = model_run(cases, Oracle(cases, wrong_every=2), 35)
    assert any(not o.ok for o in out)
    path = tmp_path / "r.xlsx"
    write_excel(out, str(path), "test")
    wb = openpyxl.load_workbook(path)
    assert wb["Results"].max_row == len(cases) + 1 and "behaviour match" in wb["Summary"]["A2"].value
    assert "by structure" in summary(out, "t")
