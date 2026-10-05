"""A local origin, a 'laptop' clone that pushes, and the tool's bare clone + review worktree."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from school_notes2.git import repos as gitrepos
from school_notes2.git import run as gitrun
from school_notes2.git.run import Git

ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "PATH": "/usr/bin:/bin",
       "GIT_AUTHOR_NAME": "Laptop", "GIT_AUTHOR_EMAIL": "l@example.com",
       "GIT_COMMITTER_NAME": "Laptop", "GIT_COMMITTER_EMAIL": "l@example.com"}

REVIEW_INDEX = "# Review-állapot\n\nKézzel írt szöveg.\n"


def sh(*args, cwd=None) -> str:
    return subprocess.run(args, cwd=cwd, env=ENV, check=True, capture_output=True,
                          text=True).stdout.strip()


@dataclass
class Repos:
    origin: Path
    laptop: Path
    bare: Path
    wt_path: Path
    repo: Git
    wt: Git

    def commit(self, files: dict[str, str | bytes], msg: str = "change\n\nSchool-Notes-Run: run") -> str:
        for rel, data in files.items():
            path = self.laptop / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(data, bytes):
                path.write_bytes(data)
            else:
                path.write_text(data, encoding="utf-8")
        sh("git", "add", "-A", cwd=self.laptop)
        sh("git", "commit", "-q", "-m", msg, cwd=self.laptop)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.laptop)
        return sh("git", "rev-parse", "HEAD", cwd=self.laptop)

    def remote(self, ref: str) -> str:
        return sh("git", "--git-dir", str(self.origin), "rev-parse", ref)


@pytest.fixture
def repos(tmp_path, log, monkeypatch) -> Repos:
    # Tests use a local path origin; production keeps protocol.file.allow=never.
    monkeypatch.setattr(gitrun, "FIXED_C",
                        tuple(c for c in gitrun.FIXED_C if not c.startswith("protocol.file")))
    origin = tmp_path / "origin.git"
    sh("git", "init", "-q", "--bare", "-b", "main", str(origin))
    laptop = tmp_path / "laptop"
    sh("git", "clone", "-q", str(origin), str(laptop))
    sh("git", "switch", "-q", "-c", "main", cwd=laptop)
    (laptop / "docs/review").mkdir(parents=True)
    (laptop / "docs/review/index.md").write_text(REVIEW_INDEX, encoding="utf-8")
    (laptop / "wiki").mkdir()
    (laptop / "wiki/index.md").write_text("# Kezdőlap\n", encoding="utf-8")
    sh("git", "add", "-A", cwd=laptop)
    sh("git", "commit", "-q", "-m", "seed", cwd=laptop)
    sh("git", "push", "-q", "origin", "HEAD:main", "HEAD:claude-reviewed", cwd=laptop)
    bare = tmp_path / "tool.git"
    sh("git", "clone", "-q", "--bare", str(origin), str(bare))
    sh("git", "--git-dir", str(bare), "config", "--replace-all", "remote.origin.fetch",
       "refs/heads/main:refs/remotes/origin/main")
    sh("git", "--git-dir", str(bare), "config", "--add", "remote.origin.fetch",
       "refs/heads/claude-reviewed:refs/remotes/origin/claude-reviewed")
    sh("git", "--git-dir", str(bare), "fetch", "-q", "origin")
    wt_path = tmp_path / "work" / "review"
    sh("git", "--git-dir", str(bare), "worktree", "add", "-q", "--detach", str(wt_path),
       "refs/remotes/origin/main")
    repo = Git(bare, "Tool Owner", "owner@example.com", log)
    wt = gitrepos.worktree_git(repo, wt_path)
    return Repos(origin, laptop, bare, wt_path, repo, wt)
