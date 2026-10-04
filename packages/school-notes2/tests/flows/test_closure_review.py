"""Closure review regressions: owner data, scoped handoff and replay-safe P4 filing."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from school_notes2.figures import requests, licenses
from school_notes2.flows import checks, correction, fetch, generation_receipts, handlers, learning, status, steps
from school_notes2.repair import queue
from school_notes2.state import phase, safefs
from school_notes2.state.errors import NeedsOwner
from school_notes2.wiki import frontmatter
from tests.wiki.conftest import repo
from tests.wiki.test_guard import snapshot, run
from tests.flows.test_learning_checks import learning_run


TOPIC = "wiki/proba/elso.md"
NOTE = "wiki/proba/2026-09-10-elso-jegyzet.md"


def request(repo):
    safefs.write_text(repo, TOPIC, safefs.read_text(repo, TOPIC) + "\n<!-- figure-request: test -->\n")
    return {"id": "test", "page": TOPIC, "source": "sources/proba/csomag/01.jpg",
            "crop": "teljes kép", "purpose": "Tanulás", "origin": "teacher-own"}


def granted(repo):
    value = requests.collect(repo, [request(repo)])[0]
    safefs.write_json(repo, requests.PATH, [value])
    safefs.write_json(repo, licenses.PATH, [{"sha256": value["content_sha256"], "request_id": value["id"],
        "granted_by": "Rights holder", "scope": "public-with-credit", "credit": "Credit: public author",
        "own_work_confirmed": True, "on": "2026-10-04"}])
    return value


@pytest.mark.parametrize("crash", ["before", "after"])
def test_p4_request_filing_resumes_without_replacing_its_journal(repo, tmp_path, monkeypatch, crash):
    result = {"status": "done", "figure_requests": [request(repo)]}
    ctx = SimpleNamespace(notes_path=repo, cfg=SimpleNamespace(limits=SimpleNamespace(owner_after_open=5)),
                          image_settings=lambda: SimpleNamespace(learner="sample", ledger=lambda: {"jobs": {}}))
    task = phase.create(tmp_path / "tasks", "sample", "notes", "cron", "correcting")
    root = task.dir / "correction"
    saved = {"status": "done", "result": result, "tool_state": {"tool_writes": {}, "tool_parts": {}, "tool_hashes": {}}}
    base = snapshot(repo)
    real = safefs.write_text
    def interrupted(root, rel, text, **kw):
        if rel == requests.PATH:
            if crash == "after":
                real(root, rel, text, **kw)
            raise RuntimeError("power loss")
        return real(root, rel, text, **kw)
    with monkeypatch.context() as patch:
        patch.setattr(safefs, "write_text", interrupted)
        with pytest.raises(RuntimeError, match="power loss"):
            correction.apply(ctx, task, root, saved)
    resumed = phase.load(task.dir)
    assert resumed.get("learning_pending")["path"] == requests.PATH
    correction.apply(ctx, resumed, root, saved)
    assert resumed.get("learning_pending") is None
    assert requests.active(repo)[0]["original_sha256"] is None
    first = snapshot(repo)
    correction.apply(ctx, phase.load(task.dir), root, saved)
    assert snapshot(repo) == first
    changes = [(p, "modified" if p in base else "added") for p, data in first.items() if base.get(p) != data]
    assert not run(repo, base, changes, tool_files=resumed.get("tool_writes"), tool_parts=resumed.get("tool_parts", {}))


def test_check_during_background_generation_preserves_all_task_state(learning_run, monkeypatch):
    ctx, task = learning_run
    started, finish = Event(), Event()
    def generate(*args, **kwargs):
        started.set()
        assert finish.wait(10)
        return {"state": "generated", "number": 1, "sha256": "a" * 64, "preview_sha256": "b" * 64}
    monkeypatch.setattr(handlers.image_generate, "generate", generate)
    api = handlers.build(ctx, task.dir)
    with ThreadPoolExecutor(max_workers=1) as executor:
        job = executor.submit(api.image_generate, "test", None)
        try:
            assert started.wait(10)
            assert api.check()["ok"]
            before = phase.load(task.dir).data
            assert before["data"]["writer_check"]["count"] == 1
            assert before["data"]["tool_parts"]
        finally:
            finish.set()
        assert job.result()["state"] == "generated"
    assert phase.load(task.dir).data == before
    assert not safefs.walk_files(ctx.notes_path, "docs/evidence/image-generation")


def test_generated_receipts_are_one_sorted_write_and_learner_scoped(repo, tmp_path, monkeypatch):
    entries = {name: {"learner": learner, "attempts": [{"state": "generated", "sha256": digest}]}
               for name, learner, digest in [("b", "sample", "b" * 64), ("other", "other", "c" * 64),
                                             ("a", "sample", "a" * 64)]}
    settings = SimpleNamespace(learner="sample", ledger=lambda: {"jobs": entries})
    ctx = SimpleNamespace(notes_path=repo, image_settings=lambda: settings)
    task = phase.create(tmp_path / "tasks", "sample", "notes", "cron", "finishing")
    generation_receipts.refresh(ctx, task)
    paths = safefs.walk_files(repo, "docs/evidence/image-generation")
    assert len(paths) == 1
    assert safefs.read_json(repo, paths[0])["outputs"] == ["a" * 64, "b" * 64]
    before = safefs.read_bytes(repo, paths[0])
    entries = dict(reversed(list(entries.items())))
    generation_receipts.refresh(ctx, phase.load(task.dir))
    assert safefs.read_bytes(repo, paths[0]) == before
    legacy = "docs/evidence/image-generation/old-run.json"
    safefs.write_text(repo, legacy, '{"rights": "generated", "outputs": []}\n')
    old = safefs.read_bytes(repo, legacy)
    writes = []
    original = generation_receipts.journal.write
    def record(*args, **kwargs):
        writes.append(args[2])
        return original(*args, **kwargs)
    monkeypatch.setattr(generation_receipts.journal, "write", record)
    next_task = phase.create(tmp_path / "tasks", "sample", "notes", "cron", "finishing")
    generation_receipts.refresh(ctx, next_task)
    assert not writes
    entries["new"] = {"learner": "sample", "attempts": [{"state": "generated", "sha256": "d" * 64}]}
    generation_receipts.refresh(ctx, next_task)
    assert writes == paths
    assert safefs.walk_files(repo, "docs/evidence/image-generation") == sorted(paths + [legacy])
    assert safefs.read_bytes(repo, legacy) == old
    assert safefs.read_json(repo, paths[0])["outputs"] == ["a" * 64, "b" * 64, "d" * 64]


def test_approved_request_fetch_status_and_repair_queue(repo, tmp_path):
    value = granted(repo)
    assert status._permissions(repo) == {"figure_requests": [], "approved_figure_requests": [value]}
    task = phase.create(tmp_path / "tasks", "sample", "notes", "interactive", "prepared")
    task.update(ranges=[[0, 0]], packages=[], pages=[])
    assert fetch.fetch_json(task, 1, grade=9, repo=repo)["approved_figure_requests"] == [value]
    task.update(mode="repair", repair_targets=[{"page": "wiki/proba/masodik.md", "kind": "topic", "sources": [], "related": [TOPIC]}])
    assert fetch.fetch_json(task, 1, grade=9, repo=repo)["approved_figure_requests"] == []
    task.update(repair_targets=[{"page": TOPIC, "kind": "topic", "sources": [], "related": []}])
    assert fetch.fetch_json(task, 1, grade=9, repo=repo)["approved_figure_requests"] == [value]
    first = queue.build(repo)
    for item in first["items"]:
        item["status"] = "done"
    rebuilt = queue.build(repo, first)
    assert [i["page"] for i in rebuilt["items"] if i["status"] == "pending"] == [TOPIC]
    assert queue.next_item(rebuilt)["page"] == TOPIC
    assert queue.build(repo, rebuilt) == rebuilt


def test_invalid_owner_license_stops_before_check_budget_and_status_survives(learning_run):
    ctx, task = learning_run
    safefs.write_json(ctx.notes_path, licenses.PATH, [{"on": "2026-02-30"}])
    with pytest.raises(NeedsOwner, match="invalid image permission"):
        handlers.build(ctx, task.dir).check()
    assert not phase.load(task.dir).get("writer_check")
    data = status.summary(ctx)
    assert "docs/licenses.json" in status.render(data)
    assert data["license_error"]


@pytest.mark.parametrize("inherited", [False, True])
def test_banner_error_routes_to_changed_topic_and_reads_old_dependencies(repo, tmp_path, monkeypatch, inherited):
    safefs.write_text(repo, NOTE, frontmatter.set_keys(safefs.read_text(repo, NOTE), {"banner_from": "elso.md"}))
    old = safefs.read_text(repo, TOPIC)
    broken = old.replace("../assets/abra.svg", "https://example.test/banner.png")
    if inherited:
        safefs.write_text(repo, TOPIC, broken)
    base = snapshot(repo)
    safefs.write_text(repo, TOPIC, broken + "\nÚj mondat.\n")
    task = phase.create(tmp_path / "tasks", "sample", "notes", "cron", "writing")
    ctx = SimpleNamespace(notes_path=repo)
    monkeypatch.setattr(steps, "llm_snapshot", lambda *a: {TOPIC: "changed"})
    monkeypatch.setattr(steps, "base_reader", lambda *a: base.get)
    if inherited:
        with pytest.raises(NeedsOwner, match="predating"):
            learning.validate(ctx, task)
    else:
        with pytest.raises(steps.CheckFailed) as failure:
            learning.validate(ctx, task)
        assert {i["file"] for i in failure.value.items} == {TOPIC}
        assert NOTE in failure.value.items[0]["message"]


def test_footnotes_have_separate_counts(learning_run):
    ctx, task = learning_run
    text = safefs.read_text(ctx.notes_path, TOPIC)
    safefs.write_text(ctx.notes_path, TOPIC, text + "\nA 3. dián ez áll.\n\n[^x]: A 3. dián. https://example.test\n")
    items = checks.source_warnings(ctx, task, [TOPIC])
    assert len(items) == 2
    assert task.get("source_ref_counts") == {TOPIC: 1}
    assert task.get("public_footnote_counts") == {TOPIC: 1}
