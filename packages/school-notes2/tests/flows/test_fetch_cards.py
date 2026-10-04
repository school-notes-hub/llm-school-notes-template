"""Preflight and preloaded cards at the existing preparation boundary (T-095)."""

import json
from types import SimpleNamespace

import pytest

from school_notes2.flows import fetch
from school_notes2.state import phase
from school_notes2.state.errors import Prerequisite
from school_notes2.wiki import machine
from tests.sources.test_cards import CARD, subjects
from tests.sources.test_sources import record


def context(repo, monkeypatch):
    def git(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=(repo / "tools/subjects.json").read_bytes())
    wt = SimpleNamespace(run=git)
    ctx = SimpleNamespace(notes_path=repo, worktree=lambda _: wt, image_settings=lambda: None,
                          tools_dir=lambda: None, cfg=SimpleNamespace(sources=SimpleNamespace(
                              max_side_px=2000, jpeg_quality=85, pdf_dpi=200, pages_per_call=30)))
    monkeypatch.setattr(fetch, "_base", lambda *args: "a" * 40)
    monkeypatch.setattr(fetch.workbranch, "start", lambda *args, **kwargs: None)
    monkeypatch.setattr(fetch.workbranch, "reset_workdir", lambda *args: None)
    monkeypatch.setattr(fetch.image_pending, "scan", lambda _: {"pending": []})
    monkeypatch.setattr(fetch.image_plans, "restore", lambda *args: None)
    (repo / ".git").write_text("gitdir: unused\n")
    return ctx


@pytest.mark.parametrize("student", ["benedek", "barna"])
def test_invalid_card_blocks_before_drive_and_prepare(tmp_path, monkeypatch, student):
    repo = tmp_path / "repo"
    repo.mkdir()
    subjects(repo, {**CARD, "role": " "})
    ctx = context(repo, monkeypatch)
    task = phase.create(tmp_path / "tasks", student, "notes", "cron", "downloading")
    def no_drive():
        pytest.fail("Drive must not be touched before card validation")
    with pytest.raises(Prerequisite, match="statika") as failure:
        fetch.advance(ctx, task, no_drive)
    assert "tools/subjects.json statika" in failure.value.todo
    assert phase.load(task.dir).phase == "downloading"
    assert task.get("preparation_base") is None
    task.set_phase("moved", selected=[])
    with pytest.raises(Prerequisite):
        fetch.prepare(ctx, task, new_subject_index=fetch.new_subject)
    assert not (repo / "sources").exists()
    subjects(repo)
    fetch.prepare(ctx, task, new_subject_index=fetch.new_subject)
    assert phase.load(task.dir).phase == "prepared"


@pytest.mark.parametrize("student", ["benedek", "barna"])
def test_preloaded_subject_prepares_and_resumes(tmp_path, monkeypatch, student):
    repo = tmp_path / "repo"
    repo.mkdir()
    subjects(repo)
    ctx = context(repo, monkeypatch)
    doc = tmp_path / "document.md"
    doc.write_text("# Tananyag\n")
    task = phase.create(tmp_path / "tasks", student, "notes", "cron", "moved")
    task.update(selected=[{"package": {"subject_name": "Statika", "name": "Óra", "role": "tanari",
                                       "description": "", "preconverted": True},
                          "files": [record(doc, "document.md")]}])
    def crash(*args):
        raise RuntimeError("crash before placement")
    with pytest.raises(RuntimeError, match="crash"):
        fetch.prepare(ctx, task, new_subject_index=crash)
    assert phase.load(task.dir).get("preparation_base") == "a" * 40
    # A moving origin must not change the already validated preparation base.
    monkeypatch.setattr(fetch, "_base", lambda *args: pytest.fail("base must stay pinned"))
    task = phase.load(task.dir)
    fetch.prepare(ctx, task, new_subject_index=fetch.new_subject)
    data = fetch.fetch_json(task, 1)
    assert data["packages"][0]["new_subject"] is True
    assert data["packages"][0]["card"] == CARD
    assert (repo / "wiki/statika/index.md").is_file()
    assert machine.add_subjects(repo, [{"subject": "statika", "emoji": "📐", "color": "#336699"}], {})
    entry = json.loads((repo / "tools/subjects.json").read_text())["subjects"]["statika"]
    assert entry["name"] == "Statika" and entry["card"] == CARD and entry["emoji"] == "📐"
    assert fetch.fetch_json(phase.load(task.dir), 1) == data
