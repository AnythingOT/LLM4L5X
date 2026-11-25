"""The shape of the repository: which folder may import which, a README per folder, STRUCTURE.txt current.

A new import across folders is a design decision: change ALLOWED in the same PR and say why there.
"""
import ast
import shutil
from pathlib import Path

import pytest

from eval import structure

ROOT = Path(__file__).resolve().parent.parent
PRODUCT = {"core", "l5x", "explain", "lint", "udt", "generate", "devices", "testcases", "library"}
FOLDERS = PRODUCT | {"eval", "gui"}
ALLOWED = {
    "core": set(),                             # the base: no other folder
    "l5x": {"core"},
    "explain": {"core", "l5x"},
    "lint": {"core", "l5x"},
    "udt": {"core", "l5x", "lint"},            # the project index (lint.context) finds layout risks
    "generate": {"core", "l5x", "lint", "udt"},  # the model's answer is linted before it is accepted
    "devices": set(),                          # sees tag values only
    "testcases": {"core", "l5x", "generate"},  # reads the requirements workbook
    "library": {"core", "lint", "devices", "testcases"},
    "gui": PRODUCT,                            # every product folder, and Flask; never eval
    "eval": FOLDERS - {"eval"},                # developers' measuring: anything
}


def imports(folder: str) -> dict[str, set[str]]:
    """Top-level names imported anywhere in a folder (inside functions too) -> the files importing them."""
    out: dict[str, set[str]] = {}
    for f in (ROOT / folder).rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for n in names:
                out.setdefault(n.split(".")[0], set()).add(str(f.relative_to(ROOT)))
    return out


@pytest.mark.parametrize("folder", sorted(FOLDERS))
def test_each_folder_imports_only_what_it_may(folder):
    used = imports(folder)
    wrong = {m: sorted(files) for m, files in used.items() if m in FOLDERS and m != folder and m not in ALLOWED[folder]}
    assert not wrong, f"{folder}/ may not import {sorted(wrong)}: {wrong}"
    if folder != "gui":
        assert "flask" not in used, f"only gui/ uses Flask: {sorted(used.get('flask', []))}"


def test_no_import_cycles_between_folders():
    graph = {f: ALLOWED[f] & FOLDERS for f in FOLDERS}
    seen, stack = set(), []

    def visit(n):
        assert n not in stack, f"cycle: {' -> '.join(stack + [n])}"
        if n in seen:
            return
        stack.append(n)
        for m in graph[n]:
            visit(m)
        stack.pop()
        seen.add(n)

    for f in sorted(FOLDERS):
        visit(f)


@pytest.mark.parametrize("folder", sorted(FOLDERS | {"tests"}))
def test_every_folder_has_a_readme_that_says_what_it_is(folder):
    readme = ROOT / folder / "README.md"
    assert readme.exists(), f"{folder}/README.md is missing"
    assert structure.folder_line(folder), f"{folder}/README.md has no first line under its title"


@pytest.mark.skipif(not (ROOT / ".git").exists() or not shutil.which("git"), reason="needs a git checkout")
def test_structure_txt_is_current():
    current = (ROOT / "STRUCTURE.txt").read_text(encoding="utf-8")
    assert current == structure.render(), "STRUCTURE.txt is out of date: run  python -m eval.structure"
