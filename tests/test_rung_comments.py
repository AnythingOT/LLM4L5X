"""Download the attached L5X with the English read as rung comments: only missing comments are added."""
import io
from pathlib import Path

import pytest
from lxml import etree

import app as gui
from explain.comments import PREFIX, add_rung_comments
from gui.state import SESSION
from l5x.reader import read_l5x

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture()
def client():
    SESSION.detach()
    gui.app.config["TESTING"] = True
    with gui.app.test_client() as c:
        yield c
    SESSION.detach()


def attach(c, name):
    raw = (FIX / name).read_bytes()
    c.post("/api/project", data={"file": (io.BytesIO(raw), name)}, content_type="multipart/form-data")
    return raw


def without_auto_comments(data: bytes) -> bytes:
    root = etree.fromstring(data, etree.XMLParser(strip_cdata=False))
    for c in root.iter("Comment"):
        if c.getparent().tag == "Rung" and (c.text or "").startswith(PREFIX):
            c.getparent().remove(c)
    return etree.tostring(root, method="c14n")


def test_missing_comments_are_added_and_nothing_else_changes(client):
    raw = attach(client, "sample_project.L5X")
    d = client.post("/api/process", json={"text": "decompile", "settings": {}}).get_json()
    assert d["commented"] == 1 and d["can_comment"] == 2  # rung 0 has a comment; rungs 1, 2 explained; 3 is an AOI call
    assert next(r for r in d["rows"] if r["number"] == 0)["comment"] == "Pump seal-in"
    r = client.get("/api/project/commented")
    assert r.status_code == 200 and r.headers["X-Added"] == "2"
    assert 'filename="sample_project_commented.L5X"' in r.headers["Content-Disposition"]
    body = r.data
    assert body.startswith(raw[: raw.index(b"<RSLogix5000Content")])  # declaration as exported
    p = read_l5x(body)
    comments = {x.number: x.comment for x in p.routines[0].rungs}
    assert comments[0].strip() == "Pump seal-in"  # the author's comment is kept as it was
    assert comments[1].startswith(PREFIX) and "Level" in comments[1] and comments[2].startswith(PREFIX)
    assert not comments[3]
    # the only change is the added comments: everything else is byte-for-byte the same XML
    assert without_auto_comments(body) == without_auto_comments(raw)


def test_a_fully_commented_file_gets_nothing(client):
    raw = (FIX / "sample_project.L5X").read_bytes()
    once, added = add_rung_comments(raw, {("MainProgram", "MainRoutine", 1): "one", ("MainProgram", "MainRoutine", 0): "x"})
    assert added == 1  # rung 0 already has a comment
    again, added = add_rung_comments(once, {("MainProgram", "MainRoutine", 1): "two"})
    assert added == 0 and again == once


def test_no_file_attached(client):
    assert client.get("/api/project/commented").status_code == 400
