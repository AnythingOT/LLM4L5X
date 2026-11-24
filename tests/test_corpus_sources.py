"""The list of public exports CI fetches: pinned, permissively licensed, never one of ours."""
import re

from eval.fetch_corpus import sources


def test_every_source_is_pinned_and_permissive():
    rows = sources()
    assert len(rows) >= 20
    for repo, commit, licence, _exclude in rows:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+", repo), repo
        assert re.fullmatch(r"[0-9a-f]{40}", commit), (repo, commit)  # a commit, never a branch that moves
        assert licence in {"MIT", "Apache-2.0"}, (repo, licence)
        assert not repo.lower().startswith("anythingot/"), repo  # public exports only, not the owner's
    assert len({r for r, *_ in rows}) == len(rows)
