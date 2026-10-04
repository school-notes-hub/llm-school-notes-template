"""One hourly run end to end (plan 5.1): fake Drive, fake podman/writer, real Git."""

import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from PIL import Image

from school_notes2 import config
from school_notes2.drive.client import DriveClient
from school_notes2.flows import context, fetch as fetch_flow, finish as finish_flow, prereq
from school_notes2.flows import run as run_flow, setup
from school_notes2.state import phase
from school_notes2.wiki import generate, public
from tests.conftest import make_origin
from tests.drive.fakedrive import FakeDrive
from tests.wiki.conftest import INDEX, ROOT, page

TEMPLATE = Path(__file__).resolve().parents[4]
HERE = Path(__file__).parent


def jpeg(color) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (300, 200), color).save(out, "JPEG")
    return out.getvalue()


def learner_files() -> dict[str, str]:
    files = {
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
    return files


def seeded_origin(tmp_path: Path) -> Path:
    """The learner repo with its generated parts already up to date (as after migration)."""
    work = tmp_path / "gen"
    for rel, text in learner_files().items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(text, encoding="utf-8")
    generate.write_indexes(work)
    public.write(work, public.render_rights(work))
    files = {p.relative_to(work).as_posix(): p.read_text(encoding="utf-8")
             for p in work.rglob("*") if p.is_file()}
    (tmp_path / "origin-src").mkdir()
    return make_origin(tmp_path / "origin-src", files)


@pytest.fixture
def world(tmp_path, local_origin, monkeypatch):
    origin = seeded_origin(tmp_path)
    (tmp_path / "site-src").mkdir()
    site = make_origin(tmp_path / "site-src", {"README.md": "site\n"})
    drive = FakeDrive()
    root = drive.folder("Benedek")
    ready = drive.folder("Feltöltés_Kész", drive.folder("Próba", drive.folder("Füzet", root)))
    package = drive.folder("Óra 1", ready)
    drive.file("1.jpg", package, jpeg("red"))
    drive.file("2.jpg", package, jpeg("blue"))
    drive.folder("Feldolgozva", drive.items[ready]["parents"][0])
    cfg = config.parse({
        "root": str(tmp_path / "srv"), "secrets_dir": str(tmp_path / "secrets"),
        "email_to": "o@example.com", "git": {"name": "O", "email": "o@example.com"},
        "release_dir": str(TEMPLATE),
        "students": {"benedek": {"repo": str(origin), "repo_key": "/nonexistent",
                                 "site_repo": str(site), "site_key": "/nonexistent",
                                 "drive_root": root, "grade": 9}},
        "roles": {"writer": {"harness": "codex", "model": "fake", "effort": "high", "timeout_s": 60},
                  "reviewer": {"harness": "claude-review", "model": "fake", "effort": "high",
                               "timeout_s": 60}},
    })
    ctx = context.make(cfg, "benedek", console=False)
    setup.setup(ctx)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "podman").write_text(f"#!/bin/sh\nexec {sys.executable} {HERE / 'fake_podman.py'} \"$@\"\n")
    (bin_dir / "podman").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    runtime = Path(tempfile.mkdtemp(prefix="sn-rt-"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr(fetch_flow, "drive_client", lambda ctx: DriveClient(drive))
    monkeypatch.setattr(prereq, "podman", lambda: None)
    monkeypatch.setattr(finish_flow, "_build", lambda ctx, task, commit: {"commit": commit,
                                                                           "output": "/nonexistent"})
    # The fake Drive's clock is fixed; the packages are an hour old by it.
    monkeypatch.setattr("school_notes2.drive.inventory.datetime", _FixedNow)
    return ctx, origin, drive, package


class _FixedNow:
    from datetime import datetime as _dt

    @classmethod
    def now(cls, tz=None):
        from tests.drive.fakedrive import NOW
        return NOW

    @classmethod
    def fromisoformat(cls, value):
        return cls._dt.fromisoformat(value)


def show(origin: Path, rev_path: str) -> str:
    return subprocess.run(["git", f"--git-dir={origin}", "show", rev_path],
                          capture_output=True, text=True).stdout


def test_hourly_run_end_to_end(world):
    ctx, origin, drive, package = world
    rc = run_flow.run(ctx)
    assert rc == 0, ctx.cfg.log_path.read_text()[-3000:]
    task = phase.all_tasks(ctx.task_root(), "benedek")[-1]
    assert task.phase == "done", task.data
    log = show(origin, "main")
    assert f"Run-Id: {task.run_id}" in log and "notes(benedek): Teszt óra feldolgozva." in log
    note = show(origin, "main:wiki/proba/2026-10-02-teszt-jegyzet.md")
    assert "type: lesson-notes" in note and "content_sha256" in note and "drive_folder: Óra 1" in note
    assert "grade: 9" in note
    # The configured school year reaches the writer: fetch.json and the prompt's yardstick.
    work = ctx.notes_path
    assert json.loads(work.with_name(f"{work.name}-fetch-learner.json").read_text()) == {"grade": 9}
    prompt = work.with_name(f"{work.name}-writer-prompt.txt").read_text()
    assert "Az olvasó a 9. évfolyamos tanuló" in prompt and "{grade}" not in prompt
    index = show(origin, "main:wiki/proba/index.md")
    assert "Teszt óra" in index
    listing = subprocess.run(["git", f"--git-dir={origin}", "ls-tree", "-r", "--name-only", "main",
                              "sources/"], capture_output=True, text=True).stdout
    assert "sources/proba/ora-1/1.jpg" in listing and "sources/proba/ora-1/2.jpg" in listing
    moved_to = drive.items[package]["parents"][0]
    assert drive.items[moved_to]["name"] == "Feldolgozva"


def test_second_run_without_packages_does_nothing(world):
    ctx, origin, drive, package = world
    assert run_flow.run(ctx) == 0
    before = show(origin, "main")
    assert run_flow.run(ctx) == 0
    assert show(origin, "main") == before


def test_bad_link_goes_back_to_the_writer_then_needs_owner(world, monkeypatch):
    ctx, origin, drive, package = world
    monkeypatch.setenv("FAKE_WRITER", "badlink")
    assert run_flow.run(ctx) == 1
    task = phase.open_task(ctx.task_root(), "benedek", "notes")
    assert task.phase == "writing" and task.data["llm_failures"] == 1
    check = json.loads((ctx.notes_path / ".school-notes/check.json").read_text())
    assert any("nincs-ilyen" in json.dumps(i) for i in check)
    assert run_flow.run(ctx) == 1
    task = phase.open_task(ctx.task_root(), "benedek", "notes")
    assert task.data["needs_owner"]["class"] == "bad_work"
