"""Local repair trial, queue preparation and restart boundaries (T-095)."""

from types import SimpleNamespace

import pytest

from school_notes2.flows import fetch, handlers, repair, report, run
from school_notes2.repair import check, failure, queue
from school_notes2.state import phase, safefs
from school_notes2.state.errors import BadWork
from school_notes2.state.files import read_json, write_json
from tests.flows.test_repair_queue import page
from tests.sources.test_cards import CARD, LEARNERS, shared
from tests.conftest import recording_mailer


def context(tmp_path, log, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    safefs.write_text(repo, ".git", "gitdir: unused\n")
    shared(repo, {"m": CARD})
    topic = page(repo, "a")
    def git(*args, **kwargs):
        if args[0] == "ls-tree":
            raw = b"\0".join(f"100644 blob hash\t{p}".encode() for p in queue.inventory(repo))
            return SimpleNamespace(returncode=0, stdout=raw)
        rel = args[1].split(":", 1)[1]
        exists = safefs.is_file(repo, rel)
        return SimpleNamespace(returncode=0 if exists else 1,
                               stdout=safefs.read_bytes(repo, rel) if exists else b"")
    wt = SimpleNamespace(run=git, out=lambda *a, **kw: "")
    cfg = SimpleNamespace(root=tmp_path, state_dir=tmp_path / "state", role=lambda _: (None, None))
    mailed = []
    ctx = SimpleNamespace(name="barna", notes_path=repo, worktree=lambda _: wt,
                          task_root=lambda: tmp_path, log=log, cfg=cfg,
                          mailer=recording_mailer(tmp_path, log, monkeypatch, mailed))
    monkeypatch.setattr(repair.repos, "rev", lambda *args: "a" * 40)
    monkeypatch.setattr(repair.workbranch, "changed_files", lambda *args: [])
    monkeypatch.setattr(repair.workbranch, "start", lambda *args, **kw: None)
    return ctx, topic, mailed


@pytest.mark.parametrize("student", LEARNERS)
def test_repair_prepare_restart_snapshots_card_without_drive(tmp_path, log, monkeypatch, student):
    ctx, topic, _ = context(tmp_path, log, monkeypatch)
    ctx.name = student
    task = repair.start(ctx, topic=topic, no_push=True)
    def crash(*args, **kwargs):
        raise RuntimeError("before prepared")
    monkeypatch.setattr(task, "set_phase", crash)
    with pytest.raises(RuntimeError):
        repair.prepare(ctx, task)
    task = phase.load(task.dir)
    repair.prepare(ctx, task)
    inp = fetch.fetch_json(task, 1, grade=11)
    assert inp["mode"] == "repair" and inp["packages"] == inp["pages"] == []
    assert inp["repair_targets"][0]["page"] == topic
    assert inp["card"] == CARD
    assert task.get("no_push")
    shared(ctx.notes_path, {})
    assert fetch.fetch_json(phase.load(task.dir), 1, grade=11) == inp
    assert handlers.generate(ctx, task, "test", None)["state"] == "disabled"
    assert not run._may_run(ctx, task)


def test_queue_prepare_is_tool_only_and_completion_is_resumable(tmp_path, log, monkeypatch):
    ctx, topic, _ = context(tmp_path, log, monkeypatch)
    task = repair.start(ctx, build_queue=True, no_push=True)
    repair.prepare(ctx, task)
    assert task.get("skip_writer") and queue.PATH in task.get("tool_writes")
    task.update(queue_only=False, repair_topic=topic)
    task.set_phase("finishing")
    from school_notes2.flows import journal
    real = safefs.write_text
    def crash(root, rel, text, **kw):
        real(root, rel, text, **kw)
        if rel == queue.PATH:
            raise RuntimeError("after queue write")
    monkeypatch.setattr(safefs, "write_text", crash)
    with pytest.raises(RuntimeError):
        repair.complete(ctx, task)
    task = phase.load(task.dir)
    assert task.get("learning_pending")["path"] == queue.PATH
    monkeypatch.setattr(safefs, "write_text", real)
    journal.settle(ctx, task)
    repair.complete(ctx, task)
    assert queue.load(ctx.notes_path)["items"][0]["status"] == "done"


def test_bad_repair_stops_with_the_work_kept_and_queue_untouched(tmp_path, log, monkeypatch):
    """Point 1: a bad result never discards or archives the work; the run waits for the owner."""
    ctx, topic, mailed = context(tmp_path, log, monkeypatch)
    page(ctx.notes_path, "b")
    safefs.write_json(ctx.notes_path, queue.PATH, queue.build(ctx.notes_path))
    original = safefs.read_bytes(ctx.notes_path, queue.PATH)
    task = repair.start(ctx, topic=topic)
    repair.prepare(ctx, task)
    from school_notes2.git import discard
    discarded = []
    monkeypatch.setattr(discard, "discard", lambda *args: discarded.append(1))
    assert failure.handle(ctx, task, BadWork("bad output"))
    assert task.phase != "done" and not task.get("set_aside") and task.data["needs_owner"]
    assert discarded == []
    assert safefs.read_bytes(ctx.notes_path, queue.PATH) == original


def test_owner_notes_stay_in_private_report(tmp_path, log, monkeypatch):
    ctx, topic, mailed = context(tmp_path, log, monkeypatch)
    task = repair.start(ctx, topic=topic, no_push=True)
    task.update(ranges=[[0, 0], [0, 0]])
    for n, note in enumerate(["Kihagyás, indok, jobb javaslat.", "Második észrevétel."], 1):
        write_json(task.dir / f"result-{n}.json", {"status": "done", "owner_notes": [note]})
    result = report.completion(ctx, task)
    assert result == read_json(task.dir / "report.json")
    assert result["owner_notes"] == ["Kihagyás, indok, jobb javaslat.", "Második észrevétel."]
    assert not mailed


def test_lesson_log_shortening_requires_coverage_and_checks():
    fetch = {"repair_targets": [{"kind": "lesson-notes"}]}
    assert check.coverage({"status": "done"}, fetch)
    assert not check.coverage({"status": "question"}, fetch)
    assert not check.coverage({"status": "done", "coverage": [{"unit": "claim"}], "checks": [{}]}, fetch)
