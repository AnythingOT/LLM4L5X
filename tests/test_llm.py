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
    # a misspelt tag is sent back once; if the model insists, it is accepted with a warning
    m = FakeModel("Pump_Rnu := Start_PB AND NOT Stop_PB;", "Pump_Rnu := Start_PB AND NOT Stop_PB;",
                  "Pump_Rnu := Start_PB AND NOT Stop_PB;")
    r = Generator(m).generate("run the pump from start, stop it with stop", known_tags=known)
    system = m.calls[0][0]["content"]
    assert "Pump_Run (BOOL)" in system and "Unrelated_Tag" not in system
    assert "did you mean Pump_Run" in m.calls[1][-1]["content"]
    assert r.spec and any("did you mean Pump_Run" in w for w in r.warnings)


def test_tag_names_snapped_to_the_request():
    m = FakeModel("IF Press_Hi_Limit > 5 THEN SPEED_REF := FLOW_RATE * 2;")
    r = Generator(m).generate("When PressHiLimit is above 5, store FlowRate times 2 in Speed_Ref.")
    assert r.spec == "IF PressHiLimit > 5 THEN Speed_Ref := FlowRate * 2;" and len(r.attempts) == 1
    assert any("Press_Hi_Limit -> PressHiLimit" in w for w in r.warnings)


def test_copied_example_is_rejected():
    ex = load_examples()
    copied = ex[0]["spec"]
    m = FakeModel(copied, "Agitator_Run := Mixer_Start;")
    r = Generator(m).generate("Run Agitator_Run whenever Mixer_Start is on.")
    assert "copied from the examples" in r.attempts[0].error and r.spec == "Agitator_Run := Mixer_Start;"


def test_relevant_example_may_be_repeated():
    ex = load_examples()[0]
    m = FakeModel(ex["spec"])
    r = Generator(m).generate(ex["english"])  # the request IS the example: repeating it is right
    assert r.spec and len(r.attempts) == 1


def test_misspelt_request_tag_gets_retry():
    m = FakeModel("IF RISE(Stop_PB) THEN COUNT_UP(Bottle_Counter, 10);", "IF RISE(Stop_PB) THEN COUNT_UP(Bottle_CTR, 10);")
    r = Generator(m).generate("When on the rising edge of Stop_PB, count up on Bottle_CTR with a preset of 10.")
    assert "did you mean Bottle_CTR" in r.attempts[0].error and r.spec.endswith("COUNT_UP(Bottle_CTR, 10);")


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


class Resp:
    def __init__(self, data): self.data = data
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return json.dumps(self.data).encode()


def test_llamacpp_client_sends_grammar_and_lists_models(monkeypatch):
    import urllib.request
    from inputs.llm import make_client
    seen = []

    def fake(req, timeout=None):
        if isinstance(req, str):
            seen.append(("GET", req))
            return Resp({"data": [{"id": "qwen3.6-35b-a3b-q4.gguf"}]})
        seen.append(("POST", req.full_url, json.loads(req.data)))
        return Resp({"choices": [{"message": {"content": "Motor_Run := Start_PB;"}}]})
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    c = make_client("llamacpp")
    assert c.supports_grammar and c.url.endswith(":8080")
    assert c.list_models() == ["qwen3.6-35b-a3b-q4.gguf"]
    r = Generator(c).generate("Turn on Motor_Run while Start_PB is on.")
    assert r.spec == "Motor_Run := Start_PB;"
    body = seen[-1][2]
    assert seen[-1][1].endswith("/v1/chat/completions") and "grammar" in body
    assert '"Motor_Run"' in body["grammar"] and body["temperature"] == 0


def test_no_think_asks_the_template_to_skip_thinking(monkeypatch):
    import urllib.request
    from inputs.llm import make_client
    seen = []

    def fake(req, timeout=None):
        seen.append(json.loads(req.data))
        return Resp({"choices": [{"message": {"content": "Motor_Run := Start_PB;"}}]})
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    make_client("llamacpp", think=False).chat([{"role": "user", "content": "x"}])
    make_client("llamacpp").chat([{"role": "user", "content": "x"}])
    assert seen[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert "chat_template_kwargs" not in seen[1]


def test_openai_compatible_client_has_no_grammar(monkeypatch):
    import urllib.request
    from inputs.llm import make_client
    bodies = []
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: bodies.append(json.loads(req.data)) or
                        Resp({"choices": [{"message": {"content": "X := A;"}}]}))
    c = make_client("openai", model="local-model")
    assert not c.supports_grammar and c.url.endswith(":1234")
    Generator(c).generate("X when A")
    assert "grammar" not in bodies[-1] and bodies[-1]["model"] == "local-model"


def test_grammar_rejected_falls_back(monkeypatch):
    from inputs.llm import OpenAICompatClient

    class Picky(OpenAICompatClient):
        def chat(self, messages, grammar=None):
            if grammar:
                raise LLMError("the server rejected the LogicSpec grammar: parse error")
            return "Motor_Run := Start_PB;"
    r = Generator(Picky(grammar=True)).generate("Turn on Motor_Run while Start_PB is on.")
    assert r.spec == "Motor_Run := Start_PB;" and any("continuing without it" in w for w in r.warnings)


def test_ollama_lists_models(monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: Resp(
        {"models": [{"name": "qwen3.6:35b-a3b"}, {"name": "phi4-mini:latest"}]}))
    assert OllamaClient().list_models() == ["phi4-mini:latest", "qwen3.6:35b-a3b"]


def test_extract_spec_joins_statements_split_over_lines():
    from inputs.llm import extract_spec
    reply = ("Here you go:\nIF (A <= B) OR C THEN\n  P := S * T;\nIf you need more, ask.\n"
             "Lamp := Door;")
    assert extract_spec(reply) == "IF (A <= B) OR C THEN P := S * T;\nLamp := Door;"
