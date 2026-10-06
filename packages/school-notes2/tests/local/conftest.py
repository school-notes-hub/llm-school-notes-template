import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from school_notes2.config import Role, Sources, Timeouts
from school_notes2.git.run import Git
from school_notes2.local.common import git_dir
from school_notes2.log import Log
from tests.figures.conftest import make_figure, repo  # noqa: F401 - shared fixtures

TEMPLATE = Path(__file__).resolve().parents[4]
ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "PATH": "/usr/bin:/bin",
       "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com",
       "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com"}


def git(path, *args, check=True):
    return subprocess.run(["git", "-C", str(path), *args], check=check, env=ENV,
                          capture_output=True, text=True).stdout


class FakeLocal:
    """What a local command needs from `common.Local`, with fakes for Drive and GitHub."""

    def __init__(self, repo: Path, root: Path, name="barna", drive=None, drive_root="root",
                 site_repo="file:///nonexistent", ledger=None):
        self.repo, self.name, self.records, self._drive = repo, name, [], drive
        self._ledger = ledger or {"jobs": {}}
        self.cfg = SimpleNamespace(timeouts=Timeouts(), sources=Sources(), root=root,
                                   git_name="T", git_email="t@example.com",
                                   role=lambda n: (Role("claude", "model-x", "high"), None))
        self.ctx = SimpleNamespace(name=name, tools_dir=lambda: TEMPLATE / "tools",
                                   student=SimpleNamespace(drive_root=drive_root, site_repo=site_repo))
        self.quiet = Log(None, console=False)

    def record(self, command, outcome="ok", **fields):
        self.records.append((command, outcome, fields))

    def git(self, path=None, *, network=False):
        path = path or self.repo
        return Git(git_dir(path), "T", "t@example.com", self.quiet, None, path)

    def image_settings(self, worktree=None):
        return SimpleNamespace(learner=self.name, worktree=worktree or self.repo, ledger=lambda: self._ledger)

    def drive(self):
        return self._drive

    def downloads(self):
        return self.cfg.root / "downloads" / self.name

    def site_clone(self):
        return self.cfg.root / "site" / self.name


@pytest.fixture
def fake_local(tmp_path):
    def make(repo: Path, **kw) -> FakeLocal:
        return FakeLocal(repo, tmp_path / "state-root", **kw)
    return make


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True, env=ENV)
    (path / ".gitignore").write_text(".school-notes/\n")
    return path
