"""The explorer: the attached file as a tree, and each item opened for the editor."""
import io
from pathlib import Path

import pytest

import app as gui
from gui.state import SESSION

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture()
def client():
    SESSION.detach()
    gui.app.config["TESTING"] = True
    with gui.app.test_client() as c:
        yield c
    SESSION.detach()


def attach(c, name):
    c.post("/api/project", data={"file": (io.BytesIO((FIX / name).read_bytes()), name)},
           content_type="multipart/form-data")


def test_no_file_attached(client):
    assert client.get("/api/project/tree").get_json() == {"attached": False}
    assert client.get("/api/project/routine?program=P&name=R").status_code == 400


def test_the_tree_and_each_item(client):
    attach(client, "sample_project.L5X")
    t = client.get("/api/project/tree").get_json()
    assert t["attached"] and t["filename"] == "sample_project.L5X" and t["controller"] == "Demo"
    main = next(p for p in t["programs"] if p["name"] == "MainProgram")
    assert [r["name"] for r in main["routines"]] == ["MainRoutine", "Calc"]
    assert t["aois"] == ["Motor_AOI"] and t["tags"]["controller"] >= 1
    r = client.get("/api/project/routine?program=MainProgram&name=MainRoutine").get_json()
    assert r["kind"] == "routine" and len(r["rows"]) == 5 and r["rows"][0]["comment"] == "Pump seal-in"
    assert r["rows"][1]["english"]
    assert client.get("/api/project/routine?program=MainProgram&name=Nope").status_code == 404
    aoi = client.get("/api/project/item?kind=aoi&name=Motor_AOI").get_json()
    assert [p["name"] for p in aoi["params"]][:3] == ["EnableIn", "EnableOut", "Start"]
    tags = client.get("/api/project/item?kind=tags&name=").get_json()
    assert tags["scope"] == "Controller" and any(x["name"] == "Pump" for x in tags["tags"])
    assert client.get("/api/project/item?kind=udt&name=Nope").status_code == 404


def test_a_udt_and_modules(client):
    attach(client, "udt_program.L5X")
    t = client.get("/api/project/tree").get_json()
    assert t["udts"]
    u = client.get(f"/api/project/item?kind=udt&name={t['udts'][0]}").get_json()
    assert u["kind"] == "udt" and u["members"]
    attach(client, "lint_project.L5X")
    t = client.get("/api/project/tree").get_json()
    if t["modules"]:
        m = client.get(f"/api/project/item?kind=module&name={t['modules'][0]['name']}").get_json()
        assert m["kind"] == "module" and m["catalog"]


def test_status_feeds_the_status_bar(client):
    s = client.get("/api/status").get_json()
    assert s["sim"] == {"loaded": False} and "last_run" in s and s["project"] is None
    attach(client, "sample_project.L5X")
    s = client.get("/api/status").get_json()
    assert s["project"] == "sample_project.L5X" and s["revision"].startswith("32")


def test_every_view_has_the_workbench(client):
    for path in ("/", "/energize", "/tests", "/devices", "/lint", "/settings", "/help"):
        html = client.get(path).data
        assert b'class="activity"' in html and b'class="statusbar"' in html, path
    chat = client.get("/").data
    assert b'id="explorer"' in chat and b'id="tabs"' in chat and b'id="panel"' in chat and b"ide.js" in chat
