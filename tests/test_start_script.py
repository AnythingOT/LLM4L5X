"""start.sh: packages live outside the download, installed once and again only when requirements.txt changes.

start.bat does the same on Windows (it cannot run here); this checks the decisions on Linux/macOS. The venv
and pip are stood in for, so the test is fast and offline: what is tested is when start.sh installs.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("sh"), reason="needs sh")


def download(tmp: Path, name: str, extra: str = "") -> Path:
    """A fresh copy of the repo as a zip download would give it: start.sh and requirements.txt."""
    d = tmp / name
    d.mkdir()
    script = (REPO / "start.sh").read_text()
    script = script.replace('exec "$PY" app.py', 'echo STARTED')
    script = script.replace('"$PY" -m pip install --upgrade pip >/dev/null && "$PY" -m pip install -r requirements.txt',
                            "echo PIP-INSTALL")
    # a venv stand-in: a folder whose python is this test's Python (a link: never written through)
    script = script.replace('python3 -m venv "$VENV"', f'mkdir -p "$VENV/bin" && ln -sf "{sys.executable}" "$VENV/bin/python"')
    (d / "start.sh").write_text(script)
    (d / "requirements.txt").write_text((REPO / "requirements.txt").read_text() + extra)
    return d


def start(d: Path, venv: Path) -> list[str]:
    out = subprocess.run(["sh", str(d / "start.sh")], env={**os.environ, "LLM4L5X_VENV": str(venv)},
                         capture_output=True, text=True, check=True).stdout
    return [ln for ln in out.splitlines() if ln in ("PIP-INSTALL", "STARTED") or ln.startswith(("First", "The pack"))]


def test_packages_are_installed_once_and_a_new_download_starts_at_once(tmp_path):
    venv = tmp_path / "home" / "venv"
    first = start(download(tmp_path, "dl1"), venv)
    assert first[0].startswith("First start") and first[1:] == ["PIP-INSTALL", "STARTED"]
    assert start(tmp_path / "dl1", venv) == ["STARTED"]  # started again: nothing installed
    assert start(download(tmp_path, "dl2"), venv) == ["STARTED"]  # a new download, same packages
    assert start(download(tmp_path, "dl3", "newpkg==1.0\n"), venv) == ["PIP-INSTALL", "STARTED"]  # changed
    assert start(tmp_path / "dl3", venv) == ["STARTED"]


def test_a_venv_whose_python_is_gone_is_made_again(tmp_path):
    venv = tmp_path / "home" / "venv"
    start(download(tmp_path, "dl1"), venv)
    py = venv / "bin" / "python"
    py.unlink()  # remove the link first: writing to it would write to the Python it points at
    py.write_text("#!/bin/sh\nexit 1\n")
    py.chmod(0o755)
    again = start(tmp_path / "dl1", venv)
    assert again[0].startswith("The package folder no longer works") and again[-2:] == ["PIP-INSTALL", "STARTED"]
