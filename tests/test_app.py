"""GUI back end: the JSON API behind the chat page."""
import base64
import io
import json
import zipfile
from pathlib import Path

import pytest

import app as gui
from gui import state as gui_state
from gui.state import SESSION

FIX = Path(__file__).parent / "fixtures" / "sample_project.L5X"


@pytest.fixture()
def client():
    SESSION.detach()
    gui.app.config["TESTING"] = True
    with gui.app.test_client() as c:
        yield c
    SESSION.detach()


def post(c, text, **settings):
    return c.post("/api/process", json={"text": text, "settings": settings}).get_json()


def test_index_page(client):
    r = client.get("/")
    assert r.status_code == 200 and b"LLM4L5X" in r.data and b"app.js" in r.data
    assert client.get("/static/app.js").status_code == 200


def test_compile_logicspec(client):
    d = post(client, "Pump := (Start_PB OR Pump) AND NOT Stop_PB;", output="rungs")
    assert d["kind"] == "compiled"
    assert d["rungs"][0]["text"] == "[XIC(Start_PB) ,XIC(Pump) ]XIO(Stop_PB)OTE(Pump);"
    assert d["readback"][0].startswith("Pump is on while")
    assert d["l5x"].startswith('<?xml version="1.0"') and d["filename"] == "Rung.L5X"


def test_routine_output_setting(client):
    d = post(client, "X := A;", output="routine", routine="My Routine")
    assert 'TargetType="Routine"' in d["l5x"] and d["filename"] == "Routine.L5X"


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
    v = post(client, "validate")
    assert any("does not parse" in r["message"] for r in v["import"])
    assert v["lint"]["counts"] and isinstance(v["lint"]["findings"], list)
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
    d = post(client, "XIC Start BST XIC Run NXB XIO Stop BND OTE Motor\nGRT Level 5 TON T1 ? ?", output="rungs")
    assert d["kind"] == "rungs" and d["l5x"] and d["filename"] == "Rung.L5X"
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
    def chat(self, messages, grammar=None, **kw):
        seen["grammar"] = grammar
        return "Pump_Run := Start_PB;"
    monkeypatch.setattr(llm.OpenAICompatClient, "chat", chat)
    d = post(client, "Turn on Pump_Run while Start_PB is on.", backend="llamacpp", model="")
    assert d["kind"] == "generated" and d["grammar"] is True and "Pump_Run" in seen["grammar"]


def test_validate_runs_the_rules_with_disabled_ones_skipped(client):
    from pathlib import Path
    fx = Path(__file__).parent / "fixtures" / "lint_project.L5X"
    r = client.post("/api/project", data={"file": (fx.open("rb"), "line.L5X")}, content_type="multipart/form-data")
    assert r.get_json()["kind"] == "project"
    d = client.post("/api/process", json={"text": "validate", "settings": {"disabled_rules": ["ERR001", "bogus"]}}).get_json()
    codes = {f["code"] for f in d["lint"]["findings"]}
    assert "ERR002" in codes and "ERR001" not in codes and d["lint"]["disabled"] == ["ERR001"]


def test_generated_and_pasted_rungs_carry_rung_rule_findings(client):
    d = post(client, "XIC(a)OTE(b);\nXIC(c)OTE(b);")
    assert d["kind"] == "rungs" and any(f["code"] == "ERR001" for f in d["lint"])


def test_pages_and_rule_list(client):
    for page in ("/", "/settings", "/lint", "/devices", "/tests", "/energize"):
        assert client.get(page).status_code == 200
    rules = client.get("/api/rules").get_json()["rules"]
    assert len(rules) == 50 and {"code", "title", "description", "severity", "scope", "group"} <= set(rules[0])


# ---------------------------------------------------------------- UDTs

def test_udt_text_in_udt_mode_gives_a_file(client):
    d = client.post("/api/process", json={"text": 'UDT Motor "m";\nSpeed REAL;\nRun BOOL;', "mode": "udt",
                                          "settings": {}}).get_json()
    assert d["kind"] == "udt_created" and d["filename"] == "Motor.L5X" and 'TargetType="DataType"' in d["l5x"]
    assert [m["name"] for m in d["udts"][0]["members"]] == ["Run", "Speed"] and d["udts"][0]["size"] == 8


def test_udt_problems_are_listed(client):
    d = client.post("/api/process", json={"text": "UDT Bad;\nFlags BOOL[20];", "mode": "udt"}).get_json()
    assert d["kind"] == "error" and any("multiple of 32" in x for x in d["details"])


def test_excel_attach_builds_udts_without_touching_the_project(client):
    from udt.excel import template
    r = client.post("/api/project", data={"file": (io.BytesIO(template()), "udts.xlsx")},
                    content_type="multipart/form-data").get_json()
    assert r["kind"] == "udt_created" and r["filename"] == "UDTs.zip" and len(r["udts"]) == 2
    z = zipfile.ZipFile(io.BytesIO(base64.b64decode(r["zip_b64"])))
    assert sorted(z.namelist()) == ["Line_Status.L5X", "Motor_Status.L5X"]
    assert client.get("/api/status").get_json()["project"] is None


def test_attach_udt_export_shows_the_plan_and_downloads(client):
    fx = Path(__file__).parent / "fixtures" / "studio_single_udt.L5X"
    r = client.post("/api/project", data={"file": (fx.open("rb"), "B322.L5X")},
                    content_type="multipart/form-data").get_json()
    plan = r["udt_plan"]
    assert plan["target"] == "B322" and not plan["full"] and plan["plans"][0]["saved"] == 36
    f = client.post("/api/udt/download", json={"selected": ["B322"], "output": "single"})
    assert f.status_code == 200 and "B322_opt.L5X" in f.headers["Content-Disposition"]
    assert client.post("/api/udt/download", json={"selected": ["B322"], "output": "program"}).status_code == 400


def test_optimize_command_and_full_program_download(client):
    fx = Path(__file__).parent / "fixtures" / "udt_program.L5X"
    client.post("/api/project", data={"file": (fx.open("rb"), "plant.L5X")}, content_type="multipart/form-data")
    d = post(client, "optimize")
    by = {p["name"]: p for p in d["plans"]}
    assert d["kind"] == "udt_plan" and d["full"] and by["Pad_UDT"]["default"] and not by["Copy_UDT"]["default"]
    assert not by["InAoi_UDT"]["default"]  # reordered but saves nothing
    f = client.post("/api/udt/download", json={"selected": ["Pad_UDT"], "output": "program"})
    notes = json.loads(base64.b64decode(f.headers["X-Notes"]))
    assert f.status_code == 200 and any("Test the import" in n for n in notes)
    z = client.post("/api/udt/download", json={"selected": ["Pad_UDT", "Copy_UDT"], "output": "zip"})
    assert z.mimetype == "application/zip"
    assert client.get("/api/udt/template").mimetype.endswith("sheet")


def test_plain_english_udt_goes_through_the_model(client, monkeypatch):
    class Fake:
        supports_grammar, url = True, "http://x"

        def chat(self, messages, grammar=None, **kw):
            return 'UDT Pump "A pump";\nSpeed REAL "rpm";\nRunning BOOL "running";'
    monkeypatch.setattr(gui_state, "llm", lambda s: Fake())
    d = client.post("/api/process", json={"text": "a pump with speed and running", "mode": "udt"}).get_json()
    assert d["kind"] == "udt_created" and d["grammar"] and d["filename"] == "Pump.L5X"
    assert [m["name"] for m in d["udts"][0]["members"]] == ["Running", "Speed"]


def test_ladder_endpoint_and_drawings_in_results(client):
    d = client.post("/api/ladder", json={"rungs": [{"text": "XIC(A)OTE(B);", "number": 3}, {"text": "nonsense"}]}).get_json()
    assert d["svgs"][0].startswith("<svg") and ">3<" in d["svgs"][0] and d["svgs"][1] is None
    r = post(client, "XIC(A)OTE(B);")
    assert r["rungs"][0]["svg"].startswith("<svg")


@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"},                         # another site's page
    {"Origin": "null"},                                         # sandboxed iframe, file:// page
    {"Sec-Fetch-Site": "cross-site"},                           # cross-site without an Origin
    {"Host": "127.0.0.1:5000", "Origin": "http://127.0.0.1:8000"},  # another app on this PC
    {"Host": "attacker.example:5000"},                          # DNS rebinding
])
def test_other_sites_cannot_drive_the_app(client, headers):
    # a page the user visits must not start a job that sends the project's tags elsewhere
    xlsx = client.get("/api/spec/sample").data
    settings = json.dumps({"backend": "ollama", "llm_url": "http://203.0.113.9:11434"})
    r = client.post("/api/project", data={"file": (io.BytesIO(xlsx), "req.xlsx"), "settings": settings},
                    content_type="multipart/form-data", headers=headers)
    assert r.status_code == 403
    assert client.delete("/api/project", headers=headers).status_code == 403


def test_the_app_own_page_and_scripts_still_work(client):
    same = {"Host": "127.0.0.1:5000", "Origin": "http://127.0.0.1:5000"}
    assert client.post("/api/process", json={"text": "help"}, headers=same).status_code == 200
    assert client.post("/api/process", json={"text": "help"}).status_code == 200  # curl, no browser headers
    assert client.get("/").status_code == 200


def test_extra_hosts_can_be_allowed_on_purpose(client, monkeypatch):
    monkeypatch.setenv("LLM4L5X_ALLOWED_HOSTS", "plc-tools.lan")
    assert client.post("/api/process", json={"text": "help"},
                       headers={"Host": "plc-tools.lan:5000", "Origin": "http://plc-tools.lan:5000"}).status_code == 200
def test_ladder_shows_presets_from_the_attached_project(client):
    from core.compiler import TagDef
    from core.rung import parse_rung
    from l5x.writer import write_routine
    l5x = write_routine([parse_rung("XIC(Go)TON(Fill_TMR,?,?);")],
                        [TagDef("Go", "BOOL"), TagDef("Fill_TMR", "TIMER", preset=5000)],
                        routine="R", program="P", revision="37.00")
    d = client.post("/api/project", data={"file": (io.BytesIO(l5x.encode()), "p.L5X")},
                    content_type="multipart/form-data").get_json()
    assert d["kind"] == "project"
    svg = client.post("/api/ladder", json={"rungs": [{"text": "XIC(Go)TON(Fill_TMR,?,?);"}]}).get_json()["svgs"][0]
    assert ">5000</text>" in svg
