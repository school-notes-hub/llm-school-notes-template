import pytest

from school_notes2.review import close, nightly
from school_notes2.state import phase
from school_notes2.state.errors import NeedsOwner, Transient
from school_notes2.wiki import frontmatter as fm

from .conftest import sh

IDENT = close.Identity("benedek", "opus-5.5/high", "2.0.0", "2026-10-04", "2026-10-04T03:20:00+02:00")
REVIEW = {"verdict": "changes",
          "findings": [{"id": "R1", "file": "wiki/a.md", "line": 1, "problem": "Elírás.", "relates_to": None}],
          "figures": [{"file": "wiki/assets/f.svg", "page": "wiki/a.md", "verdict": "jó",
                       "observed": "Két nyíl."}]}


def reviewed(tmp_path, repos, **kw):
    args = dict(max_images=30, max_diff_kb=300, fetch_timeout=60, rasterize=lambda s, o: [])
    args.update(kw)
    task = nightly.prepare(tmp_path / "srv", "benedek", repos.repo, repos.wt, **args)
    nightly.record_review(task, REVIEW)
    return task


def file_at(repos, ref, path):
    return sh("git", "--git-dir", str(repos.origin), "show", f"{ref}:{path}")


def test_quiet_night_marker_includes_report(tmp_path, repos):
    head = repos.commit({"wiki/a.md": "szöveg\n", "wiki/assets/f.svg": "<svg/>"})
    task = reviewed(tmp_path, repos)
    r, m = close.close(task, repos.repo, repos.wt, IDENT)
    assert m == r and repos.remote("main") == r and repos.remote("claude-reviewed") == r
    assert sh("git", "--git-dir", str(repos.origin), "rev-parse", f"{r}^") == head
    report = file_at(repos, r, "docs/review/2026-10-04-review.md")
    assert fm.split(report + "\n").meta["items"] == {"R1": "open"}
    assert "review-index" in file_at(repos, r, "docs/review/index.md")
    assert "Két nyíl." in file_at(repos, r, "docs/evidence/pages/a.md")
    msg = sh("git", "--git-dir", str(repos.origin), "log", "-1", "--format=%B", r)
    assert f"Run-Id: {task.run_id}" in msg and "Kind: review" in msg
    assert phase.load(task.dir).phase == "done"


def test_commit_arriving_during_review_sets_marker_to_t(tmp_path, repos):
    t = repos.commit({"wiki/a.md": "x\n", "wiki/assets/f.svg": "<svg/>"})
    task = reviewed(tmp_path, repos)
    later = repos.commit({"wiki/b.md": "laptop\n"})
    r, m = close.close(task, repos.repo, repos.wt, IDENT)
    assert m == t and repos.remote("claude-reviewed") == t
    assert sh("git", "--git-dir", str(repos.origin), "rev-parse", f"{r}^") == later


def test_limit_cut_sets_marker_to_t(tmp_path, repos):
    t = repos.commit({"wiki/a.md": "x" * 3000 + "\n", "wiki/assets/f.svg": "<svg/>"})
    repos.commit({"wiki/b.md": "y" * 3000 + "\n"})
    task = reviewed(tmp_path, repos, max_diff_kb=1)
    r, m = close.close(task, repos.repo, repos.wt, IDENT)
    assert m == t != r


def test_atomic_push_moves_neither_ref(tmp_path, repos):
    repos.commit({"wiki/a.md": "x\n", "wiki/assets/f.svg": "<svg/>"})
    task = reviewed(tmp_path, repos)
    main_before, marker_before = repos.remote("main"), repos.remote("claude-reviewed")
    hook = repos.origin / "hooks" / "update"
    hook.write_text('#!/bin/sh\n[ "$1" = refs/heads/claude-reviewed ] && exit 1\nexit 0\n')
    hook.chmod(0o755)
    with pytest.raises(NeedsOwner):
        close.close(task, repos.repo, repos.wt, IDENT)
    assert repos.remote("main") == main_before
    assert repos.remote("claude-reviewed") == marker_before


def test_race_rebuilds_on_fresh_main(tmp_path, repos, monkeypatch):
    t = repos.commit({"wiki/a.md": "x\n", "wiki/assets/f.svg": "<svg/>"})
    task = reviewed(tmp_path, repos)
    real, calls = close._push, []

    def racing(repo, r, m, timeout):
        calls.append(r)
        if len(calls) == 1:
            repos.commit({"wiki/c.md": "közben\n"})
        real(repo, r, m, timeout)

    monkeypatch.setattr(close, "_push", racing)
    r, m = close.close(task, repos.repo, repos.wt, IDENT)
    assert len(calls) == 2 and m == t and repos.remote("main") == r
    assert sh("git", "--git-dir", str(repos.origin), "ls-tree", "--name-only", r,
              "docs/review/").count("2026-10-04-review") == 1


def test_lost_reply_is_decided_by_ls_remote(tmp_path, repos, monkeypatch):
    repos.commit({"wiki/a.md": "x\n", "wiki/assets/f.svg": "<svg/>"})
    task = reviewed(tmp_path, repos)
    real = close._push

    def lost(repo, r, m, timeout):
        real(repo, r, m, timeout)
        raise Transient("connection reset after send")

    monkeypatch.setattr(close, "_push", lost)
    r, m = close.close(task, repos.repo, repos.wt, IDENT)
    assert repos.remote("main") == r and phase.load(task.dir).phase == "done"


def test_resume_in_pushing_phase_needs_no_new_commit(tmp_path, repos, monkeypatch):
    repos.commit({"wiki/a.md": "x\n", "wiki/assets/f.svg": "<svg/>"})
    task = reviewed(tmp_path, repos)
    r, m = close.close(task, repos.repo, repos.wt, IDENT)
    task.data["phase"] = "pushing"
    task.save()
    monkeypatch.setattr(close, "_commit", lambda *a: pytest.fail("no new commit expected"))
    assert close.close(task, repos.repo, repos.wt, IDENT) == (r, m)


def test_discard_timeout_steps_marker_past_commit(tmp_path, repos):
    stuck = repos.commit({"wiki/a.md": "nagy\n"})
    repos.commit({"wiki/b.md": "utána\n"})
    task = phase.create(tmp_path / "srv", "benedek", "review", "cron", "closing")
    r, m = close.discard_timeout(task, repos.repo, repos.wt, IDENT, stuck)
    assert m == stuck and repos.remote("claude-reviewed") == stuck and repos.remote("main") == r
    assert "Nem átnézve" in file_at(repos, r, "docs/review/2026-10-04-review.md")
