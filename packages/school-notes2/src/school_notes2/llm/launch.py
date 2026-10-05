"""Launching an LLM role in the agent container (plan 5.3, 5.6/4, 7.4, 8.1).

The tool never parses the harness's event stream to decide success: success is exit code 0
plus a schema-valid output (file or stdout mode). Metrics are best effort.
"""

import hashlib
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..config import Harness, Role
from ..log import Log
from ..state import safefs
from ..state.errors import BadWork, NeedsOwner, Prerequisite, Transient, SnError, WaitingQuota
from . import metrics as metrics_mod
from .output import extract_stdout, read_file
from .leases import guarded

from .argv import (DEFAULT_LOGIN_DOMAINS, DEFAULT_PROVIDER_DOMAINS, EXIT_API,  # noqa: F401
                   EXIT_FIREWALL, EXIT_PREFLIGHT, LOGIN_COMMANDS, NOT_EXECUTABLE,
                   PODMAN_FAILED, Limits, Mounts, api_domain, container_name, expand, family,
                   harness_command, home_volume, podman_argv, prompt)


def tree_fingerprint(root: Path, exclude: tuple[str, ...] = (".school-notes",)) -> str:
    """A cheap fingerprint of a tree (paths, sizes, mtimes) to tell whether the LLM worked."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.is_dir() or (rel.parts and rel.parts[0] in exclude):
            continue
        st = path.lstat()
        digest.update(f"{rel}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
    return digest.hexdigest()


@dataclass(frozen=True)
class RoleRun:
    """Everything one headless role call needs."""

    learner: str
    run_id: str
    role_name: str               # writer | reviewer
    role: Role
    harness: Harness
    image: str
    mounts: Mounts
    output_host: Path            # where the output file appears on the host (file mode)
    schema: str                  # result | review
    task_dir: Path
    grade: int                   # the learner's school year, filled into the prompt
    label: str = "1"             # range k, or attempt; part of the transcript name
    allowed_domains: tuple[str, ...] = DEFAULT_PROVIDER_DOMAINS
    limits: Limits = Limits()
    max_agents: int = 3
    lease_dir: Path | None = None
    attempt: int = 1


@dataclass
class Outcome:
    rc: int
    timed_out: bool
    duration_s: float
    output: dict | None
    problems: list[str]
    changed: bool
    transcript: Path
    metrics: dict = field(default_factory=dict)


def _open_private(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    return os.fdopen(fd, "wb")


def remove_stale(name: str, podman: str = "podman") -> None:
    """Whoever holds the learner lock owns the container name; a leftover one is stale."""
    subprocess.run([podman, "rm", "-f", "--ignore", name], capture_output=True, timeout=60)


def _wait(proc: subprocess.Popen, name: str, timeout: float, podman: str) -> bool:
    """Wait for the harness; on timeout `podman stop -t 10`. True when it timed out."""
    try:
        proc.wait(timeout=timeout)
        return False
    except subprocess.TimeoutExpired:
        subprocess.run([podman, "stop", "-t", "10", name], capture_output=True, timeout=60)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        return True


def _read_output(run: RoleRun, transcript: Path) -> tuple[dict | None, list[str], bool]:
    """(output, problems, produced): `produced` means the role wrote something at all."""
    if run.harness.output == "stdout":
        text = transcript.read_text(encoding="utf-8", errors="replace")
        value, problems = extract_stdout(text, run.schema)
        return value, problems, value is not None
    root = _output_root(run)
    value, problems = read_file(run.output_host, run.schema, root)
    try:
        produced = safefs.exists(root, safefs.rel_of(root, run.output_host))
    except safefs.UnsafePath:
        produced = True                 # something was written there, just not usable
    return value, problems, produced


def _output_root(run: RoleRun) -> Path:
    """The container-controlled tree holding the output file (worktree or out/)."""
    for root in (run.mounts.out_dir, run.mounts.work):
        if root and run.output_host.is_relative_to(root):
            return root
    return run.output_host.parent


class TimedOut(SnError):
    """T-125: timeout is independent of bad work and transport retries."""

    kind = "timeout"


def classify(rc: int, timed_out: bool, changed: bool, produced: bool,
             output: dict | None, problems: list[str]) -> Exception | None:
    """Map one role call to the 8.1 classes; None means success."""
    if rc == EXIT_PREFLIGHT:
        return NeedsOwner("the container preflight security check failed",
                          todo="read the run log; the container saw something it must not")
    if rc == EXIT_FIREWALL:
        return NeedsOwner("the container firewall could not be loaded",
                          todo="check Podman and iptables on the VM")
    if rc == EXIT_API:
        return Transient("the model API is unreachable from the container")
    if rc == PODMAN_FAILED:
        return Prerequisite("Podman could not start the agent container",
                            todo="check `podman info` and XDG_RUNTIME_DIR for the cron user")
    if rc in NOT_EXECUTABLE:
        return NeedsOwner(f"the harness command is missing in the image (exit {rc})",
                          todo="check the role template and the installed image")
    if timed_out:
        return TimedOut("the LLM ran out of time")
    if rc == 0 and output is not None:
        return None
    if rc == 0:
        return BadWork("output missing or invalid: " + "; ".join(problems[:5]))
    if not changed and not produced:
        return Transient(f"the LLM did not work (exit {rc}, nothing changed)")
    return BadWork(f"the LLM exited with {rc} after changing files: " + "; ".join(problems[:3]))


def run_headless(run: RoleRun, *, log: Log, snapshot: Callable[[], object],
                 podman: str = "podman") -> Outcome:
    """Start the role, feed the fixed prompt, wait, read and classify the output.

    Raises the 8.1 error class on failure; returns the Outcome on success.
    """
    from . import guard
    return guard.headless(run, lambda admitted: _admitted(admitted, log=log, snapshot=snapshot, podman=podman))


def _admitted(run, *, log, snapshot, podman):
    from .leases import acquire
    root = run.lease_dir or run.task_dir / "agent-leases"
    with acquire(root, run.learner, _volume_role(run.role_name), run.max_agents):
        return _headless(run, log=log, snapshot=snapshot, podman=podman)


def _headless(run, *, log, snapshot, podman):
    name = container_name(run.learner, run_id=run.run_id, role=run.role_name,
                          unit=run.label, attempt=run.attempt)
    remove_stale(name, podman)
    run.output_host.unlink(missing_ok=True)
    before = snapshot()
    text = prompt(run.role_name, run.harness.output, grade=run.grade)
    argv = podman_argv(learner=run.learner, image=run.image, run_id=run.run_id,
                       mounts=run.mounts, name=name, role=_volume_role(run.role_name),
                       allowed_domains=run.allowed_domains,
                       probe_domain=api_domain(run.harness, run.allowed_domains),
                       limits=run.limits, podman=podman)
    argv += harness_command(run.harness, run.role, text)
    transcript = run.task_dir / f"transcript-{run.role_name}-{run.label}.log"
    start = time.monotonic()
    with _open_private(transcript) as out:
        timed_out, rc = _run_fed(argv, text.encode("utf-8") if run.harness.prompt_stdin else None,
                                 out, name, run.role.timeout_s, podman)
    duration = time.monotonic() - start
    changed = snapshot() != before
    output, problems, produced = _read_output(run, transcript)
    outcome = Outcome(rc, timed_out, duration, output, problems, changed,
                      transcript, metrics_mod.from_transcript(transcript))
    from .quota import exhausted
    error = (WaitingQuota("A harness heti kerete elfogyott.")
             if not timed_out and exhausted(transcript) else
             classify(outcome.rc, timed_out, changed, produced, output, problems))
    log.event(f"llm.launch role={run.role_name}", "ok" if error is None else "error",
              step=run.label, duration_s=duration, rc=outcome.rc, timed_out=timed_out,
              changed=changed, model=run.role.model, effort=run.role.effort,
              harness=run.harness.name,
              prompt_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
              prompt_bytes=len(text.encode("utf-8")), error_class=getattr(error, "kind", ""),
              **{f"m_{k}": v for k, v in outcome.metrics.items()})
    if error is not None:
        raise error
    return outcome


def _volume_role(role_name: str) -> str:
    """The reviewer has its own home; everything else (writer, chat) uses the writer's."""
    return "reviewer" if role_name in ("reviewer", "figure-review", "reader-1", "recheck") else "writer"


def _run_fed(argv: list[str], stdin: bytes | None, out, name: str, timeout: float,
             podman: str) -> tuple[bool, int]:
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE if stdin is not None else
                            subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
    if stdin is not None:
        try:
            proc.stdin.write(stdin)
        except BrokenPipeError:
            pass
        proc.stdin.close()
    timed_out = _wait(proc, name, timeout, podman)
    return timed_out, proc.returncode


def run_interactive(**kwargs):
    from . import guard
    return guard.interactive(kwargs, _interactive)


@guarded("writer")
def _interactive(*, learner: str, run_id: str, role: Role, harness: Harness, image: str,
                    mounts: Mounts, log: Log,
                    allowed_domains: tuple[str, ...] = DEFAULT_PROVIDER_DOMAINS,
                    limits: Limits = Limits(), podman: str = "podman") -> int:
    """The owner's `chat` session: same image, same MCP, interactive template, no timeout.
    It runs on the writer's home volume."""
    name = container_name(learner, run_id=run_id, role="chat")
    remove_stale(name, podman)
    argv = podman_argv(learner=learner, image=image, run_id=run_id, mounts=mounts, name=name,
                       role="writer", interactive=True, allowed_domains=allowed_domains,
                       probe_domain=api_domain(harness, allowed_domains), limits=limits,
                       podman=podman) + expand(harness.interactive, role)
    start = time.monotonic()
    rc = subprocess.call(argv)
    log.event("llm.launch role=interactive", "ok", duration_s=time.monotonic() - start, rc=rc,
              harness=harness.name, model=role.model)
    if rc in (EXIT_PREFLIGHT, EXIT_FIREWALL, EXIT_API, PODMAN_FAILED):
        raise classify(rc, False, False, False, None, [])
    return rc


@guarded(None)
def login_ok(*, learner: str, run_id: str, role: str, harness: Harness, image: str, log: Log,
             allowed_domains: tuple[str, ...] = DEFAULT_PROVIDER_DOMAINS,
             podman: str = "podman", timeout: float = 120) -> bool:
    """Run the template's login check in the image with the role's home volume."""
    name = container_name(learner, run_id=run_id or "login", role=role + "-login")
    remove_stale(name, podman)
    argv = podman_argv(learner=learner, image=image, run_id=run_id, mounts=Mounts(home=True),
                       name=name, role=role, allowed_domains=allowed_domains,
                       probe_domain=api_domain(harness, allowed_domains),
                       podman=podman) + list(harness.login_check)
    try:
        proc = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        subprocess.run([podman, "rm", "-f", "--ignore", name], capture_output=True, timeout=60)
        raise Transient("the harness login check timed out") from None
    log.event("llm.login_check", "ok" if proc.returncode == 0 else "error",
              harness=harness.name, role=role, rc=proc.returncode)
    if proc.returncode in (0, 1):
        return proc.returncode == 0
    raise classify(proc.returncode, False, False, False, None, []) or Transient("login check")


@guarded(None)
def run_login(*, learner: str, role: str, harness: Harness, image: str, log: Log,
              allowed_domains: tuple[str, ...], podman: str = "podman") -> int:
    """The owner's one-off harness login on a role's home volume (plan 7.4, 10.4).

    `allowed_domains` must include the login sites (provider + login domains)."""
    name = container_name(learner, run_id="login", role=role + "-login")
    remove_stale(name, podman)
    command = LOGIN_COMMANDS.get(family(harness))
    if command is None:
        raise NeedsOwner(f"no login command known for harness {harness.name}",
                         todo="log in by hand in the container")
    argv = podman_argv(learner=learner, image=image, run_id="login", mounts=Mounts(home=True),
                       name=name, role=role, interactive=True, allowed_domains=allowed_domains,
                       probe_domain=api_domain(harness, allowed_domains),
                       podman=podman) + command
    rc = subprocess.call(argv)
    log.event("llm.login", "ok" if rc == 0 else "error", harness=harness.name, role=role, rc=rc)
    if rc in (EXIT_PREFLIGHT, EXIT_FIREWALL, EXIT_API, PODMAN_FAILED):
        raise classify(rc, False, False, False, None, [])
    return rc


