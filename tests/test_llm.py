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


def test_no_near_miss_warning_for_a_name_the_request_writes():
    known = {"Cooker1_Enabled01": "BOOL", "Pump_Run": "BOOL"}
    m = FakeModel("Cooker2_Enabled01 := Pump_Run;")
    r = Generator(m).generate("Cooker2_Enabled01 is on while Pump_Run is on.", known_tags=known)
    assert r.spec and not any("did you mean" in w for w in r.warnings)  # the user named Cooker2_ on purpose


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
    make_client("openai").chat([{"role": "user", "content": "x"}])
    assert seen[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert seen[1]["chat_template_kwargs"] == {"enable_thinking": False}  # llama.cpp: always, the grammar needs it
    assert "chat_template_kwargs" not in seen[2]


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
                raise LLMError("the server rejected the grammar: parse error")
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


def test_ollama_gets_the_context_window(monkeypatch):
    import inputs.llm as llm
    seen = {}
    monkeypatch.setattr(llm, "_post_json", lambda url, body, timeout: seen.update(body) or {"message": {"content": "A := B;"}})
    llm.make_client("ollama", context=32768).chat([{"role": "user", "content": "x"}])
    assert seen["options"]["num_ctx"] == 32768


def test_guard_accepts_plain_names_written_in_the_request():
    from inputs.llm import Generator

    class Fake:
        supports_grammar = False
        calls = 0

        def chat(self, messages, grammar=None, **kw):
            Fake.calls += 1
            return "IF Flow_Switch THEN RESET Beacon;"

    r = Generator(Fake()).generate("When Flow_Switch is on, unlatch Beacon.", known_tags={"Beacon_Light": "BOOL"})
    assert r.error is None and Fake.calls == 1


def test_grammar_lets_the_model_write_plain_names_from_the_request():
    from inputs.llm import Generator, plain_names
    assert plain_names("D is on while A is on and B is off.") == {"A", "B", "D"}
    assert plain_names("Turn on A_Lamp when a part arrives. Unlatch Beacon.") == {"Beacon"}

    class G:
        supports_grammar = True
        grammar = ""

        def chat(self, messages, grammar=None, **kw):
            G.grammar = grammar
            return "IF Flow_Switch THEN RESET Beacon;"

    Generator(G()).generate("When Flow_Switch is on, unlatch Beacon.", known_tags={"Beacon_Light": "BOOL"})
    assert '"Beacon"' in G.grammar


def test_a_dropped_condition_is_sent_back():
    m = FakeModel("IF Cool_SP <= Temp_SP OR NOT Guard_Closed THEN COUNT_UP(Pallet_CTR, 100);",
                  "IF (Cool_SP <= Temp_SP OR NOT Guard_Closed) AND Batch_Request THEN COUNT_UP(Pallet_CTR, 100);")
    r = Generator(m).generate("Count up on Pallet_CTR with a preset of 100 if either Cool_SP is at most Temp_SP "
                              "or Guard_Closed is off, and Batch_Request is on.")
    assert "names Batch_Request but the logic does not use it" in m.calls[1][-1]["content"]
    assert "Batch_Request" in r.spec and len(r.attempts) == 2


def test_latch_the_request_did_not_ask_for_is_sent_back():
    m = FakeModel("IF Dosing_Rate <= 50 THEN SET Fault_Latch;", "IF Dosing_Rate <= 50 THEN ENERGIZE Fault_Latch;")
    r = Generator(m).generate("When Dosing_Rate is at most 50, energize Fault_Latch.")
    assert "does not ask to latch Fault_Latch" in m.calls[1][-1]["content"]
    assert "ENERGIZE Fault_Latch" in r.spec


def test_move_of_one_is_a_latch_too():
    # MOVE(1,Fault_Latch) never writes 0, so it held the output on like SET did
    m = FakeModel("IF Door_Open OR Motor_Overload THEN Fault_Latch := 1;",
                  "Fault_Latch := Door_Open OR Motor_Overload;")
    r = Generator(m).generate("When either Door_Open is on or Motor_Overload is on, turn on Fault_Latch.")
    assert "does not ask to latch Fault_Latch" in m.calls[1][-1]["content"]
    assert len(r.attempts) == 2


@pytest.mark.parametrize("spec, text", [
    ("IF Auto_Sel THEN Mode := 1;", "When Auto_Sel is on, move 1 to Mode."),  # the value is asked for
    ("IF Run_PB THEN Lamp := 1;\nIF Stop_PB THEN Lamp := 0;", "Turn on Lamp with Run_PB, off with Stop_PB."),
])
def test_move_of_one_that_is_asked_for_passes(spec, text):
    r = Generator(FakeModel(spec)).generate(text)
    assert len(r.attempts) == 1 and not any("latch" in w for w in r.warnings)


def test_latch_word_for_one_tag_does_not_excuse_another():
    # hard seed 11, Multi_output row 10: "latch Divert_Gate" switched the latch check off for Motor_Run
    m = FakeModel("IF NOT Auto_Mode AND Reset_PB THEN SET Divert_Gate, Motor_Run := 1;",
                  "IF NOT Auto_Mode AND Reset_PB THEN SET Divert_Gate, ENERGIZE Motor_Run;")
    r = Generator(m).generate("When Auto_Mode is false and Reset_PB is true, latch Divert_Gate and turn on Motor_Run.")
    assert "does not ask to latch Motor_Run" in m.calls[1][-1]["content"]
    assert "Divert_Gate" not in m.calls[1][-1]["content"].split("does not ask to latch")[1][:15]
    assert len(r.attempts) == 2


@pytest.mark.parametrize("text", [
    "When Start_PB is on, set Pump_Run; it stays on until reset.",   # the latch words name no tag
    "Keep Pump_Run on when Start_PB is pressed.",
])
def test_latch_asked_in_a_clause_still_passes(text):
    r = Generator(FakeModel("IF Start_PB THEN SET Pump_Run;")).generate(text)
    assert not any("latch" in w for w in r.warnings) and len(r.attempts) == 1


def test_a_condition_split_over_two_statements_is_sent_back():
    # hard seed 11, Parallel row 8: "(A or B), and C -> latch X" came back as two SETs, i.e. A OR B OR C
    m = FakeModel("IF Temp_PV > 50 OR Flow_Switch THEN SET Shuttle_Fwd;\nIF Steam_SP >= 10 THEN SET Shuttle_Fwd;",
                  "IF (Temp_PV > 50 OR Flow_Switch) AND Steam_SP >= 10 THEN SET Shuttle_Fwd;")
    r = Generator(m).generate("Latch Shuttle_Fwd if either Temp_PV exceeds 50 or Flow_Switch is on, "
                              "and Steam_SP is greater than or equal to 10.")
    assert "turned on by 2 separate statements" in m.calls[1][-1]["content"]
    assert len(r.attempts) == 2


def test_two_statements_are_fine_when_the_request_names_the_tag_twice():
    m = FakeModel("IF Start_PB THEN SET Lamp;\nIF Test_PB THEN SET Lamp;")
    r = Generator(m).generate("Latch Lamp when Start_PB is on. Also latch Lamp when Test_PB is on.")
    assert len(r.attempts) == 1


def test_rise_without_an_edge_word_is_sent_back():
    # hard seed 11, Multi_output row 12: a one-shot ran the timer and the heater for one scan
    m = FakeModel("IF RISE(Cool_SP > 10 AND Jam_Sensor) THEN START_TIMER(Settle_TMR, 2s), ENERGIZE Glue_Heater;",
                  "IF Cool_SP > 10 AND Jam_Sensor THEN START_TIMER(Settle_TMR, 2s), ENERGIZE Glue_Heater;")
    r = Generator(m).generate("When Cool_SP exceeds 10 and Jam_Sensor is active, run the on-delay timer Settle_TMR "
                              "with a 2 second preset and turn on Glue_Heater.")
    assert "do not use RISE" in m.calls[1][-1]["content"]
    assert "RISE" not in r.spec


@pytest.mark.parametrize("text", ["Add 1 to Batch_Count each time Box_Eye turns on.",
                                  "Add 1 to Batch_Count on the rising edge of Box_Eye."])
def test_rise_with_an_edge_word_passes(text):
    r = Generator(FakeModel("IF RISE(Box_Eye) THEN Batch_Count := Batch_Count + 1;")).generate(text)
    assert len(r.attempts) == 1 and not any("RISE" in w for w in r.warnings)


def test_set_and_reset_pair_is_a_latch_on_purpose():
    m = FakeModel("IF Level >= 95 THEN SET Drain_Valve;\nIF Level < 50 THEN RESET Drain_Valve;")
    r = Generator(m).generate("Open Drain_Valve when Level is at least 95, close it when Level drops below 50.")
    assert len(r.attempts) == 1 and not r.warnings


def test_output_the_request_does_not_name_is_sent_back():
    m = FakeModel("IF Box_Eye THEN COUNT_UP(Box_CTR, 12);\nBatch_Request := Box_CTR.DN;",
                  "IF Box_Eye THEN COUNT_UP(Box_CTR, 12);")
    r = Generator(m).generate("Count each box on Box_Eye with the up counter Box_CTR; the batch is done at 12 boxes.",
                              known_tags={"Batch_Request": "BOOL"})
    assert "writes Batch_Request, which the request does not name" in m.calls[1][-1]["content"]
    assert "Batch_Request" not in r.spec


def test_a_project_tag_made_of_the_request_words_passes():
    # with a project attached, "run the pump" may rightly become Pump_Run
    m = FakeModel("Pump_Run := Start_PB;")
    r = Generator(m).generate("Run the pump while Start_PB is pressed.", known_tags={"Pump_Run": "BOOL", "Start_PB": "BOOL"})
    assert len(r.attempts) == 1


def test_output_check_warns_on_the_last_attempt_instead_of_failing():
    m = FakeModel(*["IF Go_Cmd THEN SET Alarm_Latch;"] * 5)
    r = Generator(m).generate("When Go_Cmd is on, turn on Alarm_Latch.")
    assert r.spec and any("does not ask to latch" in w for w in r.warnings)
