"""Fix-48 (the javítás-47 review): closures a 2.5.x correction round applied are not applied
again; a writer question in an isolated fix call reaches the owner once and stops the calls;
a held release names the pushed commit; the short status shows a task's newer error."""

from types import SimpleNamespace

import pytest

from school_notes2.flows import correction_calls, review_phases, run as run_flow, status_text, steps
from school_notes2.notify import Notice, mailed
from school_notes2.review import files, relations
from school_notes2.state import phase, safefs

PAGE = "wiki/m/topic.md"
OLD = "---\ntype: topic\n---\n# Téma\n\nRégi mondat.\n"
RUN = "20261005-212528-7b15"


def report(repo, ids=("R1", "R2", "R3")):
    path = files.write_review(repo, "2026-10-05", {"verdict": "changes", "findings": [
        {"severity": "hiba", "id": i, "file": PAGE, "problem": f"Hiba {i}.", "relates_to": None} for i in ids]},
        "r", "a", "b")
    return path.relative_to(repo).as_posix()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    safefs.write_text(repo, PAGE, OLD + "\nÚj mondat.\n")
    monkeypatch.setattr(steps, "base_reader", lambda ctx, task: lambda p: OLD.encode())
    return repo


def ctx_for(repo, events=None):
    record = (lambda *a, **kw: events.append((a, kw))) if events is not None else (lambda *a, **kw: None)
    return SimpleNamespace(notes_path=repo, log=SimpleNamespace(event=record))


def closures(rel, *ids, status="fixed"):
    return [{"file": rel, "item_id": i, "status": status} for i in ids]


def test_legacy_round_closures_are_left_out_and_count_no_new_attempt(repo, tmp_path):
    """Review 1–2: the 2.5.1 rounds applied R1–R3 under `-fix-a1-rN`; P5 reopened R2. The
    2.6.0 content steps neither fail on the closed items nor re-close or recount R2."""
    rel = report(repo)
    listed = [{"file": rel, "item_id": i} for i in ("R1", "R2", "R3")]
    first = closures(rel, "R1", "R2", "R3")
    files.apply_closure(repo, RUN + "-fix-a1-r1", first, listed, automatic=True)
    from school_notes2.reader import report as run_report
    run_report.reopen(repo, rel + "#R2", "A magyarázat hiányos.")
    files.apply_closure(repo, RUN + "-fix-a1-r2", closures(rel, "R2", status="open"),
                        [{"file": rel, "item_id": "R2"}], automatic=True)
    before = safefs.read_text(repo, rel)
    task = phase.create(tmp_path / "tasks", "benedek", "notes", "cron", "correcting", run_id=RUN)
    task.update(mode="fix")
    review_phases.resume_legacy_round(task)
    assert task.phase == "writing" and task.get("closures_applied") and task.get("recheck_all")
    result, dropped = steps.usable(ctx_for(repo), task, {"status": "done", "review_closure": first},
                                   {"pages": [], "packages": []}, listed)
    # R1 and R3 are decided; R2 (reopened, still open) keeps its claim for the one P5 pass.
    assert [c["item_id"] for c in result["review_closure"]] == ["R2"]
    assert [d.split("#")[1] for d in dropped] == ["R1: already fixed; left as is", "R3: already fixed; left as is"]
    assert safefs.read_text(repo, rel) == before  # the closure step applies nothing again
    items = relations.inventory(repo)["items"]
    assert items[rel + "#R2"]["status"] == "open"
    assert items[rel + "#R2"]["repair_runs"] == [RUN + "-fix-a1-r1"]
    assert items[rel + "#R2"]["repair_attempts"] == 1


def test_a_repeated_finish_of_the_same_run_keeps_its_own_closures(repo, tmp_path):
    """The `already closed` rule reads the items before this run's own section: a rerun of
    the content steps replaces the section instead of dropping the run's closures."""
    rel = report(repo, ("R1",))
    listed = [{"file": rel, "item_id": "R1"}]
    task = phase.create(tmp_path / "tasks", "benedek", "notes", "cron", "writing", run_id=RUN)
    for _ in range(2):
        result, dropped = steps.usable(ctx_for(repo), task, {"status": "done", "review_closure": closures(rel, "R1")},
                                       {"pages": [], "packages": []}, listed)
        assert result["review_closure"] == closures(rel, "R1") and not dropped
        files.apply_closure(repo, RUN, result["review_closure"], listed, automatic=True)
    text = safefs.read_text(repo, rel)
    assert text.count(f"## Végrehajtva ({RUN})") == 1
    assert files.read_items(repo, repo / rel) == {"R1": "fixed"}


def asked_task(tmp_path, rel):
    task = phase.create(tmp_path / "tasks", "benedek", "notes", "cron", "writing", run_id=RUN)
    task.update(mode="fix", calls=[{"subject": "m", "packages": [], "seqs": [], "pending_images": [],
                                    "open_review_items": [{"file": rel, "item_id": "R1"},
                                                          {"file": rel, "item_id": "R2"}]}])
    return task


def test_isolated_writer_question_goes_to_the_owner_once_and_stops_the_calls(repo, tmp_path, monkeypatch):
    """Review 3: the question is kept at the items, they become owner items (no further call),
    one mail goes out for the run and the status shows the question."""
    rel = report(repo, ("R1", "R2", "R3"))
    task = asked_task(tmp_path, rel)
    question = {"status": "question", "questions": [{"text": "Melyik  ábrablokkot\nhelyezzem át?"}]}
    result = correction_calls.run(ctx_for(repo), task, 1, lambda: question, lambda: None)
    assert result["status"] == "done" and task.get("failed_fix_calls") == [1]
    assert {c["status"] for c in result["review_closure"]} == {"open"}
    assert task.get("asked_items") == {rel + "#R1": "Melyik ábrablokkot helyezzem át?",
                                       rel + "#R2": "Melyik ábrablokkot helyezzem át?"}
    listed = task.get("calls")[0]["open_review_items"]
    kept, _ = steps.usable(ctx_for(repo), task, result, {"pages": [], "packages": []}, listed)
    outcome = files.apply_closure(repo, task.run_id, steps.with_questions(task, kept)["review_closure"], listed,
                                  automatic=True)
    assert outcome.new_owner == [{"file": rel, "item_id": "R1", "question": True},
                                 {"file": rel, "item_id": "R2", "question": True}]
    assert files.read_items(repo, repo / rel) == {"R1": "owner", "R2": "owner", "R3": "open"}
    items = relations.inventory(repo)["items"]
    assert items[rel + "#R1"]["owner_question"] == "Melyik ábrablokkot helyezzem át?"
    assert "repair_attempts" not in items[rel + "#R1"]           # a question is not an attempt
    assert [i["item_id"] for i in files.open_items(repo, "cron")] == ["R3"]  # no further call
    # One mail for the run's question; the item notices stay in the status.
    sent = []
    monkeypatch.setattr(run_flow.owner_notices, "send", lambda ctx, notice: sent.append(notice) or True)
    ctx = SimpleNamespace(name="benedek")
    assert run_flow.owner_items(ctx, task, outcome.new_owner)
    assert run_flow.owner_items(ctx, task, outcome.new_owner)  # a rerun: the outbox key is the same
    mails = [n for n in sent if mailed(n)]
    assert {n.kind for n in mails} == {f"owner-question:{RUN}"}
    assert "2 javítandó review-tételnél" in mails[0].message and "Melyik" not in mails[0].message
    assert not mailed(Notice("benedek", f"review_owner:{rel}:R1", RUN, "finish", "owner", "x", ""))
    assert status_text.questions(SimpleNamespace(notes_path=repo)) == [
        ([f"{rel.rsplit('/', 1)[1]}#R1", f"{rel.rsplit('/', 1)[1]}#R2"], "Melyik ábrablokkot helyezzem át?")]


def test_question_line_in_the_short_status():
    data = {"name": "benedek", "current": None, "now": __import__("datetime").datetime(2026, 10, 5, 12),
            "held": False, "today": [], "errors": [], "items": 1, "owner_items": 2, "figures": 0, "drive": 0,
            "budget": "–", "questions": [(["x.md#R1", "x.md#R2"], "Melyik ábrát?")]}
    text = status_text.render(data)
    assert "  Tulajdonosi döntésre vár: 2 review-tétel.\n    A jegyzetíró kérdése (x.md#R1, x.md#R2): Melyik ábrát?" in text


def test_short_status_shows_a_task_error_newer_than_its_progress(tmp_path):
    """Review question 4: `last_error` after the last phase step is an open error line."""
    task = phase.create(tmp_path / "tasks", "benedek", "notes", "cron", "writing")
    task.set_phase("writing", writing_k=5)
    assert task.get("progress_at") and status_text.task_error(task) is None
    task.record_error("bad_work", "result-2.json\nis missing")
    error = status_text.task_error(task)
    assert error["message"] == "utolsó hiba (bad_work): result-2.json is missing"
    assert error["run_id"] == task.run_id and error["at"] == task.data["last_error"]["at"]
    task.update(progress_at="2999-01-01T00:00:00+01:00")
    assert status_text.task_error(task) is None          # progress after the error
    task.record_error("transient", "push failed")
    task.mark_needs_owner("x", "y", "program")
    assert status_text.task_error(task) is None          # a stop for the owner has its own line
    legacy = phase.create(tmp_path / "tasks", "benedek", "notes", "cron", "correcting")
    legacy.data["data"].pop("progress_at", None)
    legacy.record_error("bad_work", "result-2.json is missing")
    assert status_text.task_error(legacy)                # a 2.5.x task has no recorded progress


def test_held_release_names_the_amended_commit_without_a_second_mail(tmp_path, monkeypatch):
    """Review 4: the catch-up sees the pushed (amended) commit as held, so it neither
    rebuilds it nor mails again; `_build` alone decided about the mail."""
    from school_notes2.flows import finish, publish
    recorded = []
    monkeypatch.setattr("school_notes2.notify.incidents.record", lambda *a, **kw: recorded.append(a))
    ctx = SimpleNamespace(name="benedek", student=SimpleNamespace(publish=True),
                          cfg=SimpleNamespace(state_dir=tmp_path / "state"))
    publish.hold(ctx, "pre-amend", "build", notify=False)
    finish._held(ctx, {"commit": "amended", "held": True, "reason": "build"})
    from school_notes2.state.files import read_json
    assert read_json(publish._held(ctx)) == {"source": "amended", "reason": "build"}
    assert recorded == []
