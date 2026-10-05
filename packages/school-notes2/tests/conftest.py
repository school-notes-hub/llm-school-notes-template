import subprocess
from pathlib import Path

import pytest

from school_notes2.git.run import Git
from school_notes2.log import Log


@pytest.fixture
def log(tmp_path):
    return Log(tmp_path / "logs" / "main.log", run_id="t-run", student="tester", console=False)


def make_origin(tmp_path: Path, files: dict[str, str | bytes]) -> Path:
    """A bare 'origin' with one commit on main holding `files`."""
    seed = tmp_path / "seed"
    seed.mkdir()
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "PATH": "/usr/bin:/bin",
           "GIT_AUTHOR_NAME": "Seed", "GIT_AUTHOR_EMAIL": "seed@example.com",
           "GIT_COMMITTER_NAME": "Seed", "GIT_COMMITTER_EMAIL": "seed@example.com"}
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True, env=env)
    for rel, text in files.items():
        path = seed / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            path.write_bytes(text)
        else:
            path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(seed), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(seed), "commit", "-q", "-m", "seed"], check=True, env=env)
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(origin)], check=True, env=env)
    return origin


@pytest.fixture
def git_factory(log):
    def factory(git_dir: Path, work_tree: Path | None = None) -> Git:
        return Git(git_dir, "Test Owner", "owner@example.com", log, None, work_tree)
    return factory


@pytest.fixture
def local_origin(monkeypatch):
    """Production forbids the file protocol; tests use local bare origins."""
    from school_notes2.git import run
    fixed = tuple(c for c in run.FIXED_C if not c.startswith("protocol.file"))
    monkeypatch.setattr(run, "FIXED_C", fixed + ("protocol.file.allow=always",))


def record_render(repo: Path, asset: str) -> None:
    """Give synthetic raster candidates the same hash-bound proof as real renders."""
    from school_notes2.state import safefs
    from school_notes2.wiki.pages import sha256
    folder, name = asset.rsplit("/", 1)
    source, receipt = f"{folder}/drawing.py", f"{folder}/render.json"
    safefs.write_text(repo, source, "# Drawing source\n")
    outputs = safefs.read_json(repo, receipt, {}).get("outputs", {})
    outputs[name] = {"sha256": sha256(repo, asset)}
    safefs.write_json(repo, receipt, {"source": source, "source_sha256": sha256(repo, source), "outputs": outputs})
