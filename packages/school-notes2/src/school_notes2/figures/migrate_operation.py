"""Locked, resumable host operation for the pending-figure migration."""

import fcntl
import os
import sys
from contextlib import contextmanager
from dataclasses import replace

from ..git import repos
from ..git.run import with_retries
from ..log import Log
from ..state import phase, safefs
from ..wiki import public
from . import migrate_pending as migration

JOURNAL = "migration-operation-24.json"
MAIN = "refs/remotes/origin/main"
MESSAGE = "Függő ábrák és régi fejlécek migrálása\n\nSchool-Notes-Run: fix\n"


@contextmanager
def admission(ctx, dry_run):
    if not dry_run:
        lock = ctx.lock()
        if not lock.try_acquire("migrate-pending"):
            raise ValueError("the learner lock is held; retry after the current operation finishes")
        try:
            yield
        finally:
            lock.release()
        return
    # A preview never creates a lock, holder, state directory or log file.
    path = ctx.cfg.state_dir / ctx.name / "lock"
    fd = os.open(path, os.O_RDONLY) if path.exists() else None
    try:
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("the learner lock is held; retry after the current operation finishes") from None
        yield
    finally:
        if fd is not None:
            os.close(fd)


def run(ctx, *, dry_run=False, push=False):
    try:
        with admission(ctx, dry_run):
            task = phase.open_task(ctx.task_root(), ctx.name, "notes")
            if task is not None:
                raise ValueError(f"open notes run {task.run_id} ({task.phase}); finish or discard it before migration")
            result = preview(ctx) if dry_run else execute(ctx, push)
            result["receipt_directory"] = str((ctx.cfg.state_dir / ctx.name).resolve())
            print(migration.encoded(result), end="")
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def preview(ctx):
    wt = replace(ctx.worktree("notes"), log=Log(None, console=False))
    dirty = wt.out("--no-optional-locks", "status", "--porcelain=v1", "--untracked-files=all").strip()
    if dirty:
        raise ValueError("the notes worktree is not clean:\n" + dirty)
    result = migration.migrate(ctx.notes_path, state_dir=ctx.cfg.state_dir / ctx.name,
                               repo=wt, dry_run=True)
    from .migrate_ledger import preview
    result["ledger"] = preview(ctx, wt)
    return {**result, "receipt_directory": str((ctx.cfg.state_dir / ctx.name).resolve()),
            "preview_commit": repos.rev(wt, "HEAD"),
            "note": "Local snapshot only; --dry-run does not fetch or switch the worktree."}


def execute(ctx, push):
    wt, work, state = ctx.worktree("notes"), ctx.notes_path, ctx.cfg.state_dir / ctx.name
    saved = safefs.read_json(state, JOURNAL, {})
    with_retries(lambda: repos.fetch(ctx.bare(), ctx.cfg.timeouts.fetch_s), log=ctx.log)
    head = repos.rev(wt, MAIN)
    if saved.get("commit"):
        return publish(ctx, wt, saved, head, push)
    if saved and saved["base"] != head:
        raise ValueError("migration input changed: origin/main; inspect and preserve changes, then remove "
                         f"{state / migration.RECEIPT} and {state / JOURNAL}; rerun --dry-run")
    if saved:
        clean_interrupted(work, state, saved)
    wt.run("switch", "--detach", "--discard-changes", MAIN)
    if wt.out("status", "--porcelain=v1", "--untracked-files=all").strip():
        raise ValueError("the notes worktree is not clean; preserve or remove the untracked files and retry")
    saved = saved or {"base": head, "public_existed": safefs.is_file(work, "publication/public.json"),
                      "mark_existed": safefs.is_file(work, migration.MARK)}
    safefs.write_json(state, JOURNAL, saved)
    result = migration.migrate(work, state_dir=state, repo=wt)
    public.write(work, public.either(public.render_rights(work), public.media_receipt_rights(work)))
    wt.run("add", "-A", "--", ".")
    tree = wt.out("write-tree").strip()
    if tree == wt.out("rev-parse", "HEAD^{tree}").strip():
        safefs.unlink(state, JOURNAL)
        return {**result, "status": "already-migrated"}
    # The commit object precedes the durable checkpoint; replay can only leave an
    # unreferenced object, never a second migration in published history.
    commit = wt.out("commit-tree", tree, "-p", head, "-F", "-", input=MESSAGE.encode()).strip()
    saved.update(commit=commit, result=result)
    safefs.write_json(state, JOURNAL, saved)
    return publish(ctx, wt, saved, head, push)


def clean_interrupted(work, state, saved):
    receipt = safefs.read_json(state, migration.RECEIPT, {})
    migration.check_current(work, {"files": receipt.get("files", {})}, state)
    # Only files created by this transaction may be removed; unrelated untracked
    # files still fail the clean-worktree gate after switching.
    for path, hashes in receipt.get("files", {}).items():
        if hashes["before"] is None and migration.current(work, path) == hashes["after"]:
            safefs.unlink(work, path)
    if not saved["mark_existed"] and safefs.read_json(work, migration.MARK, {}).get("version") == migration.VERSION:
        safefs.unlink(work, migration.MARK)
    if not saved["public_existed"] and safefs.is_file(work, "publication/public.json"):
        safefs.unlink(work, "publication/public.json")


def publish(ctx, wt, saved, remote, push):
    commit = saved["commit"]
    if repos.is_ancestor(wt, commit, remote):
        wt.run("switch", "--detach", "--discard-changes", remote)
        return {**saved["result"], "status": "already-pushed", "commit": commit}
    if remote != saved["base"]:
        raise ValueError(f"origin/main changed after migration commit {commit}; "
                         f"{migration.recovery(ctx.cfg.state_dir / ctx.name)}")
    wt.run("switch", "--detach", "--discard-changes", commit)
    if push:
        wt.run("push", "--porcelain", "origin", f"{commit}:refs/heads/main", timeout=ctx.cfg.timeouts.push_s)
        observed = repos.ls_remote(wt, "refs/heads/main", ctx.cfg.timeouts.ls_remote_s)
        if observed != commit:
            raise ValueError(f"push verification failed for {commit}; rerun the same --push command")
        with_retries(lambda: repos.fetch(ctx.bare(), ctx.cfg.timeouts.fetch_s), log=ctx.log)
    ctx.log.event("migration.pending", "pushed" if push else "committed", commit=commit)
    return {**saved["result"], "status": "pushed" if push else "committed", "commit": commit}
