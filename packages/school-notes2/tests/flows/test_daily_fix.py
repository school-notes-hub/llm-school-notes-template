"""Daily fix admission and prepared checkpoint; the existing review chain owns P2/P6."""

from types import SimpleNamespace

import pytest

from school_notes2.flows import fetch, fix, run, review_phases
from school_notes2.review import files
from school_notes2.state import phase, safefs
from tests.flows.test_repair import context


@pytest.mark.parametrize("learner", ["one", "two"])
def test_daily_fix_prepare_crash_and_subject_assignments(tmp_path, log, monkeypatch, learner):
    ctx, page, _ = context(tmp_path, log, monkeypatch)
    ctx.name = learner
    wt = ctx.worktree("notes")
    original_run = wt.run
    wt.run = lambda *a, **kw: None if a[0] == "switch" else original_run(*a, **kw)
    ctx.worktree = lambda kind: wt
    ctx.bare = lambda: wt
    ctx.cfg.limits = SimpleNamespace(max_agents=3, review_closures_per_run=20, fix_runs_per_day=6)
    ctx.cfg.timeouts = SimpleNamespace(fetch_s=1)
    monkeypatch.setattr(fix.repos, "fetch", lambda *a: None)
    files.write_review(ctx.notes_path, "2026-10-04", {"verdict": "changes", "findings": [
        {"id": "R1", "file": page, "problem": "Hiba.", "relates_to": None}]}, "fake", "a", "b")
    task = fix.next_task(ctx)
    assert task.get("mode") == "fix"
    original = task.set_phase
    monkeypatch.setattr(task, "set_phase", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        fix.prepare(ctx, task)
    resumed = phase.load(task.dir)
    fix.prepare(ctx, resumed)
    value = fetch.fetch_json(resumed, 1, grade=9)
    assert value["mode"] == "fix" and value["packages"] == value["pages"] == []
    assert value["open_review_items"][0]["item_id"] == "R1"
    assert value["subject"] == "m"
    resumed.set_phase("done")
    assert fix.next_task(ctx).get("mode") == "fix"


def test_priority_is_new_packages_then_fix_then_repair(monkeypatch):
    from school_notes2.flows import repair
    ctx, seen = SimpleNamespace(), []
    monkeypatch.setattr(fetch, "drive_client", lambda *a: None)
    monkeypatch.setattr(fetch, "start", lambda *a: None)
    monkeypatch.setattr(fix, "next_task", lambda *a: seen.append("fix") or "fix-task")
    monkeypatch.setattr(repair, "next_task", lambda *a: seen.append("repair"))
    assert run._new_task(ctx) == "fix-task" and seen == ["fix"]
    monkeypatch.setattr(fetch, "start", lambda *a: "new-task")
    assert run._new_task(ctx) == "new-task" and seen == ["fix"]


def test_fix_inspection_goes_directly_to_finalization(tmp_path, monkeypatch):
    task = phase.create(tmp_path, "one", "notes", "cron", "figures")
    task.update(mode="fix")
    seen = []
    monkeypatch.setattr(review_phases.inspection, "prepare", lambda *a: seen.append("figures"))
    monkeypatch.setattr(review_phases.inspection, "inspect", lambda *a: seen.append("inspect"))
    monkeypatch.setattr(review_phases.correction, "all_items", lambda *a: ["finding"])
    monkeypatch.setattr(review_phases, "finalize", lambda *a: seen.append("finalize"))
    monkeypatch.setattr(review_phases.relations, "inventory", lambda *a: {"items": {}})
    review_phases.advance(SimpleNamespace(notes_path=tmp_path), task, lambda *a: None)
    assert task.phase == "finishing" and seen == ["figures", "inspect", "finalize"]


@pytest.mark.parametrize("item_page", ["wiki/s/topic.md", "wiki/assets/a.png"])
def test_fix_allows_unit_and_embedding_but_not_unrelated_page(tmp_path, item_page):
    from school_notes2.flows import correction
    from school_notes2.state.errors import BadWork
    repo, snapshot = tmp_path / "repo", tmp_path / "snapshot"
    repo.mkdir()
    for page, text in {
        "wiki/s/topic.md": "---\ntype: concept\n---\n# A\n\n![A](../assets/a.png)\n",
        "wiki/s/log.md": "---\ntype: lesson-notes\nlessons: [{topics: [topic.md]}]\n---\n# Óra\n",
        "wiki/s/summary.md": "---\ntype: chapter-summary\n---\n# Összefoglaló\n\n[A](topic.md)\n",
        "wiki/s/other.md": "---\ntype: concept\n---\n# Más\n",
    }.items():
        safefs.write_text(repo, page, text)
    safefs.write_bytes(repo, "wiki/assets/a.png", b"image")
    report = files.write_review(repo, "2026-10-04", {"verdict": "changes", "findings": [
        {"id": "R1", "file": item_page, "problem": "Hiba", "relates_to": None}]}, "fake", "a", "b")
    items = [{"file": report.relative_to(repo).as_posix(), "item_id": "R1"}]
    correction.snapshot(repo, snapshot)
    for page in ("topic", "log", "summary"):
        path = f"wiki/s/{page}.md"
        safefs.write_text(repo, path, safefs.read_text(repo, path) + "\nJavítás.\n")
    ctx = SimpleNamespace(notes_path=repo)
    correction.check_scope(ctx, snapshot, items)
    # An edited link must not give the writer more scope.
    safefs.write_text(repo, "wiki/s/summary.md", "---\ntype: chapter-summary\n---\n[Other](other.md)\n")
    safefs.write_text(repo, "wiki/s/other.md", "# Más\n\nVáltozás.\n")
    with pytest.raises(BadWork, match="unassigned page"):
        correction.check_scope(ctx, snapshot, items)


def test_fix_may_edit_the_page_whose_description_an_index_finding_quotes(tmp_path):
    from school_notes2.flows import correction
    from school_notes2.state.errors import BadWork
    repo, snapshot = tmp_path / "repo", tmp_path / "snapshot"
    repo.mkdir()
    description = "Füzetjegyzet egy dátum nélküli óráról, a piacgazdaság jellemzői."
    pages = {
        "wiki/s/index.md": f"---\ntitle: S\n---\n# S\n\n* [Óra](ora.md) - {description}\n",
        "wiki/s/ora.md": f"---\ntype: lesson-notes\ntitle: Óra\ndescription: {description}\n---\n# Óra\n",
        "wiki/s/other.md": "---\ntype: concept\ntitle: Más\ndescription: Egy egészen más oldal hosszú leírása.\n---\n# Más\n",
    }
    for page, text in pages.items():
        safefs.write_text(repo, page, text)
    report = files.write_review(repo, "2026-10-04", {"verdict": "changes", "findings": [
        {"id": "R1", "file": "wiki/s/index.md", "problem": "A leírás metaadattal kezdődik.",
         "quote": f"[Óra](ora.md) - {description}", "relates_to": None}]}, "fake", "a", "b")
    items = [{"file": report.relative_to(repo).as_posix(), "item_id": "R1"}]
    correction.snapshot(repo, snapshot)
    safefs.write_text(repo, "wiki/s/ora.md", pages["wiki/s/ora.md"].replace("Füzetjegyzet egy dátum nélküli óráról, a p", "A p"))
    correction.check_scope(SimpleNamespace(notes_path=repo), snapshot, items)
    safefs.write_text(repo, "wiki/s/other.md", pages["wiki/s/other.md"] + "Változás.\n")
    with pytest.raises(BadWork, match="unassigned page"):
        correction.check_scope(SimpleNamespace(notes_path=repo), snapshot, items)


@pytest.mark.parametrize("learner", ["one", "two"])
def test_legacy_owner_only_starts_fix_and_migrates_before_assignment(tmp_path, log, monkeypatch, learner):
    from school_notes2.wiki import frontmatter
    ctx, page, _ = context(tmp_path, log, monkeypatch)
    ctx.name = learner
    wt = ctx.worktree("notes")
    original = wt.run
    wt.run = lambda *a, **kw: None if a[0] == "switch" else original(*a, **kw)
    ctx.worktree = lambda _: wt
    ctx.bare = lambda: wt
    ctx.cfg.limits = SimpleNamespace(max_agents=3, review_closures_per_run=20, fix_runs_per_day=6)
    ctx.cfg.timeouts = SimpleNamespace(fetch_s=1)
    monkeypatch.setattr(fix.repos, "fetch", lambda *a: None)
    path = files.write_review(ctx.notes_path, "2026-10-04", {"verdict": "changes", "findings": [
        {"id": "R1", "file": page, "problem": "Hiba.", "chain": 1}]}, "r", "a", "b")
    path.write_text(frontmatter.set_keys(path.read_text(), {"items": {"R1": "owner"}, "repair_policy": 0}))
    task = fix.next_task(ctx)
    assert task is not None and task.get("open_review_items") == []
    fix.prepare(ctx, task)
    supplied = fetch.fetch_json(task, 1, grade=9)
    assert supplied["open_review_items"][0]["item_id"] == "R1"
    assert supplied["open_review_items"][0]["chain"] == 1
    assert not task.get("skip_writer")
    assert path.relative_to(ctx.notes_path).as_posix() in task.get("tool_writes")
