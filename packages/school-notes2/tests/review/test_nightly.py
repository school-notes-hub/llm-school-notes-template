import json

import pytest

from school_notes2.review import nightly
from school_notes2.state import phase
from school_notes2.state.errors import NeedsOwner

from .conftest import sh

GEN = ("# Tárgy\n\n<!-- school-notes:generated chapters -->\n{}\n"
       "<!-- /school-notes:generated -->\n\nKézi rész.\n")


def fake_rasterize(svgs, out_dir):
    made = []
    for svg in svgs:
        png = out_dir / (svg.stem + ".png")
        png.write_bytes(b"PNG")
        made.append(png)
    return made


def prepare(tmp_path, repos, **kw):
    args = dict(fetch_timeout=60, rasterize=fake_rasterize)
    args.update(kw)
    return nightly.prepare(tmp_path / "srv", "benedek", repos.repo, repos.wt, **args)


def test_empty_range_makes_no_task(tmp_path, repos):
    assert prepare(tmp_path, repos) is None
    assert phase.all_tasks(tmp_path / "srv", "benedek") == []


def test_prepare_writes_diff_images_and_moves_worktree(tmp_path, repos):
    repos.commit({"wiki/a/index.md": GEN.format("* régi")}, "index")
    sh("git", "push", "-q", "-f", "origin", "HEAD:claude-reviewed", cwd=repos.laptop)
    head = repos.commit({
        "wiki/a/index.md": GEN.format("* új generált sor"),
        "wiki/a/2026-10-02-ora-jegyzet.md": "# Óra\n\nSzöveg.\n",
        "wiki/log.md": "## 2026-10-02\n\n* új óra\n",
        "docs/evidence/pages/a/x.md": "# rekord\n",
        "publication/public.json": "{}\n",
        "sources/a/ora/p0001.jpg": b"\xff\xd8jpeg",
        "sources/a/ora/document.md": "# tankönyv\n",
        "wiki/assets/abra.svg": "<svg/>",
        "wiki/assets/kep.png": b"\x89PNG\x00",
    })
    task = prepare(tmp_path, repos)
    assert task.phase == "prepared" and task.get("T") == head and task.get("H") == head
    assert "wiki/a/index.md" not in [u["topic"] for u in task.get("units")]
    assert "wiki/a/2026-10-02-ora-jegyzet.md" in [u["topic"] for u in task.get("units")]
    assert sh("git", "rev-parse", "HEAD", cwd=repos.wt_path) == head


def test_no_size_or_image_cutoff(tmp_path, repos):
    commits = [repos.commit({f"wiki/{n}.md": "x" * 310000 + "\n",
                            **{f"sources/s/{n}-{i}.jpg": b"x" for i in range(31)}}, str(n)) for n in range(2)]
    task = prepare(tmp_path, repos)
    assert task.get("T") == task.get("H") == commits[-1]
    assert task.get("commits") == commits


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


def _task(root, commits, timed_out):
    t = phase.create(root, "benedek", "review", "cron", "prepared")
    t.update(commits=commits, timed_out=timed_out)
    return t



def test_pending_close_finds_reviewed_task(tmp_path):
    t = _task(tmp_path, ["c"], False)
    assert nightly.pending_close([t]) is None
    nightly.record_review(t, {"verdict": "ok", "findings": []})
    assert nightly.pending_close(phase.all_tasks(tmp_path, "benedek")).run_id == t.run_id
    with pytest.raises(Exception):
        nightly.record_review(t, {"verdict": "maybe", "findings": []})


def test_resume_old_prepared_input_adds_relation_keys(tmp_path, repos):
    repos.commit({"wiki/a.md": "# Nyitott kérdések\n\n<!-- q: a-datum -->\n1. Mi a dátum?\n"})
    task = prepare(tmp_path, repos)
    task.update(topic_review=False)  # Already prepared legacy tasks still resume.
    nightly.resume_prepared(task, repos.repo, repos.wt, fake_rasterize)
    target = task.dir / "in/relations.json"
    original = target.read_bytes()
    target.unlink()  # A prepared task from the previous contract.
    nightly.resume_prepared(task, repos.repo, repos.wt, fake_rasterize)
    assert target.read_bytes() == original
    assert json.loads(original)["pages"]["wiki/a.md"]["questions"] == ["a-datum"]
