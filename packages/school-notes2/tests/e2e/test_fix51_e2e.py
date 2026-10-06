"""Fix-51 end to end: a nightly review item, committed and pushed from the review worktree,
is visible to `ready()` and the status at once, and the next round starts its fix run even
when the learner has no other work (Barna, 2026-10-06)."""

import subprocess

from school_notes2.flows import fetch as fetch_flow, nightly as nightly_flow, run as run_flow, work_pending
from school_notes2.git import repos
from school_notes2.state import phase
from tests.e2e.test_nightly_e2e import ENV, laptop_commit
from tests.e2e.test_run_e2e import show, world  # noqa: F401 - shared fixture


def git(wt, *args):
    return subprocess.run(["git", "-C", str(wt), *args], capture_output=True, text=True, check=True, env=ENV).stdout.strip()


def test_nightly_item_is_visible_and_starts_a_fix_run(world, tmp_path, monkeypatch):
    ctx, origin, drive, package = world
    monkeypatch.setattr(fetch_flow, "drive_client", lambda ctx: None)    # no Drive work
    seed = git(ctx.notes_path, "rev-parse", "HEAD")
    subprocess.run(["git", f"--git-dir={origin}", "update-ref", "refs/heads/claude-reviewed", seed], check=True)
    laptop_commit(tmp_path, origin, "wiki/proba/elso.md", show(origin, "main:wiki/proba/elso.md") + "\nÚj bekezdés.\n")
    assert nightly_flow.nightly(ctx) == 0, ctx.cfg.log_path.read_text()[-2000:]
    main = subprocess.run(["git", f"--git-dir={origin}", "rev-parse", "main"],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert git(ctx.notes_path, "rev-parse", "HEAD") == main
    assert work_pending.ready(ctx)
    lines = work_pending.completion(ctx)
    assert "1 nyitott tétel" in lines[1] and "indítható munka" in lines[0], lines
    started = []
    monkeypatch.setattr(run_flow, "advance", lambda ctx, task: started.append(task))
    assert run_flow.run(ctx) == 0, ctx.cfg.log_path.read_text()[-2000:]
    assert len(started) == 1 and started[0].get("mode") == "fix"
    assert [i["item_id"] for i in started[0].get("open_review_items")] == ["R1"]
    from school_notes2.flows import status
    text = status.render(status.summary(ctx))
    assert "review-tételek: nyitott 1" in text and "mögött" not in text


def pushed_review(ctx, origin, tmp_path):
    """origin/main moved by the review worktree, as after a nightly report."""
    review = ctx.worktree("review")
    review.run("fetch", "origin", "refs/heads/main:refs/remotes/origin/main")
    review.run("switch", "--detach", "--discard-changes", "refs/remotes/origin/main")
    (review.work_tree / "docs/review/2026-10-06-review.md").write_text(
        "# Review\n\n<!-- items\nR1: open\n-->\n", encoding="utf-8")
    review.run("add", "-A")
    review.run("commit", "-qm", "review(benedek): 1 megállapítás")
    review.run("push", "origin", "HEAD:refs/heads/main")
    return repos.rev(review, "HEAD")


def test_a_run_holding_the_worktree_and_stray_edits_are_never_moved(world, tmp_path, monkeypatch):
    """The catch-up never touches an open run's worktree, stray edits or a commit that is not
    on origin/main; the status then tells that its numbers are old."""
    from school_notes2.flows import notes_sync, status
    ctx, origin, drive, package = world
    seed = git(ctx.notes_path, "rev-parse", "HEAD")
    main = pushed_review(ctx, origin, tmp_path)
    assert repos.rev(ctx.worktree("notes"), "refs/remotes/origin/main") == main
    task = phase.create(ctx.task_root(), "benedek", "notes", "cron", "moved")
    assert notes_sync.catch_up(ctx) == "busy" and git(ctx.notes_path, "rev-parse", "HEAD") == seed
    task.data["closed"] = True
    task.save()
    (ctx.notes_path / "wiki/proba/elso.md").write_text("kézi szerkesztés\n", encoding="utf-8")
    assert notes_sync.catch_up(ctx) == "refused_dirty"
    assert (ctx.notes_path / "wiki/proba/elso.md").read_text(encoding="utf-8") == "kézi szerkesztés\n"
    assert "1 committal az origin/main mögött" in status.render(status.summary(ctx))
    git(ctx.notes_path, "commit", "-qam", "helyi commit")
    local = git(ctx.notes_path, "rev-parse", "HEAD")
    assert notes_sync.catch_up(ctx) == "refused_diverged" and git(ctx.notes_path, "rev-parse", "HEAD") == local
    git(ctx.notes_path, "reset", "-q", "--hard", seed)
    assert notes_sync.catch_up(ctx) == "moved" and git(ctx.notes_path, "rev-parse", "HEAD") == main
    assert notes_sync.catch_up(ctx) == "current"
    assert "mögött" not in status.render(status.summary(ctx))


def test_a_finished_run_leaves_the_worktree_current_without_refusals(world):
    ctx, origin, drive, package = world
    assert run_flow.run(ctx) == 0, ctx.cfg.log_path.read_text()[-2000:]
    main = subprocess.run(["git", f"--git-dir={origin}", "rev-parse", "main"],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert git(ctx.notes_path, "rev-parse", "HEAD") == main
    assert "refused" not in ctx.cfg.log_path.read_text()


def test_an_owner_closure_alone_starts_a_fix_run_that_commits_it(world, tmp_path, monkeypatch):
    """Benedek R2/R4 (owner, 2026-10-06): closed "javítva a toolban"; no other work."""
    from school_notes2.flows import reopen
    from school_notes2.review import files
    from tests.flows.test_fix49 import REPORT, REVIEW
    ctx, origin, drive, package = world
    monkeypatch.setattr(fetch_flow, "drive_client", lambda ctx: None)
    clone = tmp_path / "laptop"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True, env=ENV)
    (clone / REVIEW).write_text(REPORT, encoding="utf-8")
    subprocess.run(["git", "-C", str(clone), "add", REVIEW], check=True, env=ENV)
    subprocess.run(["git", "-C", str(clone), "commit", "-qm", "review\n\nSchool-Notes-Run: chat"], check=True, env=ENV)
    subprocess.run(["git", "-C", str(clone), "push", "-q", "origin", "main"], check=True, env=ENV)
    subprocess.run(["git", f"--git-dir={ctx.cfg.bare(ctx.name)}", "fetch", "-q", "origin",
                    "refs/heads/main:refs/remotes/origin/main"], check=True, env=ENV)
    assert "1 tétel, javítva" in reopen.close(ctx, [f"{REVIEW}#R38"], "javítva a toolban")
    assert run_flow.run(ctx) == 0, ctx.cfg.log_path.read_text()[-3000:]
    task = phase.all_tasks(ctx.task_root(), "benedek")[-1]
    assert task.get("mode") == "fix" and task.phase == "done", task.phase
    text = show(origin, f"main:{REVIEW}")
    page = files.parse_report(text)
    assert page.meta["items"]["R38"] == "fixed" and "## Tulajdonosi lezárás (close-" in text
    assert reopen.pending(ctx) == [] and git(ctx.notes_path, "rev-parse", "HEAD") == subprocess.run(
        ["git", f"--git-dir={origin}", "rev-parse", "main"], capture_output=True, text=True).stdout.strip()
    assert run_flow.run(ctx) == 0                            # nothing left: no further run
    assert len(phase.all_tasks(ctx.task_root(), "benedek")) == 1
