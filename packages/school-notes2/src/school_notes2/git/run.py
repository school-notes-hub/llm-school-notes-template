"""The only Git caller (plan 6.1, 6.3, 6.8): fixed argv and environment, explicit
--git-dir/--work-tree, logging, error classification and retries."""

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..log import Log, Timer
from ..state.errors import NeedsOwner, Race, Transient

FIXED_C = (
    "core.hooksPath=/dev/null", "core.autocrlf=false", "core.safecrlf=false",
    "core.fsmonitor=false", "core.quotePath=false", "core.symlinks=true", "core.editor=true",
    "core.pager=cat", "color.ui=never", "protocol.ext.allow=never", "protocol.file.allow=never",
    "submodule.recurse=false", "fetch.recurseSubmodules=false", "transfer.fsckObjects=true",
    "maintenance.auto=false", "push.default=nothing", "push.followTags=false",
    "rebase.autoStash=false", "rebase.autoSquash=false", "rebase.updateRefs=false",
    "rerere.enabled=false", "merge.conflictStyle=merge", "diff.renames=false",
    "commit.gpgSign=false", "credential.helper=", "user.useConfigOnly=true",
)

TRANSIENT = (
    "Connection timed out", "Connection reset", "Connection closed by remote host",
    "Could not resolve hostname", "kex_exchange_identification",
    "the remote end hung up unexpectedly", "early EOF", "RPC failed", "Internal Server Error",
    "No space left on device", "Connection refused", "Network is unreachable",
)
PERMANENT = (
    "couldn't find remote ref",          # a ref the step needs does not exist (yet)
    "Permission denied (publickey)", "Host key verification failed", "Repository not found",
    "protected branch", "pre-receive hook declined", "GH0", "exceeds GitHub's file size limit",
    "large files detected",
    # HTTPS: a refused or missing credential never passes by itself (owner: gh auth login)
    "Authentication failed", "returned error: 401", "returned error: 403",
    "could not read Username", "could not read Password", "Invalid username or password",
)
RACE = ("(fetch first)", "(non-fast-forward)")
RETRY_DELAYS = (15, 60, 180)


@dataclass(frozen=True)
class HttpsToken:
    """GitHub over HTTPS with the token `gh auth token` gave at run time: the token lives only
    in git's environment; the helper on argv names the variable, never the value."""

    token: str = field(repr=False)

    def env(self) -> dict:
        return {"SN_GIT_TOKEN": self.token}

    def config(self) -> tuple[str, ...]:
        """The helper answers only for https://github.com, and git may speak only HTTPS (a
        specific `protocol.<name>.allow` still wins, e.g. the tests' local file origins)."""
        return ("protocol.allow=never", "protocol.https.allow=always",
                "credential.https://github.com.helper=",
                'credential.https://github.com.helper=!f() { echo username=x-access-token; '
                'echo "password=$SN_GIT_TOKEN"; }; f')


@dataclass(frozen=True)
class Git:
    """A bare repo plus (optionally) one of its worktrees, bound to an identity and a log."""

    git_dir: Path
    name: str
    email: str
    log: Log
    remote: HttpsToken | None = None
    work_tree: Path | None = None

    def at(self, work_tree: Path) -> "Git":
        return Git(self.git_dir, self.name, self.email, self.log, self.remote, work_tree)

    def env(self) -> dict:
        env = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
               "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/false", "SSH_ASKPASS": "",
               "GIT_EDITOR": "true", "GIT_MERGE_AUTOEDIT": "no", "GIT_PAGER": "cat",
               "LC_ALL": "C", "PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/nonexistent"}
        if self.remote:
            env.update(self.remote.env())
        return env

    def argv(self, args: list[str], gc: bool = False) -> list[str]:
        argv = ["git", f"--git-dir={self.git_dir}"]
        if self.work_tree:
            argv.append(f"--work-tree={self.work_tree}")
        remote = self.remote.config() if self.remote else ()
        for item in FIXED_C + remote + (f"user.name={self.name}", f"user.email={self.email}"):
            argv += ["-c", item]
        if not gc:
            argv += ["-c", "gc.auto=0"]
        return argv + args

    def run(self, *args: str, timeout: float = 120, check: bool = True, input: bytes | None = None,
            gc: bool = False, cwd: Path | None = None) -> subprocess.CompletedProcess:
        argv = self.argv(list(args), gc)
        with Timer() as t:
            try:
                proc = subprocess.run(argv, env=self.env(), input=input, capture_output=True,
                                      timeout=timeout, cwd=cwd or self.work_tree or self.git_dir)
            except subprocess.TimeoutExpired:
                self.log.event("git." + args[0], "error", target=" ".join(args[1:3]),
                               error_class="transient", message="timeout")
                raise Transient(f"git {args[0]} timed out after {timeout:.0f}s") from None
        stderr = proc.stderr.decode("utf-8", "replace")
        self.log.event("git." + args[0], "ok" if proc.returncode == 0 else "error",
                       target=" ".join(a for a in args[1:3]), duration_s=t.s, rc=proc.returncode,
                       stderr_head="\n".join(stderr.splitlines()[:20]) if proc.returncode else "")
        if check and proc.returncode != 0:
            raise classify(args[0], failure_text(proc), proc.returncode)
        return proc

    def out(self, *args: str, **kw) -> str:
        return self.run(*args, **kw).stdout.decode("utf-8", "replace")

    def ok(self, *args: str, **kw) -> bool:
        return self.run(*args, check=False, **kw).returncode == 0


def failure_text(proc: subprocess.CompletedProcess) -> str:
    """stderr plus stdout: `push --porcelain` reports rejections on stdout."""
    out = proc.stdout.decode("utf-8", "replace") if proc.stdout else ""
    return proc.stderr.decode("utf-8", "replace") + "\n" + out[-4000:]


class GitFailed(Exception):
    """A local Git command failed in a way the caller must interpret (e.g. merge conflict)."""

    def __init__(self, command: str, rc: int, stderr: str):
        super().__init__(f"git {command} failed (rc={rc}): {stderr.strip()[:300]}")
        self.rc = rc
        self.stderr = stderr


def classify(command: str, stderr: str, rc: int) -> Exception:
    """Map a failed Git call to the 6.8 classes. Unknown network errors count as transient."""
    if any(m in stderr for m in RACE) and command == "push":
        return Race("push rejected: someone pushed first")
    if command == "fetch" and ("non-fast-forward" in stderr or "(forced update)" in stderr
                               or "rejected" in stderr):
        return NeedsOwner("the remote history was rewritten (non-fast-forward fetch)",
                          todo="check the remote repository; the tool never force-updates")
    if any(m in stderr for m in PERMANENT):
        return NeedsOwner(f"git {command}: {_first_line(stderr)}",
                          todo="fix the GitHub side (key, permission, rule), then "
                               "`school-notes status --clear <learner> <kind> --continue`")
    if any(m in stderr for m in TRANSIENT):
        return Transient(f"git {command}: {_first_line(stderr)}")
    if command in ("fetch", "push", "ls-remote", "clone"):
        return Transient(f"git {command} (unknown error): {_first_line(stderr)}")
    return GitFailed(command, rc, stderr)


def _first_line(text: str) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-1][:200] if lines else ""


def with_retries(step, *, delays=RETRY_DELAYS, log: Log | None = None, sleep=time.sleep):
    """Run `step()`; on Transient retry with the 6.8 delays, then re-raise."""
    for attempt, delay in enumerate((*delays, None), start=1):
        try:
            return step()
        except Transient as exc:
            if delay is None:
                raise
            if log:
                log.event("retry", f"retry {attempt}/{len(delays)}", message=str(exc)[:200])
            sleep(delay)
