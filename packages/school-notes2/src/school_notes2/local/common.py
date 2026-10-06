"""What every local command shares (plan 3.1): the configuration, the learner's working copy,
the release this process runs from, git over HTTPS with `gh`'s token, and the log.

The library functions log into a quiet log; each command writes one line of its own to the
JSONL log (`logs/school-notes.log`), so the log reads one line per command."""

import subprocess
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from .. import config
from ..flows import context
from ..git.run import Git, HttpsToken
from ..log import TZ, Log
from ..state.errors import Prerequisite
from . import keys

# local/common.py → local → school_notes2 → src → school-notes2 → packages → the template root
RELEASE = Path(__file__).resolve().parents[5]


def now() -> datetime:
    return datetime.now(TZ)


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def today() -> str:
    return now().date().isoformat()


@dataclass
class Local:
    ctx: context.Ctx
    repo: Path

    @property
    def name(self) -> str:
        return self.ctx.name

    @property
    def cfg(self) -> config.Config:
        return self.ctx.cfg

    @property
    def quiet(self) -> Log:
        return Log(None, student=self.name, console=False)

    def record(self, command: str, outcome: str = "ok", **fields) -> None:
        """The command's one line in the JSONL log."""
        Log(self.cfg.log_path, student=self.name, console=False).event(f"sn.{command}", outcome, **fields)

    def git(self, path: Path | None = None, *, network: bool = False) -> Git:
        """The tool's Git on a normal clone (`path`, default the working copy); with `network`
        the HTTPS token of `gh` goes into git's environment only."""
        path = path or self.repo
        remote = HttpsToken(gh_token()) if network else None
        return Git(git_dir(path), self.cfg.git_name, self.cfg.git_email, self.quiet, remote, path)

    def image_settings(self, worktree: Path | None = None):
        """The shared host ledger and lock; the key is read from the ops `.env` at call time."""
        return replace(self.ctx.image_settings(), worktree=worktree or self.repo, key_file=keys.ENV_FILE)

    def drive(self):
        from ..drive.client import DriveClient, DriveMediaTransport
        transport = DriveMediaTransport(None, self.cfg.timeouts.drive_call_s, tools_dir=self.ctx.tools_dir(),
                                        saved=keys.drive_token(keys.load()))
        return DriveClient(transport, self.cfg.timeouts.download_package_s)

    def site_clone(self) -> Path:
        return self.cfg.root / "site" / self.name

    def downloads(self) -> Path:
        return self.cfg.root / "downloads" / self.name


def load(learner: str, config_path: Path | None = None) -> Local:
    cfg = replace(config.load(config_path), release_dir=RELEASE)
    ctx = context.make(cfg, learner, console=False)
    repo = ctx.student.local_repo or Path.home() / "jegyzet" / f"school-notes-{learner}-active"
    if not (repo / ".git").exists():
        raise Prerequisite(f"{repo} is not a git working copy", todo="clone the learner repo over HTTPS")
    return Local(ctx, repo)


def learners(config_path: Path | None = None) -> list[str]:
    return sorted(config.load(config_path).students)


def git_dir(path: Path) -> Path:
    dot = path / ".git"
    if dot.is_file():                       # a linked worktree: "gitdir: <path>"
        target = Path(dot.read_text(encoding="utf-8").split(":", 1)[1].strip())
        return target if target.is_absolute() else (path / target).resolve()
    return dot


def gh_token() -> str:
    """`gh auth token`, asked at run time; never written anywhere."""
    try:
        proc = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        proc = None
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        raise Prerequisite("gh gives no GitHub token", todo="gh auth login (HTTPS)")
    return proc.stdout.strip()


def https_url(url: str) -> str:
    """`git@github.com:org/repo.git` → `https://github.com/org/repo.git`; HTTPS stays."""
    if url.startswith("git@github.com:"):
        return "https://github.com/" + url.removeprefix("git@github.com:")
    if url.startswith("ssh://git@github.com/"):
        return "https://github.com/" + url.removeprefix("ssh://git@github.com/")
    return url
