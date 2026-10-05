"""Fix-47 (the two 2.6.0 reviews): an unchecked change never goes out, a failed check is
rechecked by the next run, a held release is visible, a text-less `fixed` reaches the owner,
public-gate refusals in cron are items, and 2.5.1 receipts are reused."""

from types import SimpleNamespace

import pytest

from school_notes2.flows import finish, fix, inspection, operational_report, recheck, steps, unchecked
from school_notes2.review import files
from school_notes2.site import build as site_build
from school_notes2.state import phase, safefs
from school_notes2.state.files import read_json

PAGE = "wiki/m/topic.md"
OLD = "---\ntype: topic\n---\n# Téma\n\nRégi mondat.\n"
NEW = OLD + "\nÚj mondat.\n"


class Worktree:
    """`git show <commit>:<path>` over a fixed table."""

    def __init__(self, table):
        self.table = table

    def run(self, *args, check=True, **kw):
        commit, path = args[1].split(":", 1)
        text = self.table.get((commit, path))
        return SimpleNamespace(returncode=0 if text is not None else 128, stdout=(text or "").encode())


@pytest.fixture
def held(tmp_path, log, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    safefs.write_text(repo, PAGE, NEW)
    wt = Worktree({("b1", PAGE): OLD, ("b2", PAGE): NEW})
    ctx = SimpleNamespace(notes_path=repo, name="benedek", log=log, worktree=lambda _: wt, mailer=None,
                          cfg=SimpleNamespace(state_dir=tmp_path / "state"), student=SimpleNamespace(publish=True))
    incidents = []
    monkeypatch.setattr("school_notes2.notify.incidents.record",
                        lambda ctx, kind, step, **kw: incidents.append((kind, step, kw.get("scope"))))
    monkeypatch.setattr("school_notes2.notify.incidents.resolve", lambda ctx, scope: incidents.append(("resolved", scope)))
    def prepare(repo, view, unit, folder, old, **kw):
        folder.mkdir(parents=True, exist_ok=True)
        safefs.write_text(folder, "old.txt", old(PAGE))
    monkeypatch.setattr(recheck.inputs, "prepare", prepare)
    monkeypatch.setattr(inspection, "role", lambda *a: None)
    monkeypatch.setattr(recheck.runtime, "role", lambda *a: None)
    return ctx, incidents


def task_for(tmp_path, base, run_id_dir="t"):
    task = phase.create(tmp_path / "tasks" / run_id_dir, "benedek", "notes", "cron", "inspecting")
    task.update(mode="fix", base=base)
    return task


def test_failed_recheck_holds_the_release_and_the_next_run_rechecks_against_its_base(tmp_path, held, monkeypatch):
    """Futás-review 3: a failed P5 call is not "unchanged": the page is carried with its base,
    the release is held (one owner mail), the next run rechecks it and the hold ends."""
    ctx, incidents = held
    task = task_for(tmp_path, "b1", "one")
    monkeypatch.setattr(recheck.steps, "base_reader", lambda ctx, task: lambda p: OLD.encode())
    monkeypatch.setattr(recheck.calls, "run", lambda *a, **kw: {"status": "not_checked", "reason": "timeout"})
    entry = recheck.check_page(ctx, task, tmp_path / "view", PAGE, [])
    assert entry["status"] == "not_checked" and entry["base"] == "b1"
    inspection._carry_unchecked(ctx, task, {"recheck": [entry]})
    assert unchecked.load(ctx)[PAGE]["base"] == "b1" and unchecked.load(ctx)[PAGE]["tries"] == 1
    inspection._carry_unchecked(ctx, task, {"recheck": [entry]})  # a replayed step counts once
    assert unchecked.load(ctx)[PAGE]["tries"] == 1
    record = finish._build(ctx, task, "c1")
    assert record == {"commit": "c1", "held": True, "reason": "unchecked"}
    assert read_json(ctx.cfg.state_dir / "benedek" / "publish-held.json") == {"source": "c1", "reason": "unchecked"}
    assert [i for i in incidents if i[0] != "resolved"] == [("publish_held", "unchecked", "publish-held")]
    assert unchecked.startable(ctx)  # the next hour starts a run for it

    # The next run: its own base already holds the change; the carried base (b1) is used.
    task2 = task_for(tmp_path, "b2", "two")
    monkeypatch.setattr(recheck.steps, "base_reader", lambda ctx, task: lambda p: NEW.encode())
    monkeypatch.setattr(recheck.steps, "llm_snapshot", lambda *a: {})
    monkeypatch.setattr(recheck.calls, "run", lambda *a, **kw: {"status": "reviewed", "model": "m",
                                                                 "review": {"items": [], "owner_notes": []}})
    entries = recheck.run(ctx, task2, tmp_path / "view2")
    assert [e["status"] for e in entries] == ["reviewed"] and entries[0]["base"] == "b1"
    folder = recheck.runtime.folder(task2) / "recheck" / recheck.units.slug(PAGE) / "in"
    assert safefs.read_text(folder, "old.txt") == OLD
    inspection._carry_unchecked(ctx, task2, {"recheck": entries})
    assert unchecked.load(ctx) == {}
    built = []
    monkeypatch.setattr(finish.site_publish, "fetch_gh_pages", lambda *a, **kw: None)
    monkeypatch.setattr(finish.site_publish, "changed_since_publish", lambda *a: None)
    monkeypatch.setattr(finish, "renderer", lambda ctx: None)
    monkeypatch.setattr(finish.site_build, "build", lambda *a, **kw: built.append(1) or SimpleNamespace(
        commit="c2", output=tmp_path / "out", duration_s=1.0))
    ctx.bare = lambda: None
    ctx.cfg.timeouts = SimpleNamespace(fetch_s=1, ls_remote_s=1)
    assert not finish._build(ctx, task2, "c2").get("held") and built == [1]


def test_unchanged_page_is_not_a_failed_check(tmp_path, held, monkeypatch):
    ctx, _ = held
    safefs.write_text(ctx.notes_path, PAGE, OLD)
    task = task_for(tmp_path, "b1")
    monkeypatch.setattr(recheck.steps, "base_reader", lambda ctx, task: lambda p: OLD.encode())
    monkeypatch.setattr(recheck.calls, "run", lambda *a, **kw: pytest.fail("nothing to check"))
    entry = recheck.check_page(ctx, task, tmp_path / "view", PAGE, [])
    assert entry["status"] == "unchanged"
    inspection._carry_unchecked(ctx, task, {"recheck": [entry]})
    assert unchecked.load(ctx) == {}


def test_failed_reader_call_carries_its_pages(tmp_path, held, monkeypatch):
    """The same for P3: an unread page holds the release until a recheck ran."""
    ctx, _ = held
    task = task_for(tmp_path, "b1")
    task.update(mode=None)
    monkeypatch.setattr(inspection.calls, "run", lambda *a, **kw: {"status": "not_checked", "reason": "format"})
    monkeypatch.setattr(inspection.inputs, "prepare", lambda *a, **kw: {})
    result = inspection._reader(ctx, task, tmp_path / "view", {"topic": "m", "pages": [PAGE], "keys": {PAGE: "k"}})
    assert result["unread"] == [PAGE] and "visszatartva" in result["notes"][0]
    inspection._carry_unchecked(ctx, task, {"unread": result["unread"], "pages": []})
    assert unchecked.load(ctx)[PAGE]["base"] == "b1"


def test_carried_pages_stop_starting_runs_after_three_failures(tmp_path, held):
    ctx, _ = held
    for n in range(unchecked.LIMIT):
        unchecked.update(ctx, task_for(tmp_path, "b1", f"r{n}"), {PAGE: "b1"}, set())
    assert unchecked.load(ctx)[PAGE]["tries"] == unchecked.LIMIT and not unchecked.startable(ctx)


def test_fix_run_starts_for_carried_pages_alone(tmp_path, held, monkeypatch):
    ctx, _ = held
    unchecked.update(ctx, task_for(tmp_path, "b1"), {PAGE: "b1"}, set())
    wt = SimpleNamespace(run=lambda *a, **kw: None)
    ctx.worktree = lambda _: wt
    ctx.bare = lambda: None
    ctx.task_root = lambda: tmp_path / "root"
    ctx.cfg.timeouts = SimpleNamespace(fetch_s=1)
    ctx.cfg.limits = SimpleNamespace(max_agents=3)
    monkeypatch.setattr(fix.repos, "fetch", lambda *a: None)
    monkeypatch.setattr(fix.repos, "rev", lambda *a: "main")
    monkeypatch.setattr(fix.files, "open_items", lambda *a: [])
    monkeypatch.setattr(fix.pending, "load", lambda *a: [])
    monkeypatch.setattr(fix.correction_figures, "assignable", lambda *a: [])
    monkeypatch.setattr(fix.fix_progress, "available", lambda ctx, items, waiting: (items, waiting))
    monkeypatch.setattr(fix.fix_progress, "runnable_images", lambda ctx, waiting: waiting)
    task = fix.next_task(ctx)
    assert task is not None and task.get("mode") == "fix" and task.get("fix_work") == []


def test_legacy_reader_receipt_is_used_not_read_again(tmp_path, held, monkeypatch):
    """Futás-review minor: a 2.5.1 `p3.json` of the attempt is applied as it is."""
    ctx, _ = held
    task = task_for(tmp_path, "b1")
    task.update(mode=None)
    root = inspection.folder(task)
    legacy = {"findings": [{"file": PAGE, "problem": "P"}], "notes": ["N"], "pages": [], "receipts": {},
              "coverage": [], "fixes": []}
    safefs.write_json(root, "p3.json", legacy)
    applied = []
    monkeypatch.setattr(inspection, "inspect_readers", lambda *a: pytest.fail("P3 read again"))
    monkeypatch.setattr(inspection.inputs, "preview", lambda *a: pytest.fail("no new view"))
    monkeypatch.setattr(inspection, "_apply", lambda ctx, task, saved: applied.append(saved))
    inspection.inspect(ctx, task)
    assert applied[0]["findings"] == legacy["findings"] and applied[0]["notes"] == ["N"]
    # A 2.5.1 fix-run receipt holds rechecks in the old format: it is not reused.
    assert inspection.legacy_receipt(root) is not None
    safefs.write_json(root, "p3.json", {**legacy, "fixes": [{"unit": {}}]})
    assert inspection.legacy_receipt(root) is None


def test_build_problem_without_an_item_tells_the_owner_once(tmp_path, held, monkeypatch):
    """Futás-review 5: G5 holds; without a wiki item nothing would lift it, so one mail."""
    ctx, incidents = held
    task = task_for(tmp_path, "b1")
    ctx.bare = lambda: None
    ctx.cfg.timeouts = SimpleNamespace(fetch_s=1, ls_remote_s=1)
    monkeypatch.setattr(finish.site_publish, "fetch_gh_pages", lambda *a, **kw: None)
    monkeypatch.setattr(finish.site_publish, "changed_since_publish", lambda *a: None)
    monkeypatch.setattr(finish, "renderer", lambda ctx: None)
    monkeypatch.setattr("school_notes2.flows.machine_findings.record", lambda *a: None)
    for problems, mailed in (([{"file": "publication/public.json", "line": None, "message": "search failed"}], True),
                             ([{"file": PAGE, "line": None, "message": "public build: overflow"}], False)):
        incidents.clear()
        def fail(*a, **kw):
            raise site_build.BuildContentError(problems)
        monkeypatch.setattr(finish.site_build, "build", fail)
        assert finish._build(ctx, task, "c1") == {"commit": "c1", "held": True, "reason": "build"}
        assert bool(incidents) is mailed
    task.set_phase("done")
    task.update(build={"commit": "c1", "held": True})
    assert operational_report.state_text("done", task) == "kész, kiadás visszatartva"


def test_all_failed_calls_without_a_commit_are_not_called_done(tmp_path):
    task = phase.create(tmp_path, "b", "notes", "cron", "done")
    task.update(no_change=True, calls=[{}, {}], failed_fix_calls=[1, 2])
    assert "nem jártak sikerrel" in operational_report.state_text("done", task)
    task.update(failed_fix_calls=[1])
    assert operational_report.state_text("done", task) == "kész"


def test_fixed_without_a_text_change_counts_as_an_attempt_until_the_owner(tmp_path, monkeypatch):
    """Futás-review R6: no endless 24-hour parking; the third such run makes it an owner item."""
    repo = tmp_path / "repo"
    repo.mkdir()
    safefs.write_text(repo, PAGE, OLD)
    report = files.write_review(repo, "2026-10-05", {"verdict": "changes", "findings": [
        {"severity": "hiba", "id": "R1", "file": PAGE, "problem": "Hiba.", "relates_to": None}]}, "r", "a", "b")
    rel = report.relative_to(repo).as_posix()
    ctx = SimpleNamespace(notes_path=repo, log=SimpleNamespace(event=lambda *a, **kw: None))
    monkeypatch.setattr(steps, "base_reader", lambda ctx, task: lambda p: safefs.read_bytes(repo, p))
    listed = [{"file": rel, "item_id": "R1"}]
    fetch = {"pages": [], "packages": []}
    for n in range(3):
        result, dropped = steps.usable(ctx, None, {"status": "done", "review_closure": [
            {"file": rel, "item_id": "R1", "status": "fixed"}]}, fetch, listed)
        assert result["review_closure"][0]["status"] == "open" and dropped
        outcome = files.apply_closure(repo, f"run-{n}", result["review_closure"], listed, automatic=True)
    items = files.read_items(repo, report)
    assert items["R1"] == "owner" and outcome.new_owner == [{"file": rel, "item_id": "R1"}]


def test_catch_up_never_releases_an_unchecked_change(tmp_path, held, monkeypatch):
    """The hourly catch-up holds too, and lifts only an `unchecked` hold of the same commit."""
    from school_notes2.flows import publish
    from school_notes2.notify import incidents
    ctx, _ = held
    ctx.bare = lambda: None
    ctx.worktree = lambda _: None
    ctx.cfg.timeouts = SimpleNamespace(fetch_s=1, ls_remote_s=1)
    monkeypatch.setattr(publish, "with_retries", lambda *a, **kw: None)
    monkeypatch.setattr(publish.site_publish, "fetch_gh_pages", lambda *a, **kw: None)
    monkeypatch.setattr(publish.repos, "rev", lambda *a: "c1")
    needed = []
    monkeypatch.setattr(publish.site_publish, "publish_needed", lambda *a: needed.append(1) or (False, "up to date"))
    unchecked.update(ctx, task_for(tmp_path, "b1"), {PAGE: "b1"}, set())
    publish.hold(ctx, "c1", "unchecked")
    assert publish._start(ctx) is None and needed == []
    unchecked.update(ctx, task_for(tmp_path, "b1", "two"), {}, {PAGE})
    assert publish._start(ctx) is None and needed == [1]  # the same commit may go out now
    publish.hold(ctx, "c1", "build")
    assert publish._start(ctx) is None and needed == [1]  # a failed build waits for a new commit
    assert incidents.wording("benedek", "publish_held", "unchecked").startswith("a kiadás visszatartva: ")
