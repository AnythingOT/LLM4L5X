"""GUI back end: the JSON API behind the chat page."""
import io
from pathlib import Path

import pytest

import app as gui

FIX = Path(__file__).parent / "fixtures" / "sample_project.L5X"


@pytest.fixture()
def client():
    gui.STATE.update(project=None, filename=None)
    gui.app.config["TESTING"] = True
    with gui.app.test_client() as c:
        yield c
    gui.STATE.update(project=None, filename=None)


def post(c, text, **settings):
    return c.post("/api/process", json={"text": text, "settings": settings}).get_json()


def test_index_page(client):
    r = client.get("/")
    assert r.status_code == 200 and b"LLM4L5X" in r.data and b"app.js" in r.data
    assert client.get("/static/app.js").status_code == 200


def test_compile_logicspec(client):
    d = post(client, "Pump := (Start_PB OR Pump) AND NOT Stop_PB;")
    assert d["kind"] == "compiled"
    assert d["rungs"][0]["text"] == "[XIC(Start_PB) ,XIC(Pump) ]XIO(Stop_PB)OTE(Pump);"
    assert d["readback"][0].startswith("Pump is on while")
    assert d["l5x"].startswith('<?xml version="1.0"') and d["filename"].endswith("_Rungs.L5X")


def test_routine_output_setting(client):
    d = post(client, "X := A;", output="routine", routine="My Routine")
    assert 'TargetType="Routine"' in d["l5x"] and d["filename"] == "My_Routine_Routine.L5X"


def test_spec_error_message(client):
    d = post(client, "X := A AND B OR C;")
    assert d["kind"] == "error" and "parentheses" in d["message"]


def test_rung_text_is_explained(client):
    d = post(client, "XIC(a)[XIC(b) ,XIO(c) ]OTE(d);\nXIC(x)OTE(y)XIC(z)OTE(w);")
    assert d["kind"] == "rungs"
    assert d["rungs"][0]["logicspec"] == "d := a AND (b OR NOT c);"
    assert d["rungs"][1]["logicspec"] is None and "middle" in d["rungs"][1]["why"]


def test_help_and_commands_without_project(client):
    assert post(client, "help")["kind"] == "help"
    assert post(client, "decompile")["kind"] == "error"
    assert post(client, "xref Pump")["kind"] == "error"


def test_attach_project_then_check_against_it(client):
    r = client.post("/api/project", data={"file": (io.BytesIO(FIX.read_bytes()), "plant.L5X")},
                    content_type="multipart/form-data").get_json()
    assert r["kind"] == "project" and r["controller"] == "Demo" and r["programs"] == ["MainProgram"]
    # existing tags are not re-created; type mismatch is caught
    d = post(client, "Pump := Start_PB AND NOT Stop_PB;")
    assert d["kind"] == "compiled" and d["tags"] == [] and d["used_project"] == "plant.L5X"
    assert post(client, "Pump := HighTmr;")["kind"] == "error"
    assert post(client, "decompile")["ok"] == 3
    assert post(client, "xref Pump")["refs"]
    assert any("parse error" in r["message"] for r in post(client, "validate")["rows"])
    assert client.get("/api/status").get_json()["project"] == "plant.L5X"
    assert client.delete("/api/project").get_json()["kind"] == "info"
    assert client.get("/api/status").get_json()["project"] is None


def test_bad_upload(client):
    r = client.post("/api/project", data={"file": (io.BytesIO(b"not xml"), "x.L5X")},
                    content_type="multipart/form-data").get_json()
    assert r["kind"] == "error"
    r = client.post("/api/project", data={"file": (io.BytesIO(b"x"), "x.txt")},
                    content_type="multipart/form-data").get_json()
    assert r["kind"] == "error" and ".L5X" in r["message"]


def test_ascii_paste(client):
    d = post(client, "XIC Start BST XIC Run NXB XIO Stop BND OTE Motor\nXIC a OTE b")
    assert d["kind"] == "rungs" and d["source"] == "ASCII"
    assert d["rungs"][0]["text"] == "XIC(Start)[XIC(Run) ,XIO(Stop) ]OTE(Motor);"
    assert d["rungs"][0]["logicspec"] == "Motor := Start AND (Run OR NOT Stop);"
    assert post(client, "XIC a BST XIC b OTE c")["kind"] == "error"


def test_compiled_includes_ascii(client):
    d = post(client, "Pump := (Start OR Pump) AND NOT Stop;")
    assert d["rungs"][0]["ascii"] == "BST XIC Start NXB XIC Pump BND XIO Stop OTE Pump"


def test_pasted_rungs_download_with_inferred_tags(client):
    d = post(client, "XIC Start BST XIC Run NXB XIO Stop BND OTE Motor\nGRT Level 5 TON T1 ? ?")
    assert d["kind"] == "rungs" and d["l5x"] and d["filename"].endswith("_Rungs.L5X")
    types = {t["name"]: t["type"] for t in d["tags"]}
    assert types == {"Start": "BOOL", "Run": "BOOL", "Stop": "BOOL", "Motor": "BOOL", "Level": "DINT", "T1": "TIMER"}
    assert any("preset of new timer T1 is unknown" in w for w in d["warnings"])
    d = post(client, "XIC(a)TON(T2,3000,0);")
    assert [t["preset"] for t in d["tags"] if t["name"] == "T2"] == [3000]


def test_english_goes_to_the_model(client, monkeypatch):
    import inputs.llm as llm
    monkeypatch.setattr(llm.OllamaClient, "chat", lambda self, m: "Pump_Run := (Start_PB OR Pump_Run) AND NOT Stop_PB;")
    d = post(client, "start the pump with start and keep it running until stop", model="fake-model")
    assert d["kind"] == "generated" and d["model"] == "fake-model"
    assert d["spec"] == "Pump_Run := (Start_PB OR Pump_Run) AND NOT Stop_PB;"
    assert d["rungs"][0]["text"] == "[XIC(Start_PB) ,XIC(Pump_Run) ]XIO(Stop_PB)OTE(Pump_Run);"
    assert d["l5x"] and len(d["attempts"]) == 1


def test_english_when_ollama_is_down(client, monkeypatch):
    import inputs.llm as llm
    def down(self, m):
        raise llm.LLMError("Cannot reach Ollama at http://127.0.0.1:11434. Is Ollama running?")
    monkeypatch.setattr(llm.OllamaClient, "chat", down)
    d = post(client, "turn on the lamp when the door is open")
    assert d["kind"] == "error" and "Is Ollama running" in d["message"] and "Settings" in d["hint"]


def test_broken_logicspec_is_not_sent_to_the_model(client, monkeypatch):
    import inputs.llm as llm
    monkeypatch.setattr(llm.OllamaClient, "chat", lambda self, m: (_ for _ in ()).throw(AssertionError("called")))
    d = post(client, "X := A AND B OR C;")
    assert d["kind"] == "error" and "parentheses" in d["message"]


def test_model_list_endpoint(client, monkeypatch):
    import inputs.llm as llm
    monkeypatch.setattr(llm.OllamaClient, "list_models", lambda self: ["phi4-mini:latest", "qwen3.6:35b-a3b"])
    d = client.post("/api/llm/models", json={"settings": {"backend": "ollama"}}).get_json()
    assert d["ok"] and d["models"] == ["phi4-mini:latest", "qwen3.6:35b-a3b"] and d["url"].endswith(":11434")
    def down(self):
        raise llm.LLMError("cannot reach http://127.0.0.1:8080/v1/models")
    monkeypatch.setattr(llm.OpenAICompatClient, "list_models", down)
    d = client.post("/api/llm/models", json={"settings": {"backend": "llamacpp"}}).get_json()
    assert not d["ok"] and "cannot reach" in d["error"] and d["url"].endswith(":8080")


def test_english_through_llamacpp_backend_uses_grammar(client, monkeypatch):
    import inputs.llm as llm
    seen = {}
    def chat(self, messages, grammar=None):
        seen["grammar"] = grammar
        return "Pump_Run := Start_PB;"
    monkeypatch.setattr(llm.OpenAICompatClient, "chat", chat)
    d = post(client, "Turn on Pump_Run while Start_PB is on.", backend="llamacpp", model="")
    assert d["kind"] == "generated" and d["grammar"] is True and "Pump_Run" in seen["grammar"]
