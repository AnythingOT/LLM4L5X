"""Write STRUCTURE.txt: every folder and file of the repository, each with one line on what it is.

The lines come from the code itself: a folder's README.md (its first line after the title) and a Python
file's docstring (its first line). So the map cannot say something the code does not; tests/test_structure.py
fails when STRUCTURE.txt is out of date. Run:  python -m eval.structure
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "corpus", "runs"}
HEAD = ("LLM4L5X: every folder and file, with what it is.\n"
        "Made by `python -m eval.structure` from the folders' README.md and the files' docstrings;\n"
        "a test fails when this file is out of date. Edit those, then run the command again.\n")
# files with no docstring of their own to read from
KNOWN = {
    "app.py": "Start the app: python app.py, then http://127.0.0.1:5000",
    "cli.py": "Command line: compile, explain, inspect, validate, fix, ask, survey and more (python cli.py -h)",
    "start.bat": "Windows: double-click to install the packages once and start the app",
    "start.sh": "Linux/macOS: the same as start.bat",
    "requirements.txt": "Python packages, exact versions",
    "README.md": "What it does and how to start",
    "LICENSE": "MIT licence",
    "THIRD_PARTY_NOTICES.md": "Licences of the packages and icons this project uses",
    "STRUCTURE.txt": "This map",
    "pytest.ini": "pytest settings",
    "ruff.toml": "Code checks (ruff)",
    ".gitattributes": "Line endings: .bat files keep CRLF",
    ".gitignore": "Files git leaves out",
    ".github/workflows/ci.yml": "CI: code checks and tests on every push",
    "docs/DESIGN.md": "How it works inside, and why",
    "docs/DEVELOPMENT.md": "For developers: layout, tests, the instruction suite",
    "docs/HANDOVER.md": "Start here when picking the work up: map of the code, working rules, results",
    "docs/ROADMAP.md": "What is done and what is next",
    "docs/GUIDE.md": "For users: every feature in detail",
}


def files() -> list[str]:
    """Tracked and new (not ignored) files; without git (a zip download), every file on disk."""
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.split("\n")
        names = [n for n in out if n and (ROOT / n).exists()]
    except (OSError, subprocess.CalledProcessError):
        names = [str(p.relative_to(ROOT)).replace("\\", "/") for p in ROOT.rglob("*") if p.is_file()]
    return sorted(n for n in names if not SKIP_DIRS & set(n.split("/")) and n != "STRUCTURE.txt") + ["STRUCTURE.txt"]


def first_line(text: str) -> str:
    """The first sentence of the first paragraph that is not a title (a docstring may wrap it over lines)."""
    para: list[str] = []
    for line in text.strip().splitlines():
        line = line.strip()
        if line.startswith(("#", "|", "```")) or (not line and not para):
            if para:
                break
            continue
        if not line:
            break
        para.append(line)
    words = " ".join(para)
    end = words.find(". ")
    return words[: end + 1] if end >= 0 else words


def describe(name: str) -> str:
    if name in KNOWN:
        return KNOWN[name]
    if name.endswith("/README.md"):
        return ""  # its first line is already the folder's line
    path = ROOT / name
    if name.endswith(".py"):
        try:
            return first_line(ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or "")
        except SyntaxError:
            return ""
    if name.endswith(".md"):
        return first_line(path.read_text(encoding="utf-8"))
    return ""


def folder_line(folder: str) -> str:
    readme = ROOT / folder / "README.md"
    return first_line(readme.read_text(encoding="utf-8")) if readme.exists() else ""


def render() -> str:
    names = files()
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for n in sorted(names, key=lambda n: (n.count("/") > 0, n.lower())):
        parts = n.split("/")
        for depth in range(1, len(parts)):
            folder = "/".join(parts[:depth])
            if folder not in seen:
                seen.add(folder)
                rows.append(("  " * (depth - 1) + parts[depth - 1] + "/", folder_line(folder)))
        rows.append(("  " * (len(parts) - 1) + parts[-1], describe(n)))
    width = max(len(a) for a, _ in rows) + 2
    body = "\n".join(f"{a:<{width}}{b}".rstrip() for a, b in rows)
    return HEAD + "\n" + body + "\n"


def main() -> None:
    (ROOT / "STRUCTURE.txt").write_text(render(), encoding="utf-8", newline="\n")
    print("STRUCTURE.txt written")


if __name__ == "__main__":
    main()
