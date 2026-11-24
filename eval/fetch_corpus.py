"""Fetch the public L5X exports listed in eval/corpus_sources.txt into a folder, for tests/test_corpus.py.

    python -m eval.fetch_corpus corpus/
    LLM4L5X_CORPUS=corpus pytest tests/test_corpus.py -q

Each repository is fetched at its pinned commit, without history, and only its .L5X files are checked out,
so the download stays small. A file whose bytes another repository already brought is dropped: the same
sample export shows up in several repositories. Nothing fetched here is ever committed.
"""
from __future__ import annotations

import fnmatch
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

SOURCES = Path(__file__).with_name("corpus_sources.txt")


def sources(path: Path = SOURCES) -> list[tuple[str, str, str, list[str]]]:
    """(repository, commit, licence, exclude globs) for each line that is not blank or a comment."""
    out = []
    for line in path.read_text("utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            repo, commit, licence, *exclude = line.split()
            out.append((repo, commit, licence, exclude))
    return out


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def fetch(dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    kept = 0
    for repo, commit, _licence, exclude in sources():
        root = dest / repo.replace("/", "_")
        if root.exists():
            shutil.rmtree(root)
        root.mkdir()
        _git(root, "init", "-q")
        _git(root, "fetch", "-q", "--depth", "1", "--filter=blob:none", f"https://github.com/{repo}", commit)
        files = [f for f in _git(root, "ls-tree", "-r", "--name-only", "FETCH_HEAD").splitlines()
                 if f.lower().endswith(".l5x") and not any(fnmatch.fnmatch(f, g) for g in exclude)]
        if files:
            subprocess.run(["git", "checkout", "-q", "FETCH_HEAD", "--pathspec-from-file=-"], cwd=root,
                           check=True, input="\n".join(files), text=True)
        shutil.rmtree(root / ".git")
        for f in files:
            p = root / f
            digest = hashlib.sha1(p.read_bytes()).hexdigest()
            if digest in seen:
                p.unlink()
            else:
                seen.add(digest)
                kept += 1
        print(f"{repo}: {sum(1 for _ in root.rglob('*') if _.is_file())} of {len(files)} files")
    return kept


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.exit("usage: python -m eval.fetch_corpus FOLDER")
    print(f"{fetch(Path(args[0]))} distinct L5X files in {args[0]}")


if __name__ == "__main__":
    main()
