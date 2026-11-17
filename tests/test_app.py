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
