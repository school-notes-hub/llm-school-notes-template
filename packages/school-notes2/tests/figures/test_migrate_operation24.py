"""Real local Git migration, no remote service, with T-095 crash injection."""

import hashlib
from types import SimpleNamespace

import pytest

from school_notes2.figures import migrate_operation as operation, migrate_pending as migration, pending
from school_notes2.git import repos
from school_notes2.log import Log
from school_notes2.state import phase, safefs
from school_notes2.state.lock import StudentLock
from school_notes2.wiki.pages import sha256
from tests.conftest import make_origin


@pytest.fixture
def ctx(tmp_path, git_factory, local_origin):
    header = b"<svg/>"
    import json
    origin = make_origin(tmp_path, {
        "wiki/index.md": "# Wiki\n",
        "wiki/m/topic.md": "---\ntype: topic\ntitle: Topic\n---\n\n![Header](../assets/header.svg)\n\nText.\n",
        "wiki/assets/header.svg": header,
        "publication/public.json": json.dumps({"assets": [{"path": "wiki/assets/header.svg",
            "sha256": hashlib.sha256(header).hexdigest(), "rights": "authored"}]}),
    })
    bare = git_factory(tmp_path / "repos/learner.git")
    repos.ensure_bare(bare, str(origin), repos.NOTES_REFSPECS)
    repos.fetch(bare, 5)
    work = tmp_path / "work/notes"
    repos.ensure_worktree(bare, work, "origin/main")
    wt = repos.worktree_git(bare, work)
    cfg = SimpleNamespace(state_dir=tmp_path / "state", timeouts=SimpleNamespace(fetch_s=5, push_s=5, ls_remote_s=5))
    from school_notes2.images.settings import ImageSettings
    from decimal import Decimal
    images = ImageSettings("learner", work, tmp_path / "unused.py", cfg.state_dir / "images",
        cfg.state_dir / "plans", cfg.state_dir / "images.lock", tmp_path / "key", Decimal("10"), Decimal("5"))
    return SimpleNamespace(image_settings=lambda: images, name="learner", notes_path=work, cfg=cfg, bare=lambda: bare,
        worktree=lambda _: wt, task_root=lambda: tmp_path, lock=lambda: StudentLock(cfg.state_dir, "learner"),
        log=Log(None, console=False))


def tree(root):
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file()}


def test_dry_run_does_not_write_even_state_or_git(ctx, tmp_path):
    # Production dry-run uses a silent Git; fixture log files must also stay unchanged.
    before = tree(tmp_path)
    assert operation.run(ctx, dry_run=True) == 0
    assert tree(tmp_path) == before
    assert not ctx.cfg.state_dir.exists()


@pytest.mark.parametrize("boundary", ["before-commit", "commit-object", "after-commit", "after-push"])
def test_commit_and_push_resume(ctx, monkeypatch, boundary):
    original = type(ctx.worktree("notes")).run
    fired = []
    def crash(git, *args, **kw):
        if boundary == "before-commit" and args[0] == "commit-tree" and not fired:
            fired.append(True)
            raise KeyboardInterrupt()
        if boundary == "after-commit" and args[0] == "push" and not fired:
            fired.append(True)
            raise KeyboardInterrupt()
        result = original(git, *args, **kw)
        if boundary == "commit-object" and args[0] == "commit-tree" and not fired:
            fired.append(True)
            raise KeyboardInterrupt()
        if boundary == "after-push" and args[0] == "push" and not fired:
            fired.append(True)
            raise KeyboardInterrupt()
        return result
    monkeypatch.setattr(type(ctx.worktree("notes")), "run", crash)
    with pytest.raises(KeyboardInterrupt):
        operation.run(ctx, push=True)
    assert operation.run(ctx, push=True) == 0
    wt = ctx.worktree("notes")
    commit = repos.rev(wt, "origin/main")
    assert wt.out("rev-list", "--count", "origin/main").strip() == "2"
    assert "School-Notes-Run: fix" in wt.out("show", "-s", "--format=%B", commit)
    assert repos.ls_remote(wt, "refs/heads/main", 5) == commit
    assert len(pending.load(ctx.notes_path)) == 1
    text = safefs.read_text(ctx.notes_path, "wiki/m/topic.md")
    assert "-->\n\n\n" not in text
    manifest = safefs.read_json(ctx.notes_path, "publication/public.json")
    assert next(p for p in manifest["pages"] if p["path"] == "wiki/m/topic.md")["sha256"] == sha256(ctx.notes_path, "wiki/m/topic.md")
    assert not wt.out("status", "--porcelain").strip()
    assert operation.run(ctx, push=True) == 0
    assert repos.rev(wt, "origin/main") == commit


def test_local_commit_is_resumed_after_worktree_switch(ctx):
    assert operation.run(ctx) == 0
    saved = safefs.read_json(ctx.cfg.state_dir / ctx.name, operation.JOURNAL)
    wt = ctx.worktree("notes")
    wt.run("switch", "--detach", "origin/main")
    assert operation.run(ctx, push=True) == 0
    assert repos.rev(wt, "origin/main") == saved["commit"]


@pytest.mark.parametrize("dry_run", [False, True])
def test_lock_and_open_notes_are_refused(ctx, dry_run, capsys):
    lock = ctx.lock()
    assert lock.try_acquire("another-run")
    try:
        assert operation.run(ctx, dry_run=dry_run) == 2
        assert "lock is held" in capsys.readouterr().err
    finally:
        lock.release()
    for status in ("writing", "needs_owner", "waiting_quota"):
        task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "writing" if status == "needs_owner" else status)
        assert operation.run(ctx, dry_run=dry_run) == 2
        assert "finish or discard" in capsys.readouterr().err
        task.set_phase("done")
    assert not safefs.is_file(ctx.notes_path, migration.MARK)


def test_untracked_files_are_not_committed(ctx, capsys):
    safefs.write_text(ctx.notes_path, "unrelated.txt", "private work")
    assert operation.run(ctx) == 2
    assert "not clean" in capsys.readouterr().err
    assert not safefs.is_file(ctx.notes_path, migration.MARK)


def test_worktree_git_file_is_never_read(ctx):
    safefs.write_text(ctx.notes_path, ".git", "untrusted, not a gitdir")
    assert operation.run(ctx, dry_run=True) == 0
    assert operation.run(ctx, push=True) == 0


def test_ls_remote_mismatch_is_refused_then_resumes(ctx, monkeypatch, capsys):
    real = repos.ls_remote
    monkeypatch.setattr(repos, "ls_remote", lambda *a: "0" * 40)
    assert operation.run(ctx, push=True) == 2
    assert "rerun the same --push" in capsys.readouterr().err
    monkeypatch.setattr(repos, "ls_remote", real)
    assert operation.run(ctx, push=True) == 0


def test_lost_host_receipts_do_not_reset_migrated_repository(ctx):
    assert operation.run(ctx, push=True) == 0
    state = ctx.cfg.state_dir / ctx.name
    for name in (operation.JOURNAL, migration.RECEIPT):
        safefs.unlink(state, name)
    before = ctx.worktree("notes").out("rev-parse", "origin/main").strip()
    assert operation.run(ctx, push=True) == 0
    assert operation.run(ctx, push=True) == 0
    assert ctx.worktree("notes").out("rev-parse", "origin/main").strip() == before
    assert safefs.read_json(ctx.notes_path, migration.MARK)["version"] == migration.VERSION
