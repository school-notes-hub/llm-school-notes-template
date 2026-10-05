"""The Git order of `finish`, G0–G9 (plan 6.6). Every step is idempotent and resumable
from the phase recorded in phase.json (8.2)."""

import shutil
from dataclasses import dataclass, field
from typing import Callable

from ..state.errors import NeedsOwner, Race, Transient
from ..state import safefs
from ..state.phase import Task
from . import conflicts, repos
from .run import Git, GitFailed, classify, failure_text, with_retries
from .workbranch import branch_name

MAX_PUSH_ROUNDS = 3
COMMIT_PATHS = ("wiki", "sources", "docs/review", "docs/evidence", "publication",
                "tools/subjects.json", "docs/repair-queue.json", "docs/figure-pending.json", "docs/figure-pending-migrations.json",
                "docs/figure-requests.json", "docs/licenses.json")


class EditedDuringFinish(Exception):
    """The interactive session kept editing while finish ran (5.4/9): call finish again."""


@dataclass
class Hooks:
    """The non-Git work finish needs, supplied by the orchestrator."""

    regenerate: Callable[[], None]          # generation + check on the current tree (G0, G4)
    build: Callable[[str], dict]            # G5: public build of a commit → build record
    publish: Callable[[dict], None]         # G8: release the build record (errors are logged)
    message: Callable[[], str]              # the commit message (6.4)
    snapshot: Callable[[], dict]            # hashes of the LLM-writable files (5.4/9)
    empty_blocks: Callable[[str], str]      # empty generated blocks (6.7)
    rerecord: Callable[[list[str]], None] = lambda paths: None   # Git merged tool files
    final_keys: Callable[[], None] = lambda: None
    held: Callable[[dict], None] = lambda record: None   # G5 held: the hold names the final commit
    extra_paths: tuple[str, ...] = field(default_factory=tuple)   # interactive: references


@dataclass
class Timeouts:
    fetch_s: float = 600
    push_s: float = 900
    ls_remote_s: float = 60
    retry_delays: tuple[float, ...] = (15, 60, 180)


RESUMABLE = ("prepared", "writing", "finishing", "committed", "built", "pushing", "pushed",
             "done")
LOCAL_TIMEOUT_S = 600        # rebase, switch, commit on a big repository


def run(task: Task, wt: Git, hooks: Hooks, t: Timeouts, start_snapshot: dict) -> str:
    """Run G0–G9 from the recorded phase; returns the final phase ('done')."""
    if task.phase not in RESUMABLE:
        raise RuntimeError(f"finish cannot continue from phase {task.phase!r}")
    if task.phase not in ("pushed", "done"):
        # Always first: an interrupted rebase must never make the run look pushed (8.2).
        g0_cleanup(task, wt, hooks)
    if task.phase in ("finishing", "writing", "prepared"):
        if not g1_commit(task, wt, hooks, start_snapshot):
            return _finish_without_commit(task, wt)
    if task.get("no_push") and task.phase == "committed":
        return "committed"  # Owner inspects the branch; only explicit finish releases it.
    if task.get("regen_pending"):
        _regenerate_and_amend(task, wt, hooks)
    phase = task.phase
    if phase == "pushing":
        phase = _after_lost_reply(task, wt, t)
    for _ in range(MAX_PUSH_ROUNDS):
        if phase in ("committed", "built"):
            phase = _publish_round(task, wt, hooks, t)
        if phase in ("pushed", "done"):
            break
    else:
        raise Transient(f"push lost the race {MAX_PUSH_ROUNDS} times")
    if task.phase == "pushed":
        g8_release(task, hooks, wt)
        g9_cleanup(task, wt)
    return task.phase


def own_commit(task: Task, wt: Git) -> str:
    """The run's commit as recorded; HEAD must agree. After a crash between a finished
    rebase and recording its result, HEAD carries this run's Run-Id and is adopted."""
    commit = task.get("commit")
    current = head(wt)
    if commit and commit != current:
        if task.get("rebasing") and _head_is_ours(wt, task.run_id, task.get("base")):
            task.update(commit=current, rebasing=False, regen_pending=True)
            return current
        raise RuntimeError(f"HEAD {current[:7]} is not the run's commit {commit[:7]}")
    return current


def head(wt: Git) -> str:
    return repos.rev(wt, "HEAD")


def g0_cleanup(task: Task, wt: Git, hooks: Hooks) -> None:
    gitdir = wt.git_dir
    lock = gitdir / "index.lock"
    if lock.exists():
        lock.unlink()   # the learner lock guarantees no other Git process runs here
    if not (gitdir / "rebase-merge").exists():
        if task.get("rebase") == "conflict":
            # Crashed right after `rebase --continue`: the rebase is done; record it.
            task.update(rebase=None, conflict_files=[], regen_pending=True,
                        base=repos.rev(wt, "refs/remotes/origin/main"))
        return
    if task.get("rebase") != "conflict":
        wt.run("rebase", "--abort")
        return
    _continue_conflicted_rebase(task, wt, hooks)


def _continue_conflicted_rebase(task: Task, wt: Git, hooks: Hooks) -> None:
    """The owner resolved the content conflict interactively (6.7): finish the rebase."""
    for path in task.get("conflict_files", []):
        if safefs.is_file(wt.work_tree, path) and conflicts.has_markers(
                safefs.read_text(wt.work_tree, path, errors="replace")):
            raise NeedsOwner(f"{path} still has conflict markers",
                             todo="resolve the markers in `school-notes chat`, then finish")
    _add(wt, hooks)
    task.update(rebasing=True)
    wt.run("rebase", "--continue", timeout=LOCAL_TIMEOUT_S)
    upstream = repos.rev(wt, "refs/remotes/origin/main")
    if head(wt) == upstream:            # the owner kept the upstream version: nothing left
        task.update(rebase=None, conflict_files=[], base=upstream, commit=upstream,
                    rebasing=False)
        task.set_phase("pushed")
        return
    task.update(rebase=None, conflict_files=[], base=upstream, commit=head(wt),
                regen_pending=True, rebasing=False)
    _regenerate_and_amend(task, wt, hooks)


def _add(wt: Git, hooks: Hooks) -> None:
    """`add -A` of the committed paths; a path that exists nowhere would make Git fail."""
    paths = [p for p in (*COMMIT_PATHS, *hooks.extra_paths)
             if (wt.work_tree / p).exists() or wt.out("ls-files", "-z", "--", p)]
    if paths:
        wt.run("add", "-A", "--", *paths)


def g1_commit(task: Task, wt: Git, hooks: Hooks, start_snapshot: dict) -> bool:
    """Commit the run (or amend our own unpushed commit). False: nothing to commit."""
    if hooks.snapshot() != start_snapshot:
        raise EditedDuringFinish("files changed while finish was running")
    _add(wt, hooks)
    _no_other_changes(wt)
    base = task.get("base")
    ours = _head_is_ours(wt, task.run_id, base)
    staged = not wt.ok("diff", "--cached", "--quiet")
    if not staged and not ours:
        return False
    if staged:
        message = hooks.message()
        args = ["commit", "--no-verify", "--cleanup=strip", "-F", "-"]
        wt.run(*(args + ["--amend"] if ours else args), input=message.encode("utf-8"),
               timeout=LOCAL_TIMEOUT_S)
    task.set_phase("committed", commit=head(wt))
    return True


def _head_is_ours(wt: Git, run_id: str, base: str) -> bool:
    if head(wt) == base:
        return False
    message = wt.out("log", "-1", "--format=%B", "HEAD")
    return f"Run-Id: {run_id}" in message.splitlines()


def _no_other_changes(wt: Git) -> None:
    """After `add` of the allowed paths nothing else may differ (the path guard ran before)."""
    out = wt.out("status", "--porcelain=v1", "-z", "--untracked-files=all")
    stray = [e[3:] for e in out.split("\0") if e and e[:2] != "  " and e[1] != " "]
    if stray:
        raise NeedsOwner("changes outside the committed paths", details={"files": stray[:20]},
                         todo="inspect the worktree in `school-notes chat`")


def _publish_round(task: Task, wt: Git, hooks: Hooks, t: Timeouts) -> str:
    """G2–G7: fetch, rebase if needed, build, push, verify."""
    with_retries(lambda: repos.fetch(wt, t.fetch_s), delays=t.retry_delays, log=wt.log)
    if repos.is_ancestor(wt, own_commit(task, wt), "refs/remotes/origin/main"):
        task.set_phase("pushed")                               # G3: already pushed
        return "pushed"
    if g4_rebase(task, wt, hooks) == "empty":
        task.set_phase("pushed")       # the change is already upstream; nothing to push
        return "pushed"
    hooks.final_keys()
    _add(wt, hooks)
    if not wt.ok("diff", "--cached", "--quiet"):
        wt.run("commit", "--no-verify", "--amend", "--no-edit", timeout=LOCAL_TIMEOUT_S)
        task.update(commit=head(wt))
    g5_build(task, wt, hooks)
    try:
        g6_push(task, wt, t)
    except Race:
        task.set_phase("committed", pushed_commit=None)
        return "committed"
    return _verify(task, wt, t)


def g4_rebase(task: Task, wt: Git, hooks: Hooks) -> str:
    upstream = repos.rev(wt, "refs/remotes/origin/main")
    if upstream == task.get("base"):
        return "same"
    task.update(rebasing=True)
    try:
        wt.run("rebase", "--no-verify", "refs/remotes/origin/main", timeout=LOCAL_TIMEOUT_S)
    except GitFailed:
        outcome = conflicts.resolve(wt, task.run_id, hooks.empty_blocks)
        if outcome.content:
            # What Git merged cleanly (tool files, emptied generated blocks) is not the
            # writer's edit: record it so the guard judges only the owner's resolution.
            hooks.rerecord(outcome.resolved)
            task.update(rebase="conflict", conflict_files=outcome.content, rebasing=False)
            raise NeedsOwner("content conflict while rebasing on origin/main",
                             todo="resolve in `school-notes chat`",
                             details={"files": outcome.content}) from None
        wt.run("rebase", "--continue", timeout=LOCAL_TIMEOUT_S)
    if head(wt) == upstream:
        task.update(base=upstream, commit=upstream, rebasing=False)
        return "empty"                 # Git dropped our commit: its change was upstream
    task.update(base=upstream, commit=head(wt), regen_pending=True, rebasing=False)
    _regenerate_and_amend(task, wt, hooks)
    return "rebased"


def _regenerate_and_amend(task: Task, wt: Git, hooks: Hooks) -> None:
    """A text-clean merge can still be semantically stale (hashes, dates): regenerate.
    `regen_pending` survives a crash between the rebase and this step."""
    hooks.regenerate()
    _add(wt, hooks)
    if not wt.ok("diff", "--cached", "--quiet"):
        wt.run("commit", "--no-verify", "--amend", "--no-edit", timeout=LOCAL_TIMEOUT_S)
    task.update(regen_pending=False, commit=head(wt))


def g5_build(task: Task, wt: Git, hooks: Hooks) -> None:
    commit = own_commit(task, wt)
    if task.get("build", {}).get("commit") == commit:
        return
    record = hooks.build(commit)
    if record.get("held"):
        # The build failed on content: its problems were recorded as items in the run's
        # report. The commit (with the report) is pushed; the publication waits (G8).
        _add(wt, hooks)
        if not wt.ok("diff", "--cached", "--quiet"):
            wt.run("commit", "--no-verify", "--amend", "--no-edit", timeout=LOCAL_TIMEOUT_S)
        task.update(commit=head(wt))
        record = {**record, "commit": head(wt)}
        hooks.held(record)
    task.set_phase("built", build=record)


def g6_push(task: Task, wt: Git, t: Timeouts) -> None:
    """Push with in-step retries; before every retry ls-remote checks whether the
    previous attempt arrived after all (6.8)."""
    attempts = []

    def attempt() -> None:
        if attempts and _after_lost_reply(task, wt, t) == "pushed":
            return
        attempts.append(1)
        task.set_phase("pushing", pushed_commit=head(wt))
        proc = wt.run("push", "--porcelain", "origin", "HEAD:refs/heads/main",
                      timeout=t.push_s, check=False)
        if proc.returncode != 0:
            raise classify("push", failure_text(proc), proc.returncode)

    with_retries(attempt, delays=t.retry_delays, log=wt.log)


def _after_lost_reply(task: Task, wt: Git, t: Timeouts) -> str:
    """`pushing` on restart or after a lost reply: ls-remote decides (6.6)."""
    remote = repos.ls_remote(wt, "refs/heads/main", t.ls_remote_s)
    mine = task.get("pushed_commit") or own_commit(task, wt)
    if remote == mine:
        task.set_phase("pushed")
        return "pushed"
    with_retries(lambda: repos.fetch(wt, t.fetch_s), delays=t.retry_delays, log=wt.log)
    if repos.is_ancestor(wt, mine, "refs/remotes/origin/main"):
        task.set_phase("pushed")
        return "pushed"
    task.set_phase("committed", pushed_commit=None)
    return "committed"


def _verify(task: Task, wt: Git, t: Timeouts) -> str:
    """G7: the remote main is our HEAD, or (after a fetch) contains it."""
    return _after_lost_reply(task, wt, t)


def g8_release(task: Task, hooks: Hooks, wt: Git) -> None:
    record = task.get("build")
    if not record or record.get("commit") != head(wt):
        return     # the pushed commit was built by someone else's round; publish catches up
    if record.get("held"):
        wt.log.event("site.publish", "held", target=record["commit"])
        return
    try:
        hooks.publish(record)
    except Exception as exc:  # noqa: BLE001 - a release error never fails the run (5.10)
        wt.log.error("site.publish", exc)
        task.update(publish_error=str(exc)[:300])


def g9_cleanup(task: Task, wt: Git) -> None:
    branch = branch_name(task.run_id)
    wt.run("switch", "--detach", "HEAD")
    if repos.has_ref(wt, f"refs/heads/{branch}") and repos.is_ancestor(
            wt, branch, "refs/remotes/origin/main"):
        wt.run("branch", "-D", branch)
    for name in ("downloads", "build"):
        shutil.rmtree(task.dir / name, ignore_errors=True)
    task.set_phase("done")


def _finish_without_commit(task: Task, wt: Git) -> str:
    """5.4/7: nothing changed – no commit, the run is done."""
    task.update(no_change=True)
    g9_cleanup(task, wt)
    return "done"
