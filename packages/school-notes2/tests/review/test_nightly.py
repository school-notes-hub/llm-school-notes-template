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
    args = dict(max_images=30, max_diff_kb=300, fetch_timeout=60, rasterize=fake_rasterize)
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
    patch = (task.dir / "in/diff.patch").read_text(encoding="utf-8")
    assert "+++ b/wiki/a/2026-10-02-ora-jegyzet.md" in patch and "wiki/log.md" in patch
    assert "docs/evidence/pages/a/x.md" in patch
    assert "generált sor" not in patch and "wiki/a/index.md" not in patch
    assert "public.json" not in patch and "tankönyv" not in patch
    listing = json.loads((task.dir / "in/images.json").read_text())
    assert [i["path"] for i in listing] == ["sources/a/ora/p0001.jpg", "wiki/assets/abra.svg",
                                            "wiki/assets/kep.png"]
    assert all((task.dir / "in" / i["file"]).is_file() for i in listing)
    assert sh("git", "rev-parse", "HEAD", cwd=repos.wt_path) == head


def test_limits_cut_the_range_but_take_at_least_one_commit(tmp_path, repos):
    big = "x" * 3000 + "\n"
    first = repos.commit({"wiki/a.md": big}, "one")
    repos.commit({"wiki/b.md": big}, "two")
    head = repos.commit({"wiki/c.md": big}, "three")
    task = prepare(tmp_path, repos, max_diff_kb=1)
    assert task.get("T") == first and task.get("H") == head and task.get("commits") == [first]


def test_image_limit(tmp_path, repos):
    a = repos.commit({"sources/s/1.jpg": b"1", "sources/s/2.jpg": b"2"}, "a")
    repos.commit({"sources/s/3.jpg": b"3"}, "b")
    assert prepare(tmp_path, repos, max_images=2).get("T") == a


def test_halving_after_timeout(tmp_path, repos):
    commits = [repos.commit({f"wiki/{n}.md": "x\n"}, str(n)) for n in range(4)]
    first = prepare(tmp_path, repos)
    assert first.get("commits") == commits
    nightly.record_timeout(first)
    assert not first.open and nightly.next_cap(first) == 2
    second = prepare(tmp_path, repos, previous=first)
    assert second.get("commits") == commits[:2]


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


def test_stuck_commit_two_nights(tmp_path):
    assert nightly.stuck_commit([_task(tmp_path, ["c1"], True)]) is None
    second = _task(tmp_path, ["c1"], True)
    assert nightly.stuck_commit(phase.all_tasks(tmp_path, "benedek")) == "c1"
    assert nightly.stuck_commit([second, _task(tmp_path, ["c1", "c2"], True)]) is None
    assert nightly.stuck_commit([second, _task(tmp_path, ["c1"], False)]) is None


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
    target = task.dir / "in/relations.json"
    original = target.read_bytes()
    target.unlink()  # A prepared task from the previous contract.
    nightly.resume_prepared(task, repos.repo, repos.wt, fake_rasterize)
    assert target.read_bytes() == original
    assert json.loads(original)["pages"]["wiki/a.md"]["questions"] == ["a-datum"]
