"""Nightly review closing (plan 5.6/5, 6.9/3): report commit R and an atomic two-ref push.

R is committed on a detached HEAD in the review worktree on top of the fresh origin/main;
`push --atomic` moves `main` to R and `claude-reviewed` to M, or neither.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..evidence import records
from ..git.run import Git, classify, failure_text
from ..state import phase, safefs
from ..state.errors import Race, Transient
from ..wiki import public
from . import files, index, relations
from .nightly import MAIN_REF, fetch, load_review, rev

ROUNDS = 3


@dataclass(frozen=True)
class Timeouts:
    fetch_s: float = 600
    push_s: float = 900
    ls_remote_s: float = 60


@dataclass(frozen=True)
class Identity:
    student: str
    reviewer: str        # model/effort, written into the report and the records
    tool_version: str
    date: str            # Europe/Budapest day of the report file
    at: str              # ISO time for the evidence records


def _message(ident: Identity, run_id: str, title: str) -> bytes:
    return (f"review({ident.student}): {title}\n\nRun-Id: {run_id}\nKind: review\n"
            f"Tool: school-notes {ident.tool_version}\n").encode()


def _commit(wt: Git, paths: list[str], message: bytes) -> str:
    wt.run("add", "-A", "--", *sorted(set(paths)))
    wt.run("commit", "--no-verify", "--cleanup=strip", "-F", "-", input=message)
    return wt.out("rev-parse", "HEAD").strip()


def _push(repo: Git, r: str, m: str, timeout: float) -> None:
    proc = repo.run("push", "--atomic", "--porcelain", "origin", f"{r}:refs/heads/main",
                    f"{m}:refs/heads/claude-reviewed", timeout=timeout, check=False)
    if proc.returncode == 0:
        return
    text = failure_text(proc)  # --porcelain puts the rejection reason on stdout
    if "(fetch first)" in text or "(non-fast-forward)" in text:
        raise Race("review push rejected: origin moved")
    if "hook declined" in text:
        text += "\npre-receive hook declined"
    raise classify("push", text, proc.returncode)


def remote_matches(repo: Git, r: str, m: str, timeout: float) -> bool:
    """Did our atomic push arrive? The marker is exactly M, and main is R or (someone pushed
    on top of it meanwhile) a descendant of R – then the report is in, never push it twice."""
    out = repo.out("ls-remote", "origin", "refs/heads/main", "refs/heads/claude-reviewed",
                   timeout=timeout)
    refs = {name: sha for sha, name in (line.split("\t") for line in out.splitlines() if line)}
    main = refs.get("refs/heads/main")
    if refs.get("refs/heads/claude-reviewed") != m or main is None:
        return False
    if main == r:
        return True
    fetch(repo, timeout * 10)
    return repo.ok("merge-base", "--is-ancestor", r, MAIN_REF)


def _round(task: phase.Task, repo: Git, wt: Git, write: Callable[[Path], list[str]],
           choose_m: Callable[[str, str], str], message: bytes, t: Timeouts) -> tuple[str, str]:
    fetch(repo, t.fetch_s)
    wt.run("switch", "--detach", "--discard-changes", MAIN_REF)
    wt.run("clean", "-fdq")
    head_now = rev(repo, MAIN_REF)
    r = _commit(wt, write(wt.work_tree), message)
    m = choose_m(r, head_now)
    task.set_phase("pushing", R=r, M=m)
    try:
        _push(repo, r, m, t.push_s)
    except Transient:
        # The reply may be lost after GitHub already moved both refs (6.6, 6.9/3).
        if not remote_matches(repo, r, m, t.ls_remote_s):
            raise
    return r, m


def _close(task: phase.Task, repo: Git, wt: Git, write, choose_m, message: bytes,
           t: Timeouts) -> tuple[str, str]:
    if task.phase == "pushing" and remote_matches(repo, task.get("R"), task.get("M"),
                                                  t.ls_remote_s):
        return _finish(task, repo, task.get("R"), task.get("M"))
    task.set_phase("closing")
    for _ in range(ROUNDS):
        try:
            return _finish(task, repo, *_round(task, repo, wt, write, choose_m, message, t))
        except Race:
            task.set_phase("closing")
    raise Transient(f"review push rejected {ROUNDS} times in a row")


def _finish(task: phase.Task, repo: Git, r: str, m: str) -> tuple[str, str]:
    repo.run("gc", "--auto", gc=True)  # the only place gc may run (6.9/5)
    task.set_phase("done", R=r, M=m)
    return r, m


def close(task: phase.Task, repo: Git, wt: Git, ident: Identity, t: Timeouts = Timeouts(),
          fetch_pages: list[dict] | None = None) -> tuple[str, str]:
    """Write the report, index and evidence; commit R; push main=R, claude-reviewed=M."""
    review = load_review(task)
    base, head, end = task.get("base"), task.get("H"), task.get("T")
    if task.get("topic_review") and not task.get("topic_results"):
        from . import topic_result, topics
        if public.dumps(topic_result.state(task)) == topics.text(repo, head, topics.STATE):
            return _finish(task, repo, head, base)

    def write(worktree: Path) -> list[str]:
        responses, dropped = relations.valid_responses(review.get("responses", []), relations.inventory(worktree))
        task.update(dropped_responses_at_close=dropped)
        if dropped:
            repo.log.event("review.dropped_responses", items=dropped)
        replied = [relations.reply(worktree, r["key"], r["verdict"], r["answer"])
                   for r in responses]
        report = files.write_review(worktree, ident.date, review, ident.reviewer, base, end)
        rel = report.relative_to(worktree).as_posix()
        owners = [{"file": rel, "item_id": key, "reason": "review finding requires an owner decision"}
                  for key, status in (files.read_items(worktree, report) or {}).items() if status == files.OWNER]
        extra = []
        if task.get("topic_review"):
            from . import topic_result
            extra, closure_owners, notes = topic_result.apply(task, worktree, ident)
            owners += closure_owners
            notes = [" ".join(n.split()) for n in notes if n not in review.get("owner_notes", [])]
            if notes:
                safefs.write_text(worktree, rel, safefs.read_text(worktree, rel)
                                  + "\n## Tulajdonosi észrevételek\n\n" + "".join(f"* {n}\n" for n in notes))
                safefs.write_json(task.dir, "review.json", {**review, "owner_notes":
                    list(dict.fromkeys(review.get("owner_notes", []) + notes))})
        task.update(notify_owner_items=owners)
        written = replied + extra + [report.relative_to(worktree).as_posix(),
                   index.update(worktree).relative_to(worktree).as_posix()]
        written += records.append(worktree, records.from_reviewer(review.get("figures", [])),
                                  kind="review",
                                  run_id=task.run_id, checker=ident.reviewer, at=ident.at,
                                  fetch_pages=fetch_pages)
        return written

    def choose_m(r: str, head_now: str) -> str:
        if task.get("topic_review"):
            return (r if head_now == head else head) if task.get("all_topics_done") else base
        # Legacy tasks keep their original marker contract.
        return r if end == head and head_now == head else end

    n = len(review["findings"])
    title = f"{n} megállapítás ({base[:7]}..{end[:7]})"
    return _close(task, repo, wt, write, choose_m, _message(ident, task.run_id, title), t)


def discard_timeout(task: phase.Task, repo: Git, wt: Git, ident: Identity, commit: str,
                    t: Timeouts = Timeouts()) -> tuple[str, str]:
    """Owner's `--discard review`: close `commit` as not reviewed and step the marker past it."""
    fetch(repo, t.fetch_s)
    parent = repo.out("rev-parse", f"{commit}^").strip()

    def write(worktree: Path) -> list[str]:
        report = files.write_timeout_report(worktree, ident.date, commit, parent, ident.reviewer,
                                            task.run_id)
        return [report.relative_to(worktree).as_posix(),
                index.update(worktree).relative_to(worktree).as_posix()]

    title = f"nem átnézve: időtúllépés ({commit[:7]})"
    return _close(task, repo, wt, write, lambda r, head_now: commit,
                  _message(ident, task.run_id, title), t)
