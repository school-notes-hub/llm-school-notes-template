import json
import subprocess
from pathlib import Path

import pytest

from school_notes2.local import publish
from school_notes2.site import build as site_build
from tests.conftest import make_origin
from tests.local.conftest import ENV, git


@pytest.fixture
def world(tmp_path, fake_local, local_origin, monkeypatch):
    (tmp_path / "o").mkdir()
    origin = make_origin(tmp_path / "o", {"wiki/index.md": "# Kezdőlap\n", ".gitignore": ".school-notes/\n"})
    (tmp_path / "s").mkdir()
    site = make_origin(tmp_path / "s", {"README.md": "site\n"})
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True, env=ENV)
    (repo / "wiki/index.md").write_text("# Kezdőlap\n\nÚj.\n")
    git(repo, "commit", "-qam", "notes")
    local = fake_local(repo, site_repo=str(site))
    builds, kept = [], []

    def fake_build(git_, commit, task_dir, renderer, *, changed, log, browser_filter=None, keep_log=None):
        kept.append(keep_log)
        out = Path(task_dir) / "build"
        (out / "site").mkdir(parents=True)
        (out / "site" / "index.html").write_text(f"<p>{commit}</p>")
        (out / "payload.json").write_text(json.dumps({"site": "", "base": "/t/", "pages": []}))
        builds.append(out)
        return site_build.BuildRecord(commit, out, 0.1, 1)
    monkeypatch.setattr(publish.site_build, "build", fake_build)
    monkeypatch.setattr(publish, "renderer", lambda local: None)
    monkeypatch.setattr(publish.done, "report", lambda repo, out=print, git=None: 0)
    # local bare origins stand in for GitHub; the real guard has its own tests below
    monkeypatch.setattr(publish, "require_github", lambda url, what: url)
    return {"local": local, "repo": repo, "origin": origin, "site": site, "builds": builds, "kept": kept}


def test_a_failed_build_keeps_its_render_log_in_the_learners_state_folder(world):
    """sn 0.4.2: the build folder is temporary; the render log of a failure goes to one fixed file."""
    assert publish.run(world["local"], out=lambda *_: None) == 0
    local = world["local"]
    assert world["kept"] == [local.cfg.state_dir / local.name / "publish-render.log"]


def ref(bare, name):
    return subprocess.run(["git", f"--git-dir={bare}", "rev-parse", "--verify", "--quiet", name],
                          capture_output=True, text=True, env=ENV).stdout.strip() or None


def head(repo):
    return git(repo, "rev-parse", "HEAD").strip()


def test_publish_pushes_main_builds_gates_and_pushes_gh_pages(world):
    lines = []
    assert publish.run(world["local"], out=lines.append) == 0
    h = head(world["repo"])
    assert ref(world["origin"], "refs/heads/main") == h
    pages = ref(world["site"], "refs/heads/gh-pages")
    record = json.loads(subprocess.run(["git", f"--git-dir={world['site']}", "show", f"{pages}:publish.json"],
                                       capture_output=True, text=True).stdout)
    assert record["source_commit"] == h
    assert ref(world["origin"], "refs/heads/claude-reviewed") is None
    assert not world["builds"][0].exists()                       # the temporary build is gone
    assert (world["local"].site_clone() / ".git").is_dir()
    assert [r[:2] for r in world["local"].records] == [("publish", "ok")]
    calls = world["local"].git_calls
    assert (world["repo"], True) in calls and (world["local"].site_clone(), True) in calls
    url = subprocess.run(["git", "-C", str(world["local"].site_clone()), "remote", "get-url", "origin"],
                         capture_output=True, text=True).stdout.strip()
    assert url == str(world["site"])


def test_reviewed_moves_claude_reviewed(world):
    assert publish.run(world["local"], reviewed=True, out=lambda *_: None) == 0
    assert ref(world["origin"], "refs/heads/claude-reviewed") == head(world["repo"])


def test_nothing_new_publishes_nothing(world):
    publish.run(world["local"], out=lambda *_: None)
    pages = ref(world["site"], "refs/heads/gh-pages")
    lines = []
    assert publish.run(world["local"], out=lines.append) == 0
    assert ref(world["site"], "refs/heads/gh-pages") == pages and len(world["builds"]) == 1
    assert any("nincs teendő" in line for line in lines)


@pytest.mark.parametrize("why", ["dirty", "untracked", "done", "branch"])
def test_preconditions_refuse_before_any_push(world, monkeypatch, why):
    repo = world["repo"]
    if why == "dirty":
        (repo / "wiki/index.md").write_text("changed\n")
    elif why == "untracked":
        (repo / "wiki/new.md").write_text("# New\n")
    elif why == "done":
        monkeypatch.setattr(publish.done, "report", lambda repo, out=print, git=None: 1)
    else:
        git(repo, "switch", "-q", "-c", "other")
    lines = []
    assert publish.run(world["local"], out=lines.append) == 1
    assert lines[-1].startswith("nem adom ki")
    assert ref(world["origin"], "refs/heads/main") != head(repo)
    assert ref(world["site"], "refs/heads/gh-pages") is None and not world["builds"]
    assert world["local"].records[-1][1] == "refused"


def test_gate_failure_stops_before_gh_pages(world, monkeypatch):
    def failing(*a, **k):
        raise site_build.BuildContentError([{"file": "wiki/index.md", "line": None,
                                             "message": "public output matches forbidden pattern"}])
    monkeypatch.setattr(publish.site_build, "build", failing)
    lines = []
    assert publish.run(world["local"], out=lines.append) == 1
    assert ref(world["site"], "refs/heads/gh-pages") is None
    assert ref(world["origin"], "refs/heads/main") == head(world["repo"])      # main goes first
    assert world["local"].records[-1][1] == "held"


def test_build_only_pushes_nothing(world, tmp_path):
    assert publish.run(world["local"], build_only=tmp_path / "b", out=lambda *_: None) == 0
    assert (tmp_path / "b" / "build" / "site" / "index.html").is_file()
    assert ref(world["origin"], "refs/heads/main") != head(world["repo"])
    assert ref(world["site"], "refs/heads/gh-pages") is None


@pytest.mark.parametrize("which", ["origin", "pushurl", "site"])
def test_a_remote_that_is_not_https_github_is_refused_before_any_push(world, monkeypatch, which):
    from school_notes2.local import common
    from school_notes2.state.errors import NeedsOwner
    monkeypatch.setattr(publish, "require_github", common.require_github)
    repo = world["repo"]
    if which == "origin":
        git(repo, "remote", "set-url", "origin", "http://github.com/o/r.git")
    elif which == "pushurl":
        git(repo, "remote", "set-url", "origin", "https://github.com/o/r.git")
        git(repo, "remote", "set-url", "--push", "origin", "http://github.com/o/r.git")
    else:
        git(repo, "remote", "set-url", "origin", "https://github.com/o/r.git")
        world["local"].student.site_repo = "http://github.com/o/site.git"
    with pytest.raises(NeedsOwner):
        publish.run(world["local"], out=lambda *_: None)
    assert ref(world["origin"], "refs/heads/main") != head(repo)
    assert ref(world["site"], "refs/heads/gh-pages") is None
    assert not [c for c in world["local"].git_calls if c[1]]          # no token-bearing git at all
