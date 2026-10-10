import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from school_notes2.config import Sources, Timeouts
from school_notes2.git.run import Git, HttpsToken
from school_notes2.local.common import git_dir
from school_notes2.log import Log
from tests.figures.conftest import make_figure, repo  # noqa: F401 - shared fixtures
from tests.wiki.conftest import INDEX, ROOT, page

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
        self.git_calls = []
        self._ledger = ledger or {"jobs": {}}
        self.cfg = SimpleNamespace(timeouts=Timeouts(), sources=Sources(), root=root, state_dir=root / "state",
                                   git_name="T", git_email="t@example.com")
        self.student = SimpleNamespace(name=name, drive_root=drive_root, site_repo=site_repo, grade=9)
        self.steps = Log(None, console=False)

    def tools_dir(self):
        return TEMPLATE / "tools"

    def record(self, command, outcome="ok", **fields):
        self.records.append((command, outcome, fields))

    def git(self, path=None, *, network=False):
        """With `network` the token-bearing remote, as in production (a fake token)."""
        path = path or self.repo
        self.git_calls.append((Path(path), network))
        remote = HttpsToken("test-token") if network else None
        return Git(git_dir(path), "T", "t@example.com", self.steps, remote, path)

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


def learner_files() -> dict[str, str]:
    """A minimal learner repo: root and subject index, one topic page, subjects.json, public.json."""
    return {
        "wiki/index.md": ROOT, "wiki/a-projektrol.md": "# A projektről\n", "wiki/log.md": "# Napló\n",
        "wiki/proba/index.md": INDEX,
        "wiki/proba/elso.md": page("type: topic\ntitle: Első\ndescription: Az első téma.\n"
                                   "chapter: alapok\norder: 10"),
        "tools/subjects.json": json.dumps({"subjects": {"proba": {"name": "Próba", "emoji": "🧪"}}},
                                          ensure_ascii=False),
        "publication/public.json": json.dumps({"version": 1, "mode": "public", "title": "T",
                                               "base": "/t/", "assets": []}),
        "docs/review/index.md": "# Review\n",
    }
