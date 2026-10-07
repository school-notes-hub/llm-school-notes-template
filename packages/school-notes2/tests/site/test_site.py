import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from school_notes2.git import repos, run
from school_notes2.git.run import Git
from school_notes2.site import build as site_build
from school_notes2.site import publish as site_publish
from school_notes2.state.errors import BadWork
from tests.conftest import make_origin

HERE = Path(__file__).parent
STUDY_SITE = HERE.parents[2] / "study-site"
ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "PATH": "/usr/bin:/bin",
       "GIT_AUTHOR_NAME": "L", "GIT_AUTHOR_EMAIL": "l@x", "GIT_COMMITTER_NAME": "L",
       "GIT_COMMITTER_EMAIL": "l@x"}


@pytest.fixture(autouse=True)
def allow_local_origin(monkeypatch):
    # Production forbids the file protocol; the tests use local bare origins.
    fixed = tuple(c for c in run.FIXED_C if not c.startswith("protocol.file"))
    monkeypatch.setattr(run, "FIXED_C", fixed + ("protocol.file.allow=always",))


def public_json(paths):
    return json.dumps({"version": 1, "mode": "public", "title": "T", "base": "/benedek9/",
                       "site": "https://example.org",
                       "pages": [{"path": p, "sha256": "0" * 64} for p in paths]}) + "\n"


PAGES = ["wiki/index.md", "wiki/gazd/index.md", "wiki/gazd/tema.md",
         "wiki/gazd/2026-09-25-ora-jegyzet.md"]
FILES = {
    "wiki/index.md": "# Kezdőlap\n",
    "wiki/gazd/index.md": "# Gazdaság\n",
    "wiki/gazd/tema.md": "# Téma\n\nTartalom. [Fotó](../../sources/gazd/p/p0001.jpg)\n",
    "wiki/gazd/2026-09-25-ora-jegyzet.md": "# Óra\n\n# Nyitott kérdések\n\nEgy szó.[^a]\n\n[^a]: Füzet, 01.jpg\n",
    "publication/public.json": public_json(PAGES),
    "sources/gazd/p/p0001.jpg": "JPEGBYTES",
    "references/konyv/document.md": "könyv",
    "docs/review/index.md": "# Review\n",
}


class Env:
    def __init__(self, tmp_path, log):
        self.tmp = tmp_path
        self.log = log
        self.origin = make_origin(tmp_path, FILES)
        clone = tmp_path / "private"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(clone)], check=True, env=ENV)
        self.bare = Git(clone / ".git", "Tool", "tool@example.com", log, None, clone)
        self.site_origin = tmp_path / "site-origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.site_origin)],
                       check=True, env=ENV)
        # As `sn publish` keeps it: one plain clone per learner, origin = the site repo.
        self.site_path = tmp_path / "work" / "site"
        subprocess.run(["git", "init", "-q", str(self.site_path)], check=True, env=ENV)
        self.site = Git(self.site_path / ".git", "Tool", "tool@example.com", log, None, self.site_path)
        self.site.run("remote", "add", "origin", str(self.site_origin))
        self.study = tmp_path / "study-site"
        self.study.mkdir()
        shutil.copy(HERE / "fake_cli.py", self.study / "cli.mjs")
        shutil.copy(HERE / "fake_browser.py", self.study / "check-browser.mjs")
        shutil.copy(STUDY_SITE / "check-public.py", self.study / "check-public.py")
        shutil.copy(STUDY_SITE / "public-patterns.json", self.study / "public-patterns.json")
        self.renderer = site_build.Renderer(self.study, Path("/bin/true"), tmp_path / "pdf-cache",
                                            node=sys.executable, python=sys.executable)
        self.n = 0

    def main(self) -> str:
        repos.fetch(self.bare, 60)
        return repos.rev(self.bare, "refs/remotes/origin/main")

    def push(self, files: dict[str, str], message="change"):
        clone = self.tmp / f"laptop-{self.n}"
        self.n += 1
        subprocess.run(["git", "clone", "-q", str(self.origin), str(clone)], check=True, env=ENV)
        for rel, text in files.items():
            (clone / rel).parent.mkdir(parents=True, exist_ok=True)
            (clone / rel).write_text(text)
        subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True, env=ENV)
        subprocess.run(["git", "-C", str(clone), "commit", "-qm", message], check=True, env=ENV)
        subprocess.run(["git", "-C", str(clone), "push", "-q", "origin", "main"], check=True, env=ENV)

    def build(self, commit, changed=None, name=None):
        task = self.tmp / "tasks" / (name or commit[:8])
        task.mkdir(parents=True, exist_ok=True)
        return site_build.build(self.bare, commit, task, self.renderer, changed=changed, log=self.log)

    def publish(self, record, run_id="r1"):
        return site_publish.publish(self.site, record.output / "site", student="benedek",
                                    source_commit=record.commit, run_id=run_id,
                                    tool_version="2.0.0", log=self.log)

    def gh_pages_files(self) -> dict[str, bytes]:
        clone = self.tmp / f"check-{self.n}"
        self.n += 1
        subprocess.run(["git", "clone", "-q", "-b", "gh-pages", str(self.site_origin), str(clone)],
                       check=True, env=ENV)
        return {p.relative_to(clone).as_posix(): p.read_bytes()
                for p in clone.rglob("*") if p.is_file() and ".git" not in p.relative_to(clone).parts}

    def gh_pages_log(self) -> list[str]:
        out = subprocess.run(["git", f"--git-dir={self.site_origin}", "log", "--format=%H",
                              "gh-pages"], capture_output=True, text=True, env=ENV)
        return out.stdout.split()


@pytest.fixture
def env(tmp_path, log):
    return Env(tmp_path, log)


def test_extract_leaves_out_sources_and_references(env, tmp_path):
    count = site_build.extract(env.bare, env.main(), tmp_path / "x")
    files = {p.relative_to(tmp_path / "x").as_posix() for p in (tmp_path / "x").rglob("*") if p.is_file()}
    assert "wiki/gazd/tema.md" in files and "publication/public.json" in files
    assert not any(f.startswith(("sources/", "references/")) for f in files)
    assert count == len(files)


def test_last_updated_dates_and_home_gets_latest(env):
    first = env.main()
    env.push({"wiki/gazd/tema.md": FILES["wiki/gazd/tema.md"] + "Új.\n"})
    dates = site_build.last_updated(env.bare, env.main())
    assert dates["wiki/gazd/tema.md"] >= dates["wiki/gazd/index.md"]
    assert dates["wiki/index.md"] == dates["wiki/gazd/tema.md"]
    assert site_build.last_updated(env.bare, first)["wiki/gazd/tema.md"] == dates["wiki/gazd/index.md"]


def test_pages_to_check_adds_indexes():
    pages = PAGES + ["wiki/other/index.md"]
    assert site_build.pages_to_check(["wiki/gazd/tema.md", "docs/x.md"], pages) == [
        "wiki/index.md", "wiki/gazd/index.md", "wiki/gazd/tema.md"]
    assert site_build.pages_to_check([], pages) == []


def test_build_every_page_and_section_goes_out(env):
    record = env.build(env.main())
    site = record.output / "site"
    lesson = (site / "gazd/2026-09-25-ora-jegyzet/index.html").read_text()
    assert "Nyitott kérdések" in lesson and "Füzet, 01.jpg" in lesson
    assert record.pages == len(PAGES)
    assert not list(site.rglob("*.jpg"))
    assert json.loads((record.output / "build.json").read_text())["commit"] == record.commit
    report = json.loads((record.output / "browser-report.json").read_text())
    assert len(report["pages"]) == len(PAGES) and report["origin"] == "http://127.0.0.1:4999"
    assert "2026" in (site / "index.html").read_text()  # the home page carries a date
    # Same commit again: the finished build is reused, not rebuilt.
    (site / "marker").write_text("x")
    assert env.build(record.commit).output == record.output and (site / "marker").exists()


def test_browser_check_visits_only_changed_pages_and_indexes(env):
    record = env.build(env.main(), changed=["wiki/gazd/tema.md"])
    report = json.loads((record.output / "browser-report.json").read_text())
    assert sorted(report["pages"]) == ["wiki/gazd/index.md", "wiki/gazd/tema.md", "wiki/index.md"]


def test_render_error_is_a_content_problem_of_the_page(env):
    env.push({"wiki/gazd/tema.md": "# Téma\n\n$RENDER_FAIL$\n"})
    with pytest.raises(BadWork) as caught:
        env.build(env.main())
    assert caught.value.problems == [{"file": "wiki/gazd/tema.md", "line": None,
                                      "message": "public build: Math rendering failed"}]


def test_browser_error_points_to_the_page(env):
    env.push({"wiki/gazd/tema.md": "# Téma\n\nOVERFLOW table\n"})
    with pytest.raises(BadWork) as caught:
        env.build(env.main())
    assert [p["file"] for p in caught.value.problems] == ["wiki/gazd/tema.md"]
    assert "overflow at 320px" in caught.value.problems[0]["message"]


def test_check_public_blocks_secrets_and_machine_paths_but_not_source_names(env):
    env.push({"wiki/gazd/tema.md": "# Téma\n\nLásd sources/gazd/p/p0001.jpg és 2026-09-25-x/01.jpg.\n"})
    env.build(env.main())  # source names and sources/ text are allowed now (1:1 wiki)
    env.push({"wiki/gazd/tema.md": "# Téma\n\nútvonal: /home/dlaszlo/titok\n"})
    with pytest.raises(BadWork) as caught:
        env.build(env.main())
    assert caught.value.problems[0]["file"] == "wiki/gazd/tema.md"
    assert "/home/" in caught.value.problems[0]["message"]


def test_publish_first_time_is_an_orphan_and_byte_identical_to_the_build(env):
    record = env.build(env.main())
    result = env.publish(record)
    assert result.changed
    files = env.gh_pages_files()
    built = {p.relative_to(record.output / "site").as_posix(): p.read_bytes()
             for p in (record.output / "site").rglob("*") if p.is_file()}
    assert {k: v for k, v in files.items() if k not in (".nojekyll", "publish.json")} == built
    assert json.loads(files["publish.json"]) == {"source_commit": record.commit,
                                                 "tool": "school-notes2 2.0.0"}
    log = env.gh_pages_log()
    assert len(log) == 1
    parents = subprocess.run(["git", f"--git-dir={env.site_origin}", "rev-list", "--parents", "-n1",
                              "gh-pages"], capture_output=True, text=True).stdout.split()
    assert parents == [log[0]]  # no parent: orphan
    message = subprocess.run(["git", f"--git-dir={env.site_origin}", "log", "-1", "--format=%B",
                              "gh-pages"], capture_output=True, text=True).stdout
    assert message.startswith("publish(benedek)") and f"Source-Commit: {record.commit}" in message


def test_same_commit_twice_gives_no_second_gh_pages_commit(env):
    record = env.build(env.main())
    env.publish(record)
    again = env.publish(record, run_id="r2")
    assert not again.changed and len(env.gh_pages_log()) == 1


def test_only_changed_files_go_out(env):
    first = env.build(env.main())
    env.publish(first)
    env.push({"wiki/gazd/tema.md": "# Téma\n\nMódosítva.\n"})
    second = env.build(env.main(), changed=["wiki/gazd/tema.md"])
    env.publish(second)
    log = env.gh_pages_log()
    assert len(log) == 2
    names = subprocess.run(["git", f"--git-dir={env.site_origin}", "diff", "--name-only", log[1], log[0]],
                           capture_output=True, text=True).stdout.split()
    # The edited page and publish.json; the home page only if its "last updated" date moved
    # (the two test commits may share one second).
    assert {"gazd/tema/index.html", "publish.json"} <= set(names)
    assert set(names) <= {"gazd/tema/index.html", "index.html", "publish.json"}


def test_rejected_push_rebuilds_on_the_new_gh_pages(env, monkeypatch):
    first = env.build(env.main())
    env.publish(first)
    env.push({"wiki/gazd/tema.md": "# Téma\n\nB.\n"})
    second = env.build(env.main())
    original = site_publish._push
    calls = []

    def competing(site, commit, log, push_s, ls_remote_s):
        if not calls:
            other = env.tmp / "other-site"
            subprocess.run(["git", "clone", "-q", "-b", "gh-pages", str(env.site_origin), str(other)],
                           check=True, env=ENV)
            (other / "extra.txt").write_text("someone else")
            subprocess.run(["git", "-C", str(other), "add", "-A"], check=True, env=ENV)
            subprocess.run(["git", "-C", str(other), "commit", "-qm", "other"], check=True, env=ENV)
            subprocess.run(["git", "-C", str(other), "push", "-q", "origin", "gh-pages"], check=True, env=ENV)
        calls.append(commit)
        return original(site, commit, log, push_s, ls_remote_s)

    monkeypatch.setattr(site_publish, "_push", competing)
    result = env.publish(second, run_id="r2")
    assert result.changed and len(calls) == 2
    log = env.gh_pages_log()
    assert len(log) == 3 and log[0] == result.commit
    assert "extra.txt" not in env.gh_pages_files()  # the build is the whole truth


def test_publish_needed(env):
    assert site_publish.publish_needed(env.bare, env.site, env.main(), "2.0.0") == (True, "never published")
    record = env.build(env.main())
    env.publish(record)
    site_publish.fetch_gh_pages(env.site, env.log)
    assert site_publish.publish_needed(env.bare, env.site, env.main(), "2.0.0") == (False, "up to date")
    env.push({"docs/review/2026-10-03-review.md": "# Review\n"})
    assert site_publish.publish_needed(env.bare, env.site, env.main(), "2.0.0") == (False, "no published change")
    assert site_publish.publish_needed(env.bare, env.site, env.main(), "2.0.1")[0]
    assert site_publish.changed_since_publish(env.bare, env.site, env.main()) == []
    env.push({"wiki/gazd/tema.md": "# Téma\n\nÚj.\n"})
    needed, reason = site_publish.publish_needed(env.bare, env.site, env.main(), "2.0.0")
    assert needed and reason == "1 published file(s) changed"
    assert site_publish.changed_since_publish(env.bare, env.site, env.main()) == ["wiki/gazd/tema.md"]


def test_wait_until_live_is_only_a_warning(env):
    answers = iter([b"not json", json.dumps({"source_commit": "abc"}).encode()])
    assert site_publish.wait_until_live("https://x/publish.json", "abc", env.log,
                                        fetch=lambda url: next(answers), sleep=lambda s: None)
    assert not site_publish.wait_until_live("https://x/publish.json", "abc", env.log, timeout_s=0,
                                            fetch=lambda url: b"{}", sleep=lambda s: None)


def test_a_deleted_page_or_image_makes_the_browser_check_visit_every_page(env):
    """Védelmek-review blocker: an unchanged page may link the deleted one; its error must
    hold the release, so after a deletion every page is checked (no link search)."""
    env.push({"wiki/gazd/2026-09-25-ora-jegyzet.md": "# Óra\n\nOVERFLOW link a törölt oldalra\n"})
    main = env.main()
    env.build(main, changed=["wiki/gazd/tema.md"], name="changed-only")  # the linking page is not visited
    with pytest.raises(BadWork) as caught:
        env.build(main, changed=["wiki/gazd/torolt.md"], name="deleted")
    assert [p["file"] for p in caught.value.problems] == ["wiki/gazd/2026-09-25-ora-jegyzet.md"]
    assert site_build.deleted(["wiki/assets/gazd/kep.png"], env.tmp / "nowhere")


def test_a_renamed_page_lists_its_old_path_too(env):
    record = env.build(env.main())
    env.publish(record)
    site_publish.fetch_gh_pages(env.site, env.log)
    clone = env.tmp / "rename"
    subprocess.run(["git", "clone", "-q", str(env.origin), str(clone)], check=True, env=ENV)
    subprocess.run(["git", "-C", str(clone), "mv", "wiki/gazd/tema.md", "wiki/gazd/uj-tema.md"], check=True, env=ENV)
    subprocess.run(["git", "-C", str(clone), "commit", "-qm", "rename"], check=True, env=ENV)
    subprocess.run(["git", "-C", str(clone), "push", "-q", "origin", "main"], check=True, env=ENV)
    assert site_publish.changed_since_publish(env.bare, env.site, env.main()) == [
        "wiki/gazd/tema.md", "wiki/gazd/uj-tema.md"]
