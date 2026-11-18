import yaml

from core.compiler import compile_spec
from eval.run import report, run_eval
from explain.equivalence import equivalent

EVAL = "eval/requests.yaml"


def test_eval_set_compiles():
    for c in yaml.safe_load(open(EVAL)):
        compile_spec(c["expect"], known_tags=c.get("tags"))


def test_equivalent_by_meaning():
    assert equivalent("X := B AND A;", "X := A AND B;")[0]
    assert equivalent("X := NOT (A OR B);", "X := NOT A AND NOT B;")[0]
    assert equivalent("X := N <= 5;", "X := NOT N > 5;")[0]
    assert equivalent("IF A THEN SET B, RESET C;", "IF A THEN RESET C;\nIF A THEN SET B;")[0]
    assert equivalent("X := DELAY(A AND B, 5s, T9);", "X := DELAY(B AND A, 5s);")[0] is False  # inner text differs
    assert equivalent("X := DELAY(A, 5s, T9);", "X := DELAY(A, 5s);")[0]


def test_not_equivalent_with_reason():
    ok, why = equivalent("X := A OR B;", "X := A AND B;")
    assert not ok and "different condition for X" in why
    ok, why = equivalent("Y := A;", "X := A;")
    assert not ok and "missing X" in why and "unexpected Y" in why
    ok, why = equivalent("X := A AND;", "X := A;")
    assert not ok and "does not parse" in why


class Oracle:
    """Fake model that answers each eval request with the expected spec."""
    def __init__(self, cases, wrong_every=0):
        self.answers = {c["request"]: c["expect"] for c in cases}
        self.wrong_every, self.n = wrong_every, 0

    def chat(self, messages):
        self.n += 1
        req = messages[-1]["content"]
        if self.wrong_every and self.n % self.wrong_every == 0:
            return "Wrong_Output := Something;"
        return self.answers[req]


def test_run_eval_with_fake_model():
    cases = yaml.safe_load(open(EVAL))
    rows = run_eval(EVAL, Oracle(cases))
    assert all(r.ok for r in rows) and len(rows) == len(cases)
    rows = run_eval(EVAL, Oracle(cases, wrong_every=3), limit=6)
    assert sum(r.ok for r in rows) < 6
    assert "correct:" in report(rows, "fake")
