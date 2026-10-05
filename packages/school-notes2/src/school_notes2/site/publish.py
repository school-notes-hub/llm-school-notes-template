"""Publishing a checked build to gh-pages (plan 6.10) and deciding whether one is due (5.10).

Only changed files go out: the site worktree starts from the current origin/gh-pages, rsync
makes it equal to the build, and Git commits the difference. The commit is made with
`commit-tree` on a detached HEAD, so no local branch exists that a retry could collide with;
the first publish is a parentless (orphan) commit pushed as a new ref, never a force push.
"""

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen

from ..git import repos
from ..git.run import Git, with_retries
from ..log import Log
from ..state.errors import Race, Transient

BRANCH = "gh-pages"
REMOTE_REF = "refs/remotes/origin/gh-pages"
RECORD = "publish.json"
PUBLISHED_INPUTS = ("wiki", "publication/public.json", "publication/assets")
MAX_ROUNDS = 3


@dataclass(frozen=True)
class Published:
    commit: str | None      # the gh-pages commit; None when there was nothing new
    changed: bool


def record_bytes(source_commit: str, tool_version: str) -> bytes:
    """publish.json: deliberately without run id, so an unchanged source gives no commit."""
    value = {"source_commit": source_commit, "tool": f"school-notes2 {tool_version}"}
    return (json.dumps(value, indent=2) + "\n").encode()


def publish(site: Git, build_site: Path, *, student: str, source_commit: str, run_id: str,
            tool_version: str, log: Log, fetch_s: int = 600, push_s: int = 900,
            ls_remote_s: int = 60, rsync: str = "rsync") -> Published:
    """Copy `build_site` (the checked `<task>/build/site`) to gh-pages and push it.

    `site` is the site worktree's Git (`repos.worktree_git(bare, path)`).
    A rejected push (someone else published) rebuilds the commit, up to three rounds.
    """
    for round_no in range(1, MAX_ROUNDS + 1):
        parent = fetch_gh_pages(site, log, fetch_s=fetch_s, ls_remote_s=ls_remote_s)
        commit = _stage(site, build_site, parent, source_commit, tool_version, rsync)
        if commit is None:
            log.event("site.publish", "ok", target="no change", source=source_commit[:12])
            return Published(None, False)
        commit = _commit(site, commit, parent, student, source_commit, run_id)
        try:
            _push(site, commit, log, push_s, ls_remote_s)
        except Race:
            log.event("site.publish", f"retry {round_no}/{MAX_ROUNDS}", target="push rejected")
            continue
        site.run("update-ref", "--no-deref", "HEAD", commit)
        log.event("site.publish", "ok", target=commit[:12], source=source_commit[:12])
        return Published(commit, True)
    raise Transient("gh-pages push kept being rejected (someone else keeps publishing)")


def fetch_gh_pages(site: Git, log: Log, *, fetch_s: int = 600, ls_remote_s: int = 60) -> str | None:
    """Fetch origin/gh-pages; None when the branch does not exist yet (first publish).

    An exact refspec fails on a missing remote ref, so existence is asked first.
    """
    def step():
        if repos.ls_remote(site, f"refs/heads/{BRANCH}", ls_remote_s) is None:
            return None
        repos.fetch(site, fetch_s, repos.GH_PAGES_SPEC)
        return repos.rev(site, REMOTE_REF)

    return with_retries(step, log=log)


def _stage(site: Git, build_site: Path, parent: str | None, source_commit: str,
           tool_version: str, rsync: str) -> str | None:
    """Make the worktree equal to the build; return the new tree, or None if unchanged."""
    work = site.work_tree
    if parent:
        site.run("switch", "--detach", "--discard-changes", parent)
    else:
        site.run("read-tree", "--empty")
    _rsync(rsync, build_site, work)
    (work / ".nojekyll").write_bytes(b"")
    (work / RECORD).write_bytes(record_bytes(source_commit, tool_version))
    site.run("add", "-A", "--", ".")
    tree = site.out("write-tree").strip()
    if parent and tree == site.out("rev-parse", parent + "^{tree}").strip():
        return None
    return tree


def _rsync(rsync: str, src: Path, dest: Path) -> None:
    argv = [rsync, "-a", "--checksum", "--delete", "--exclude=.git", f"{src}/", f"{dest}/"]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        raise Transient(f"rsync to the site worktree failed (rc={proc.returncode})")


def _commit(site: Git, tree: str, parent: str | None, student: str, source_commit: str,
            run_id: str) -> str:
    message = (f"publish({student})\n\nSource-Commit: {source_commit}\nRun-Id: {run_id}\n")
    args = ["commit-tree", tree] + (["-p", parent] if parent else [])
    return site.out(*args, input=message.encode()).strip()


def _push(site: Git, commit: str, log: Log, push_s: int, ls_remote_s: int) -> None:
    """Push; a lost answer is settled by ls-remote before any retry (6.6)."""

    def attempt():
        if repos.ls_remote(site, f"refs/heads/{BRANCH}", ls_remote_s) == commit:
            return
        try:
            site.run("push", "--porcelain", "origin", f"{commit}:refs/heads/{BRANCH}",
                     timeout=push_s)
        except Transient:
            if repos.ls_remote(site, f"refs/heads/{BRANCH}", ls_remote_s) == commit:
                return
            raise

    with_retries(attempt, log=log)
    if repos.ls_remote(site, f"refs/heads/{BRANCH}", ls_remote_s) != commit:
        raise Transient("gh-pages push not visible on the remote")


def published_record(site: Git) -> dict | None:
    """The publish.json on the last fetched origin/gh-pages (see fetch_gh_pages), or None."""
    proc = site.run("show", f"{REMOTE_REF}:{RECORD}", check=False)
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return None


def publish_needed(private: Git, site: Git, main: str, tool_version: str) -> tuple[bool, str]:
    """Does origin/main differ from the last publish in what goes out (5.10, 5.1/6)?

    A review commit (docs/ only) changes nothing that is published, so it needs no build.
    Call after fetching origin/main and `fetch_gh_pages`.
    """
    record = published_record(site)
    if record is None:
        return True, "never published"
    if record.get("tool") != f"school-notes2 {tool_version}":
        return True, "tool version changed"
    last = record.get("source_commit", "")
    if last == main:
        return False, "up to date"
    if not private.ok("cat-file", "-e", f"{last}^{{commit}}"):
        return True, "last published commit unknown"
    changed = private.out("diff", "--name-only", "--no-ext-diff", "--no-textconv", last, main,
                          "--", *PUBLISHED_INPUTS).split()
    return (True, f"{len(changed)} published file(s) changed") if changed else (False, "no published change")


def changed_since_publish(private: Git, site: Git, main: str) -> list[str] | None:
    """Wiki paths changed since the last publish (for the browser check); None = all."""
    record = published_record(site)
    last = (record or {}).get("source_commit")
    if not last or not private.ok("cat-file", "-e", f"{last}^{{commit}}"):
        return None
    # --no-renames: a renamed page lists its old path too (gone → every page is checked).
    return private.out("diff", "--name-only", "--no-renames", "--no-ext-diff", "--no-textconv", last, main,
                       "--", "wiki").split()


def wait_until_live(url: str, source_commit: str, log: Log, *, timeout_s: int = 600,
                    every_s: int = 20, fetch=None, sleep=time.sleep) -> bool:
    """Poll the live publish.json; a timeout is only a warning (6.10)."""
    fetch = fetch or _https_get
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            if json.loads(fetch(url)).get("source_commit") == source_commit:
                log.event("site.live", "ok", target=url)
                return True
        except (OSError, ValueError):
            pass
        if time.monotonic() >= deadline:
            log.event("site.live", "warning", level="warning", target=url,
                      message="publish.json not live yet")
            return False
        sleep(every_s)


def _https_get(url: str) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("only https")
    with urlopen(url, timeout=20) as response:
        return response.read()


def live_url(build_dir: Path) -> str | None:
    """https://<site><base>publish.json from the build's payload (None if no site origin)."""
    payload = json.loads((build_dir / "payload.json").read_text(encoding="utf-8"))
    return f"{payload['site']}{payload['base']}{RECORD}" if payload.get("site") else None
