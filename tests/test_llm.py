"""English -> LogicSpec loop, with a fake model (no Ollama needed)."""
import json

import pytest

from core.compiler import compile_spec
from inputs.llm import (Generator, LLMError, OllamaClient, extract_spec, load_examples, pick_examples,
                        pick_tags)


class FakeModel:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages):
        self.calls.append(messages)
        return self.replies.pop(0)


def test_every_example_compiles():
    for ex in load_examples():
        assert compile_spec(ex["spec"]).rungs, ex["english"]


def test_extract_spec_strips_noise():
    reply = "<think>hmm</think>Sure! Here it is:\n```\n1. Pump := Start AND NOT Stop;\n- IF A THEN SET B;\n```\nHope that helps."
    assert extract_spec(reply) == "Pump := Start AND NOT Stop;\nIF A THEN SET B;"
    assert extract_spec("no code here") == ""


def test_first_try_success():
    m = FakeModel("Pump := (Start_PB OR Pump) AND NOT Stop_PB;")
    r = Generator(m).generate("start pump with start button, stop with stop")
    assert r.error is None and len(r.attempts) == 1
    assert r.compiled.texts == ["[XIC(Start_PB) ,XIC(Pump) ]XIO(Stop_PB)OTE(Pump);"]


def test_retry_sends_the_exact_error_back():
    m = FakeModel("X := A AND B OR C;", "X := (A AND B) OR C;")
    r = Generator(m).generate("x when a and b, or c")
    assert r.error is None and len(r.attempts) == 2
    assert "parentheses" in r.attempts[0].error
    retry_msg = m.calls[1][-1]["content"]
    assert "That LogicSpec has an error" in retry_msg and "parentheses" in retry_msg


def test_gives_up_after_retries():
    m = FakeModel("nonsense", "still nonsense", "X := ;")
    r = Generator(m, retries=2).generate("whatever")
    assert r.spec is None and r.error.startswith("no valid LogicSpec after 3 attempts")


def test_validator_error_triggers_retry_with_project_tags():
    known = {"Pump_Run": "BOOL", "Level": "DINT"}
    m = FakeModel("Pump_Run := Level;", "Pump_Run := Level > 5;")
    r = Generator(m).generate("run pump when level above 5", known_tags=known)
    assert r.error is None and "Level is a DINT" in r.attempts[0].error


def test_project_tags_in_prompt_and_near_miss_warning():
    known = {"Pump_Run": "BOOL", "Stop_PB": "BOOL", "Start_PB": "BOOL", "Unrelated_Tag": "DINT"}
    m = FakeModel("Pump_Rnu := Start_PB AND NOT Stop_PB;")
    r = Generator(m).generate("run the pump from start, stop it with stop", known_tags=known)
    system = m.calls[0][0]["content"]
    assert "Pump_Run (BOOL)" in system and "Unrelated_Tag" not in system
    assert any("did you mean Pump_Run" in w for w in r.warnings)


def test_pick_tags_uses_descriptions():
    tags = {"P101_RUN": "BOOL", "FT201": "REAL", "XV300": "BOOL"}
    desc = {"FT201": "Cooling water flow", "XV300": "Drain valve"}
    picked = [n for n, _, _ in pick_tags("open the drain valve when flow is low", tags, desc)]
    assert picked[:2] == ["XV300", "FT201"] or set(picked[:2]) == {"XV300", "FT201"}


def test_pick_examples_prefers_similar():
    ex = load_examples()
    chosen = pick_examples("count boxes on the photo eye", ex, k=3)
    assert any("Count each box" in e["english"] for e in chosen)
    assert ex[0] in chosen


def test_ollama_client_errors(monkeypatch):
    import urllib.request, urllib.error

    def refuse(*a, **k):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    with pytest.raises(LLMError, match="Is Ollama running"):
        OllamaClient().chat([{"role": "user", "content": "x"}])


def test_ollama_client_request_shape(monkeypatch):
    import urllib.request
    seen = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"message": {"content": "X := A;"}}).encode()

    def fake(req, timeout):
        seen["url"], seen["body"] = req.full_url, json.loads(req.data)
        return Resp()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    assert OllamaClient(model="qwen3.6:35b-a3b", think=False).chat([{"role": "user", "content": "x"}]) == "X := A;"
    assert seen["url"].endswith("/api/chat")
    assert seen["body"]["model"] == "qwen3.6:35b-a3b" and seen["body"]["think"] is False
    assert seen["body"]["stream"] is False and seen["body"]["options"]["temperature"] == 0
