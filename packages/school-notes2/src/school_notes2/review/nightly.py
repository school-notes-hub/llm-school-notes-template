"""Nightly review from the diff (owner, 2026-10-05): the tool hands the independent reviewer
only the commit range since the last nightly review – `git diff <from>..<to> -- wiki/`, the
commit list, the writer's review requests and the open closures. The reviewer decides from
the diff what is a content change and what it wants to check; administrative and tool
changes may be skipped. An empty wiki diff needs no call.

Two Git objects are passed in: `repo` is the bare clone (fetch, rev-list, diff, push) and
`wt` is the review worktree (its own linked gitdir plus --work-tree, for switch/commit).
"""

import json
import re
from pathlib import Path

from ..git import repos
from ..git.run import Git, with_retries
from ..state import phase, safefs
from ..state.errors import NeedsOwner, Transient
from ..wiki import markers
from . import relations

MARKER_REF = "refs/remotes/origin/claude-reviewed"
MAIN_REF = "refs/remotes/origin/main"
ACTIVE = ("reviewed", "closing", "pushing")
REQUEST = "School-Notes-Review-Request: "
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def fetch(repo: Git, timeout: float) -> None:
    """Fetch main and the marker explicitly; a missing marker is the owner's step (6.9/4)."""
    def step():
        try:
            repos.fetch(repo, timeout, repos.MAIN_SPEC, repos.REVIEWED_SPEC)
        except (Transient, NeedsOwner) as exc:
            if "couldn't find remote ref" in str(exc):
                raise NeedsOwner("claude-reviewed marker not created yet on origin",
                                 todo="create it once at the cut-over (plan 6.9/4)") from None
            raise
    with_retries(step, log=repo.log)


def rev(repo: Git, ref: str) -> str:
    """The commit SHA of `ref`, or "" when the ref does not exist."""
    proc = repo.run("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
    return proc.stdout.decode().strip() if proc.returncode == 0 else ""


def wiki_diff(repo: Git, base: str, head: str) -> str:
    return repo.out("diff", "--no-ext-diff", "--no-textconv", "--no-renames", base, head, "--", "wiki")


def added_lines(patch: str) -> dict[str, set[int]]:
    """New-side line numbers of the `+` lines per file, read from Git's own hunk headers."""
    found, path, line = {}, None, 0
    for text in patch.splitlines():
        if text.startswith("+++ "):
            path = text[6:] if text.startswith("+++ b/") else None
            continue
        hunk = HUNK.match(text)
        if hunk:
            line = int(hunk[1])
            continue
        if path is None or text.startswith(("--- ", "diff ", "index ", "\\")):
            continue
        if text.startswith("+"):
            found.setdefault(path, set()).add(line)
            line += 1
        elif not text.startswith("-"):
            line += 1
    return found


def commits(repo: Git, base: str, head: str) -> list[dict]:
    out = []
    for sha in repo.out("rev-list", "--reverse", "--topo-order", f"{base}..{head}").split():
        message = repo.out("show", "-s", "--format=%B", sha)
        lines = message.splitlines()
        run = next((l.removeprefix("School-Notes-Run: ") for l in lines if l.startswith("School-Notes-Run: ")), None)
        requests = []
        for l in lines:
            if l.startswith(REQUEST):
                try:
                    requests += json.loads(l.removeprefix(REQUEST))
                except ValueError:
                    continue
        out.append({"commit": sha, "subject": lines[0] if lines else "", "run": run, "review_requests": requests})
    return out


def open_closures(work: Path) -> list[dict]:
    """Writer closures no independent check has judged yet, read from the item records."""
    found = []
    for key, item in relations.inventory(work)["items"].items():
        if (item["status"] == "fixed" and not item.get("recheck") and not item.get("nightly")) or (
                item["status"] == "disagree" and not item.get("response")):
            found.append({**item, "key": key})
    return found


def prepare(root: Path, student: str, repo: Git, wt: Git, *, fetch_timeout: float, max_agents: int = 3,
            log=None):
    fetch(repo, fetch_timeout)
    base, head = rev(repo, MARKER_REF), rev(repo, MAIN_REF)
    if not base:
        raise NeedsOwner("claude-reviewed marker missing", todo="create it once (plan 6.9/4)")
    if not repo.ok("merge-base", "--is-ancestor", base, head):
        raise NeedsOwner("origin/claude-reviewed is not an ancestor of origin/main",
                         todo="check the claude-reviewed branch on GitHub")
    if base == head or not wiki_diff(repo, base, head).strip():
        if log is not None:
            log.event("review.no_diff", base=base, head=head)
        return None  # Nothing in wiki/ changed: no call (owner, 2026-10-05).
    task = phase.create(root, student, "review", "cron", "prepared")
    task.update(base=base, H=head, T=head, diff_review=True, max_agents=max_agents)
    write_input(task, repo, wt)
    return task


def write_input(task: phase.Task, repo: Git, wt: Git) -> None:
    """The pinned tree at H and the reviewer's input folder; repeatable after a crash."""
    wt.run("switch", "--detach", "--discard-changes", task.get("H"))
    folder = task.dir / "in"
    folder.mkdir(parents=True, exist_ok=True)
    patch = wiki_diff(repo, task.get("base"), task.get("H"))
    listed = commits(repo, task.get("base"), task.get("H"))
    sources = repo.out("diff", "--name-only", "--no-renames", task.get("base"), task.get("H"), "--", "sources").split()
    safefs.write_text(folder, "diff.patch", patch)
    safefs.write_json(folder, "commits.json", listed)
    safefs.write_json(folder, "review-requests.json",
                      [{**r, "commit": c["commit"]} for c in listed for r in c["review_requests"]])
    safefs.write_json(folder, "items.json", open_closures(wt.work_tree))
    safefs.write_json(folder, "sources.json", sorted(sources))
    task.update(input_ready=True, items=[{"key": i["key"], "status": i["status"]} for i in open_closures(wt.work_tree)])


def triage(review: dict, patch: str, work: Path) -> tuple[list[dict], list[str]]:
    """Only a learning-blocking finding on an added author line of the diff is an item;
    every other finding is an owner note (the reviewer's own words, nothing dropped)."""
    added = added_lines(patch)
    items, notes = [], list(review["owner_notes"])
    for f in sorted(review["findings"], key=lambda f: f["id"]):
        lines = safefs.read_text(work, f["file"]) if safefs.is_file(work, f["file"]) else ""
        tool = any(start <= _offset(lines, f["line"]) < end for start, end, _ in markers.spans(lines))
        if f["severity"] == "hiba" and f["line"] in added.get(f["file"], set()) and not tool:
            items.append(f)
        else:
            notes.append(f"{f['file']}:{f['line']}: {f['problem']}" + (f" → {f['suggestion']}" if f.get("suggestion") else ""))
    return items, list(dict.fromkeys(" ".join(n.split()) for n in notes))


def _offset(text: str, line: int) -> int:
    rows = text.splitlines(keepends=True)
    return sum(len(r) for r in rows[:max(0, line - 1)])


def pending_close(tasks: list[phase.Task]) -> phase.Task | None:
    """An earlier review whose output is valid but whose closing did not finish."""
    for task in tasks:
        if task.kind == "review" and task.open and task.phase in ACTIVE and task.get("diff_review"):
            return task
    return None
