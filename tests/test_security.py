"""Data must not leave this PC by accident: the model address, the page banner, big files."""
import pytest

from inputs.llm import LLMError, check_url, is_local_url, make_client


@pytest.mark.parametrize("url", ["http://127.0.0.1:11434", "http://localhost:8080", "http://[::1]:1234",
                                 "https://127.0.0.2:9000"])
def test_this_pc_is_allowed(url):
    assert is_local_url(url) and check_url(url) == url


@pytest.mark.parametrize("url", ["http://192.168.1.20:11434", "http://gpu-box:8080", "https://api.example.com",
                                 "http://0.0.0.0:8080"])
def test_another_computer_needs_opting_in(url):
    with pytest.raises(LLMError, match="is not this PC"):
        check_url(url)
    assert check_url(url, allow_remote=True) == url


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://127.0.0.1/x", "javascript:alert(1)", "127.0.0.1:8080",
                                 "http://"])
def test_only_http_addresses(url):
    with pytest.raises(LLMError, match="use http://host:port"):
        check_url(url, allow_remote=True)


def test_every_client_goes_through_the_check():
    with pytest.raises(LLMError, match="is not this PC"):
        make_client("ollama", "http://10.0.0.5:11434")
    assert make_client("llamacpp").url.startswith("http://127.0.0.1")
    assert make_client("openai", "http://10.0.0.5:1234", allow_remote=True).url == "http://10.0.0.5:1234"


def test_settings_opt_in_must_be_a_real_true():
    from gui import state
    for raw in ("true", 1, "yes", None):
        s = state.settings({"llm_url": "http://10.0.0.5:11434", "allow_remote_model": raw})
        assert s["allow_remote_model"] is False
        with pytest.raises(LLMError):
            state.llm(s)
    s = state.settings({"llm_url": "http://10.0.0.5:11434", "allow_remote_model": True})
    note = state.remote_note(state.llm(s))
    assert "project data is sent to 10.0.0.5 unencrypted" in note
    assert state.remote_note(state.llm(state.settings({}))) == ""


def test_report_says_when_data_went_to_another_computer(monkeypatch):
    import base64
    import io
    import zipfile

    import app as gui
    from gui import state
    from gui.state import SESSION
    from test_spec import book, run

    class Remote:
        url = "http://10.0.0.5:11434"
    monkeypatch.setattr(state, "llm", lambda s: Remote())
    gui.app.config["TESTING"] = True
    data = book({"A": [["Requirement", "Rung text"], ["", "XIC(A)OTE(B);"], ["", "XIC(B OTE(C);"]]})
    with gui.app.test_client() as c:
        _, v = run(c, data)
    SESSION.detach()
    report = zipfile.ZipFile(io.BytesIO(base64.b64decode(v["result"]["zip_b64"]))).read("Report.txt").decode()
    assert report.splitlines()[1].startswith("⚠ Model server on another computer: project data is sent to 10.0.0.5")
    assert state.remote_note(type("C", (), {})()) == ""          # a client without a url cannot break it


def test_l5x_size_cap(tmp_path):
    from l5x.reader import read_l5x
    with pytest.raises(ValueError, match="above the 0 MB limit"):
        read_l5x(b"<RSLogix5000Content/>" * 100, max_bytes=10)
    f = tmp_path / "big.L5X"
    f.write_bytes(b"x" * 2048)
    with pytest.raises(ValueError, match="limit"):
        read_l5x(f, max_bytes=1024)
