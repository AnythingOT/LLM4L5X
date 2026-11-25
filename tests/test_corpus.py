"""Every feature over a folder of real L5X exports. Skipped unless LLM4L5X_CORPUS names the folder:

    python -m eval.fetch_corpus corpus          # the public exports CI uses (eval/corpus_sources.txt)
    LLM4L5X_CORPUS=corpus pytest tests/test_corpus.py -q

The exports themselves are never committed (they can be confidential). What is checked per file:
the GUI flows run without an error (attach, summary, explain, validate, optimize UDTs), no rule
crashes, every rung draws as a ladder diagram, rungs survive our writer and reader unchanged, and a reordered whole-program file reads
back with every selected UDT now in the best order and at the promised size.
"""
import base64
import io
import json
import os
from pathlib import Path

import pytest

import app as gui
from gui.state import SESSION
from core.rung import format_rung
from explain.ladder import to_svg
from lxml import etree
from l5x.reader import read_l5x
from l5x.writer import write_routine
from udt import optimize

ROOT = os.environ.get("LLM4L5X_CORPUS")
FILES = sorted(f for f in Path(ROOT).rglob("*") if f.suffix.lower() == ".l5x") if ROOT else []
pytestmark = pytest.mark.skipif(not ROOT, reason="set LLM4L5X_CORPUS to a folder of L5X exports")


@pytest.fixture
def client():
    gui.app.config["TESTING"] = True
    with gui.app.test_client() as c:
        yield c
    SESSION.detach()


def _ask(client, text):
    r = client.post("/api/process", json={"text": text, "settings": {}})
    assert r.status_code == 200
    return r.get_json()


@pytest.mark.parametrize("path", FILES, ids=[f.name for f in FILES])
def test_every_flow(client, path):
    data = path.read_bytes()
    d = client.post("/api/project", data={"file": (io.BytesIO(data), path.name)},
                    content_type="multipart/form-data").get_json()
    assert d["kind"] == "project", d.get("message")
    for cmd in ("summary", "decompile"):
        assert _ask(client, cmd)["kind"] != "error"
    v = _ask(client, "validate")
    assert v["kind"] == "validated" and not v["lint"]["errors"], v["lint"]["errors"]

    plan = d.get("udt_plan") or _ask(client, "optimize")
    if plan["kind"] == "error":  # no UDTs in this file
        return
    for p in plan["plans"]:
        if p["status"] != "skipped":
            assert p["size_best"] <= p["size_now"], p["name"]
    chosen = [p["name"] for p in plan["plans"] if p["status"] == "reordered"]
    if not chosen:
        return
    assert client.post("/api/udt/download", json={"selected": chosen, "output": "zip"}).status_code == 200
    if not plan["full"]:
        return
    r = client.post("/api/udt/download", json={"selected": chosen, "output": "program"})
    assert r.status_code == 200
    notes = " ".join(json.loads(base64.b64decode(r.headers["X-Notes"])))
    after = optimize.analyse(r.data)
    assert after.bom == (data[:3] == b"\xef\xbb\xbf")
    promised = {p["name"]: p["size_best"] for p in plan["plans"]}
    for name in chosen:
        if name in notes:  # left out, and the download says why
            continue
        got = after.plans[name]
        assert got.status != "reordered", f"{name} still not in the best order"
        assert got.size_now == promised[name], f"{name}: {got.size_now} bytes, promised {promised[name]}"


@pytest.mark.parametrize("path", FILES, ids=[f.name for f in FILES])
def test_rungs_survive_write_and_read(path):
    for rt in read_l5x(path.read_bytes()).routines:
        rungs = [x.rung for x in rt.rungs if x.rung is not None]
        if rungs:
            back = read_l5x(write_routine(rungs, [], routine="R", controller="C", program="P",
                                          revision="33.00", scope="controller").encode())
            assert [x.text for r in back.routines for x in r.rungs] == [format_rung(r) for r in rungs]


@pytest.mark.parametrize("path", FILES, ids=[f.name for f in FILES])
def test_every_rung_draws(path):
    p = read_l5x(path.read_bytes())
    cat = p.catalog()
    for rt in p.routines:
        for x in rt.rungs:
            if x.rung is not None:
                etree.fromstring(to_svg(x.rung, cat, number=x.number).encode())


@pytest.mark.parametrize("path", FILES, ids=[f.name for f in FILES])
def test_energize_loads_or_says_why(path):
    """Energize on a real export: it runs, or it refuses with a reason. Never a crash, never a silent skip."""
    from core.simulator import SimError
    from gui.energize import EnergizeError, load
    try:
        s = load([path.read_bytes()])
    except EnergizeError as e:
        assert str(e)
        return
    try:
        s.step(100)
        s.step(1000)
    except SimError:
        pass  # a run-time fault (divide by zero ...): the page shows it
