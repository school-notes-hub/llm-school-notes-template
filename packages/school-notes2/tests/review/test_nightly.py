"""Nightly review from the diff (owner, 2026-10-05): range, inputs, no call without a diff."""

import json

import pytest

from school_notes2.review import nightly
from school_notes2.state import phase
from school_notes2.state.errors import NeedsOwner

from .conftest import sh

GEN = ("# Tárgy\n\n<!-- school-notes:generated chapters -->\n{}\n"
       "<!-- /school-notes:generated -->\n\nKézi rész.\n")


def prepare(tmp_path, repos):
    return nightly.prepare(tmp_path / "srv", "benedek", repos.repo, repos.wt, fetch_timeout=60)


def test_empty_range_makes_no_task(tmp_path, repos):
    assert prepare(tmp_path, repos) is None
    assert phase.all_tasks(tmp_path / "srv", "benedek") == []


def test_range_without_a_wiki_diff_makes_no_call(tmp_path, repos):
    repos.commit({"docs/review/x.md": "# admin\n", "publication/public.json": "{}\n"}, "admin\n\nSchool-Notes-Run: fix")
    assert prepare(tmp_path, repos) is None


def test_prepare_writes_the_plain_diff_commits_requests_and_sources(tmp_path, repos):
    repos.commit({"wiki/a/index.md": GEN.format("* régi")}, "index")
    sh("git", "push", "-q", "-f", "origin", "HEAD:claude-reviewed", cwd=repos.laptop)
    request = [{"page": "wiki/a/2026-10-02-ora-jegyzet.md", "reason": "Új levezetés."}]
    first = repos.commit({"wiki/a/index.md": GEN.format("* új generált sor"),
                          "sources/a/ora/p0001.jpg": b"\xff\xd8jpeg"},
                         "notes\n\nSchool-Notes-Run: run\nSchool-Notes-Review-Request: " + json.dumps(request))
    head = repos.commit({"wiki/a/2026-10-02-ora-jegyzet.md": "# Óra\n\nSzöveg.\n"}, "fix\n\nSchool-Notes-Run: fix")
    task = prepare(tmp_path, repos)
    assert task.phase == "prepared" and task.get("H") == head and task.get("diff_review")
    patch = (task.dir / "in/diff.patch").read_text()
    # The plain Git diff: generated blocks are not hidden; the reviewer decides.
    assert "+* új generált sor" in patch and "+Szöveg." in patch
    commits = json.loads((task.dir / "in/commits.json").read_text())
    assert [(c["commit"], c["run"]) for c in commits] == [(first, "run"), (head, "fix")]
    assert json.loads((task.dir / "in/review-requests.json").read_text()) == [{**request[0], "commit": first}]
    assert json.loads((task.dir / "in/sources.json").read_text()) == ["sources/a/ora/p0001.jpg"]
    assert sh("git", "rev-parse", "HEAD", cwd=repos.wt_path) == head


def test_added_lines_and_triage_keep_only_author_errors_on_the_diff(tmp_path, repos):
    base = "# Cím\n\nRégi sor.\n"
    repos.commit({"wiki/a.md": base}, "seed page")
    sh("git", "push", "-q", "-f", "origin", "HEAD:claude-reviewed", cwd=repos.laptop)
    block = "<!-- school-notes:generated pending -->\n⏳ Ellenőrizzük.\n<!-- /school-notes:generated -->\n"
    repos.commit({"wiki/a.md": base + "Új sor.\n" + block})
    task = prepare(tmp_path, repos)
    patch = (task.dir / "in/diff.patch").read_text()
    assert nightly.added_lines(patch) == {"wiki/a.md": {4, 5, 6, 7}}
    finding = {"severity": "hiba", "file": "wiki/a.md", "quote": "q", "problem": "P", "relates_to": None}
    review = {"owner_notes": ["Megjegyzés."], "items": [], "findings": [
        {**finding, "id": "R1", "line": 4}, {**finding, "id": "R2", "line": 3},
        {**finding, "id": "R3", "line": 6}, {**finding, "id": "R4", "line": 4, "severity": "javaslat"}]}
    items, notes = nightly.triage(review, patch, repos.wt_path)
    assert [f["id"] for f in items] == ["R1"]  # unchanged line, tool block and advice are notes
    assert len(notes) == 4 and notes[0] == "Megjegyzés."


def test_marker_not_ancestor_needs_owner(tmp_path, repos):
    sh("git", "switch", "-q", "--orphan", "other", cwd=repos.laptop)
    (repos.laptop / "o.md").write_text("o\n")
    sh("git", "add", "-A", cwd=repos.laptop)
    sh("git", "commit", "-q", "-m", "orphan", cwd=repos.laptop)
    sh("git", "push", "-q", "-f", "origin", "HEAD:claude-reviewed", cwd=repos.laptop)
    with pytest.raises(NeedsOwner):
        prepare(tmp_path, repos)


def test_missing_marker_needs_owner(tmp_path, repos):
    sh("git", "push", "-q", "origin", ":claude-reviewed", cwd=repos.laptop)
    with pytest.raises(NeedsOwner, match="marker"):
        prepare(tmp_path, repos)


def test_pending_close_finds_only_reviewed_diff_tasks(tmp_path):
    task = phase.create(tmp_path, "benedek", "review", "cron", "prepared")
    task.update(diff_review=True)
    assert nightly.pending_close([task]) is None
    task.set_phase("reviewed")
    assert nightly.pending_close(phase.all_tasks(tmp_path, "benedek")).run_id == task.run_id
    legacy = phase.create(tmp_path, "benedek", "review", "cron", "reviewed")
    assert nightly.pending_close([legacy]) is None
