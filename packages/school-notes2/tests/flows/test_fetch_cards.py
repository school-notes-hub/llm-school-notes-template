"""Preflight and shared cards at the existing preparation boundary (T-095)."""

import json
import shutil
from types import SimpleNamespace

import pytest

from school_notes2.flows import fetch
from school_notes2.state import phase
from school_notes2.state.errors import Prerequisite
from school_notes2.wiki import machine
from school_notes2.sources import cards
from tests.sources.test_cards import CARD, LEARNERS, shared
from tests.sources.test_sources import record


def context(repo, monkeypatch):
    def git(*args, **kwargs):
        path = repo / args[1].split(":", 1)[1]           # `show <base>:<path>`
        if not path.exists():
            return SimpleNamespace(returncode=128, stdout=b"")
        return SimpleNamespace(returncode=0, stdout=path.read_bytes())
    wt = SimpleNamespace(run=git)
    ctx = SimpleNamespace(notes_path=repo, worktree=lambda _: wt, image_settings=lambda: None,
                          tools_dir=lambda: None, cfg=SimpleNamespace(limits=SimpleNamespace(review_closures_per_run=20, max_agents=3),
                          sources=SimpleNamespace(
                              max_side_px=2000, jpeg_quality=85, pdf_dpi=200, pages_per_call=30)))
    monkeypatch.setattr(fetch, "_base", lambda *args: "a" * 40)
    monkeypatch.setattr(fetch.workbranch, "start", lambda *args, **kwargs: None)
    monkeypatch.setattr(fetch.workbranch, "reset_workdir", lambda *args: None)
    monkeypatch.setattr(fetch.image_pending, "scan", lambda _: {"pending": []})
    monkeypatch.setattr(fetch.image_plans, "restore", lambda *args: None)
    (repo / ".git").write_text("gitdir: unused\n")
    return ctx


def test_prepare_persists_only_allocated_review_capacity(tmp_path, monkeypatch):
    from school_notes2.review import files
    from school_notes2.state import safefs
    repo = tmp_path / "repo"
    repo.mkdir()
    shared(repo)
    ctx = context(repo, monkeypatch)
    report = files.write_review(repo, "2026-10-04", {"verdict": "changes", "findings": [
        {"severity": "hiba", "id": f"R{n}", "file": "wiki/statika/topic.md", "problem": "Hiba."}
        for n in range(1, 25)]}, "r", "a", "b")
    task = phase.create(tmp_path / "tasks", "barna", "notes", "cron", "moved")
    task.update(selected=[])
    fetch.prepare(ctx, task, new_subject_index=fetch.new_subject)
    task = phase.load(task.dir)
    assert task.get("open_review_items") == []
    assert task.get("calls") == []
    assert not task.get("skip_writer")
    files.apply_closure(repo, task.run_id, [], task.get("open_review_items"), 5)
    counts = files.open_counts(safefs.read_text(repo, report.relative_to(repo).as_posix()))
    assert counts == {}


@pytest.mark.parametrize("student", LEARNERS)
def test_invalid_card_blocks_before_drive_and_prepare(tmp_path, monkeypatch, student):
    repo = tmp_path / "repo"
    repo.mkdir()
    shared(repo, {"statika": {**CARD, "role": " "}})
    ctx = context(repo, monkeypatch)
    task = phase.create(tmp_path / "tasks", student, "notes", "cron", "downloading")
    def no_drive():
        pytest.fail("Drive must not be touched before card validation")
    with pytest.raises(Prerequisite, match="statika") as failure:
        fetch.advance(ctx, task, no_drive)
    assert "subject-cards.json" in failure.value.todo
    assert phase.load(task.dir).phase == "downloading"
    assert task.get("preparation_base") is None
    task.set_phase("moved", selected=[])
    with pytest.raises(Prerequisite):
        fetch.prepare(ctx, task, new_subject_index=fetch.new_subject)
    assert not (repo / "sources").exists()
    shared(repo)
    fetch.prepare(ctx, task, new_subject_index=fetch.new_subject)
    assert phase.load(task.dir).phase == "prepared"


@pytest.mark.parametrize("student", LEARNERS)
def test_new_subject_gets_the_shared_card_and_resumes(tmp_path, monkeypatch, student):
    repo = tmp_path / "repo"
    repo.mkdir()
    shared(repo)
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
    data = fetch.fetch_json(task, 1, grade=10)
    assert data["packages"][0]["new_subject"] is True
    assert data["packages"][0]["card"] == CARD
    assert data["learner"] == {"grade": 10}
    assert (repo / "wiki/statika/index.md").is_file()
    assert machine.add_subjects(repo, [{"subject": "statika", "emoji": "📐", "color": "#336699"}],
                                {"statika": "Statika"})
    entry = json.loads((repo / "tools/subjects.json").read_text())["subjects"]["statika"]
    assert entry["name"] == "Statika" and "card" not in entry and entry["emoji"] == "📐"
    assert fetch.fetch_json(phase.load(task.dir), 1, grade=10) == data


@pytest.mark.parametrize("student", LEARNERS)
def test_missing_card_does_not_stop_preparation(tmp_path, monkeypatch, student):
    """No shared card (or no card file at all): the run goes on without a card."""
    repo = tmp_path / "repo"
    repo.mkdir()
    ctx = context(repo, monkeypatch)
    doc = tmp_path / "document.md"
    doc.write_text("# Tananyag\n")
    selected = [{"package": {"subject_name": "Statika", "name": "Óra", "role": "tanari",
                             "description": "", "preconverted": True},
                 "files": [record(doc, "document.md")]}]
    monkeypatch.setattr(fetch, "download", lambda c, t, d: t.set_phase("downloaded", selected=selected))
    monkeypatch.setattr(fetch, "move", lambda c, t, d: t.set_phase("moved"))
    for entries in (None, {"matematika": CARD}):
        if entries is not None:
            shared(repo, entries)
        task = phase.create(tmp_path / f"tasks-{entries is None}", student, "notes", "cron",
                            "downloading")
        fetch.advance(ctx, task, lambda: object())
        assert task.phase == "prepared"
        data = fetch.fetch_json(task, 1, grade=9)
        assert data["packages"][0]["subject"] == "statika"
        assert "card" not in data and "card" not in data["packages"][0]
        for path in (repo / "sources", repo / "wiki"):
            shutil.rmtree(path, ignore_errors=True)


@pytest.mark.parametrize("student", LEARNERS)
@pytest.mark.parametrize("interrupted_phase", ["downloading", "downloaded"])
def test_download_resume_refreshes_base_before_move(tmp_path, monkeypatch, student, interrupted_phase):
    from school_notes2.state.errors import Transient
    repo = tmp_path / "repo"
    repo.mkdir()
    shared(repo)
    ctx = context(repo, monkeypatch)
    ctx.student = SimpleNamespace(drive_root="root")
    ctx.log = SimpleNamespace(event=lambda *a, **k: None)
    task = phase.create(tmp_path / "tasks", student, "notes", "cron", "downloading")
    def interrupted(*args):
        if interrupted_phase == "downloaded":
            task.set_phase("downloaded", selected=[])
        raise Transient("download interrupted")
    monkeypatch.setattr(fetch, "download", interrupted)
    with pytest.raises(Transient):
        fetch.advance(ctx, task, lambda: object())
    assert phase.load(task.dir).get("preparation_base") is None
    monkeypatch.setattr(fetch, "_base", lambda *a: "b" * 40)
    shared(repo, {"statika": {**CARD, "role": " "}})
    with pytest.raises(Prerequisite):
        fetch.advance(ctx, phase.load(task.dir), lambda: pytest.fail("invalid fresh card"))
    shared(repo)
    monkeypatch.setattr(fetch, "download", lambda c, t, d: t.set_phase("downloaded", selected=[]))
    task = phase.load(task.dir)
    fetch.advance(ctx, task, lambda: object())
    assert task.phase == "prepared"
    assert task.get("base") == "b" * 40
    assert task.get("preparation_started")


@pytest.mark.parametrize("student", LEARNERS)
@pytest.mark.parametrize("when", ["before", "after"])
def test_move_crash_keeps_base_even_while_phase_is_downloaded(tmp_path, monkeypatch, student, when):
    repo = tmp_path / "repo"
    repo.mkdir()
    shared(repo)
    ctx = context(repo, monkeypatch)
    ctx.student = SimpleNamespace(drive_root="root")
    ctx.log = SimpleNamespace(event=lambda *a, **k: None)
    task = phase.create(tmp_path / "tasks", student, "notes", "cron", "downloaded")
    task.update(selected=[{"package": {"id": "pkg", "name": "Óra", "listed": []}}])
    moved = set()
    def interrupted(*args):
        assert phase.load(task.dir).get("preparation_base") == "a" * 40
        if when == "after":
            moved.add("pkg")
        raise RuntimeError("power loss")
    monkeypatch.setattr(fetch, "move_to_processed", interrupted)
    with pytest.raises(RuntimeError, match="power loss"):
        fetch.advance(ctx, task, lambda: object())
    task = phase.load(task.dir)
    assert task.phase == "downloaded" and task.get("preparation_started")
    monkeypatch.setattr(fetch, "_base", lambda *a: pytest.fail("move already pinned the base"))
    def move(*args):
        moved.add("pkg")
        return "moved"
    monkeypatch.setattr(fetch, "move_to_processed", move)
    def prepare(c, t, **kwargs):
        assert fetch._validated_base(c, t) == "a" * 40
        t.set_phase("prepared")
    monkeypatch.setattr(fetch, "prepare", prepare)
    fetch.advance(ctx, task, lambda: object())
    assert task.phase == "prepared" and moved == {"pkg"}


@pytest.mark.parametrize("student", LEARNERS)
def test_legacy_download_base_is_not_reused_by_offline_prepare(tmp_path, monkeypatch, student):
    repo = tmp_path / "repo"
    repo.mkdir()
    shared(repo)
    ctx = context(repo, monkeypatch)
    task = phase.create(tmp_path / "tasks", student, "notes", "interactive", "downloaded")
    task.update(preparation_base="old-download-base", selected=[])
    fetch.advance(ctx, task, lambda: None)
    assert task.phase == "prepared"
    assert task.get("base") == "a" * 40


@pytest.mark.parametrize("student", LEARNERS)
@pytest.mark.parametrize("broken", ['{"subjects": {', '{"subjects": []}',
                                    '{"subjects": {"statika": {"name": 7}}}'])
def test_invalid_subject_list_blocks_before_move_and_resumes_on_a_fresh_base(
        tmp_path, monkeypatch, student, broken):
    """Preparation maps Drive subjects through tools/subjects.json: a broken file stops the
    run before any package leaves Drive, and the fixed file is read from a fresh base."""
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    shared(repo)
    (repo / "tools/subjects.json").write_text(broken)
    ctx = context(repo, monkeypatch)
    ctx.student = SimpleNamespace(drive_root="root")
    ctx.log = SimpleNamespace(event=lambda *a, **k: None)
    task = phase.create(tmp_path / "tasks", student, "notes", "cron", "downloaded")
    task.update(selected=[{"package": {"id": "pkg", "name": "Óra", "listed": []}}])
    moved = []
    monkeypatch.setattr(fetch, "move_to_processed", lambda *a: moved.append(a[1]) or "moved")
    with pytest.raises(Prerequisite, match="tools/subjects.json") as failure:
        fetch.advance(ctx, task, lambda: object())
    assert "tools/subjects.json" in failure.value.todo
    task = phase.load(task.dir)
    assert moved == [] and task.phase == "downloaded"
    assert task.get("preparation_base") is None and not task.get("preparation_started")
    monkeypatch.setattr(fetch, "_base", lambda *args: "b" * 40)
    # A leftover per-learner `card` is not read, even an invalid one (cards are shared).
    (repo / "tools/subjects.json").write_text(json.dumps(
        {"subjects": {"statika": {"name": "Statika", "card": {"role": " "}}}}))
    monkeypatch.setattr(fetch, "prepare", lambda c, t, **k: t.set_phase("prepared"))
    fetch.advance(ctx, task, lambda: object())
    assert moved == ["pkg"] and task.phase == "prepared"
    assert task.get("preparation_base") == "b" * 40


@pytest.mark.parametrize("student", LEARNERS)
@pytest.mark.parametrize("boundary", ["before", "after"])
def test_legacy_literals_migrate_before_assignment_and_resume(tmp_path, monkeypatch, student, boundary):
    from school_notes2.state import safefs
    from school_notes2.wiki import frontmatter, markers
    repo = tmp_path / "repo"
    repo.mkdir()
    shared(repo)
    ctx = context(repo, monkeypatch)
    page, report = "wiki/statika/index.md", "docs/review/legacy.md"
    safefs.write_text(repo, page, markers.wrap("notes", "# 📝 Jegyzetek\n\nSzerzői leírás.\n"))
    safefs.write_text(repo, report, frontmatter.set_keys("# Review\n", {
        "items": {"R1": "open", "R2": "open"}, "status": "open", "item_details": {
            "R1": {"file": page, "quote": "Jegyzetek"},
            "R2": {"file": page, "quote": "Szerzői leírás."}}}))
    task = phase.create(tmp_path / "tasks", student, "notes", "cron", "moved")
    task.update(selected=[])
    original, fired = safefs.write_text, []
    def interrupted(root, path, text, **kwargs):
        if path != report or fired:
            return original(root, path, text, **kwargs)
        fired.append(path)
        if boundary == "after":
            original(root, path, text, **kwargs)
        raise RuntimeError("migration write")
    monkeypatch.setattr(safefs, "write_text", interrupted)
    with pytest.raises(RuntimeError, match="migration write"):
        fetch.prepare(ctx, task, new_subject_index=fetch.new_subject)
    task = phase.load(task.dir)
    fetch.prepare(ctx, task, new_subject_index=fetch.new_subject)
    assert task.get("open_review_items") == []  # Old items belong to fix runs only.
    assert report in task.get("tool_writes")
    assert task.get("learning_pending") is None
