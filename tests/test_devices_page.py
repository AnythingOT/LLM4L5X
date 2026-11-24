"""Device models on their own page, and the Lint page's name."""
import pytest
from test_energize import FILES, PLANT, SCENARIOS, _upload


@pytest.fixture
def web(tmp_path):
    import app as gui
    from gui import ENERGIZE
    from scenario.evidence import RunStore
    gui.app.config["TESTING"] = True
    gui.app.config["RUNS"] = RunStore(tmp_path / "runs")  # never the real runs/ folder
    ENERGIZE.clear()
    with gui.app.test_client() as c:
        yield c
    ENERGIZE.clear()


def test_device_models_have_their_own_page_and_save(web):
    assert web.get("/devices").status_code == 200
    bad = web.post("/api/devices/save", json={"devices": "devices: ["})
    assert bad.status_code == 400 and bad.get_json()["error"].startswith("Device models:")
    ok = web.post("/api/devices/save", json={"devices": PLANT}).get_json()
    assert ok["devices"] == 1 and ok["loaded"] is False
    d = ok["device_list"][0]
    assert d["name"] == "P101" and d["reads"] == ["P101_Cmd"] and d["answers"] == ["P101_Running"]
    assert d["timing"]["start_ms"] > 0
    # loaded later: the program answers with the saved models; Tests saves test cases alone
    _upload(web, FILES, plant=None, scenarios=None)
    assert web.get("/api/energize/state").get_json()["feedbacks"] == ["P101_Running"]
    assert web.post("/api/tests/save", json={"tests": SCENARIOS}).get_json()["devices"] == 1


def test_lint_page_and_its_old_address(web):
    assert web.get("/lint").status_code == 200 and b"<h1>Lint</h1>" in web.get("/lint").data
    r = web.get("/rules")
    assert r.status_code == 301 and r.headers["Location"].endswith("/lint")
