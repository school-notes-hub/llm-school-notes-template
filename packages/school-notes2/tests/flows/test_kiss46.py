"""Fix-46 (2.6.0 KISS): finished notes work is never discarded, one counter per writer call,
rules that do not protect the learner are warnings, and every 2.5.x state continues."""

from types import SimpleNamespace

import pytest

from school_notes2.flows import correction_calls, machine_findings, operation, policy, steps
from school_notes2.llm import launch
from school_notes2.review import files
from school_notes2.state import phase, safefs
from school_notes2.state.errors import BadWork, WaitingQuota
from school_notes2.wiki.check import BLOCKING, SECRET_MESSAGE, item
from tests.operations.test_round import cfg  # noqa: F401

PAGE = "wiki/m/topic.md"
TEXT = "---\ntitle: Téma\ntype: topic\n---\n# Téma\n\nRégi mondat.\n"


@pytest.fixture
def call(tmp_path, log):
    repo = tmp_path / "repo"
    repo.mkdir()
    safefs.write_text(repo, PAGE, TEXT)
    report = files.write_review(repo, "2026-10-05", {"verdict": "changes", "findings": [
        {"severity": "hiba", "id": "R1", "file": PAGE, "problem": "Hiba.", "relates_to": None}]}, "r", "a", "b")
    rel = report.relative_to(repo).as_posix()
    task = phase.create(tmp_path / "tasks", "learner", "notes", "cron", "writing")
    task.update(mode="fix", base="base", calls=[{"subject": "m", "open_review_items": [{"file": rel, "item_id": "R1"}],
                                                  "pending_figure_ids": []}], ranges=[[0, 0]])
    ctx = SimpleNamespace(notes_path=repo, log=log)
    return ctx, task, rel


def edit(ctx, text="Új, kész mondat."):
    safefs.write_text(ctx.notes_path, PAGE, TEXT + text + "\n")


def run_call(ctx, task, invoke, recover=lambda: None):
    return correction_calls.run(ctx, task, 1, invoke, recover)


def test_check_failure_keeps_the_work_continues_once_then_becomes_an_item(call):
    """Point 1: the writer continues on its own files with the error list; what is still
    wrong after that is an item for the next run, and the finished text stays."""
    ctx, task, rel = call
    seen = []
    def invoke():
        seen.append(safefs.read_json(ctx.notes_path, ".school-notes/check.json"))
        edit(ctx)
        safefs.write_json(task.dir / "call-1", "candidate.json", {"status": "done", "review_closure": [
            {"file": rel, "item_id": "R1", "status": "fixed"}]})
        raise steps.CheckFailed([item(PAGE, 8, "link target does not exist: 'x.md'")])
    result = run_call(ctx, task, invoke)
    assert len(seen) == 2 and seen[1][0]["message"] == "link target does not exist: 'x.md'"
    assert "Új, kész mondat." in safefs.read_text(ctx.notes_path, PAGE)  # kept, not rolled back
    assert result["review_closure"][0]["status"] == "fixed"
    report = phase.load(task.dir).get("inspection_report")
    assert "x.md" in safefs.read_text(ctx.notes_path, report)  # an item for the next run


def test_unusable_output_is_undone_only_at_the_last_attempt(call):
    ctx, task, rel = call
    attempts = []
    def invoke():
        attempts.append(safefs.read_text(ctx.notes_path, PAGE))
        edit(ctx, "ghp_" + "a" * 36)
        raise steps.CheckFailed([item(PAGE, 8, f"{SECRET_MESSAGE} 'ghp_'", kind=BLOCKING)])
    result = run_call(ctx, task, invoke)
    assert "ghp_" in attempts[1]  # The writer's second attempt sees its own files.
    assert safefs.read_text(ctx.notes_path, PAGE) == TEXT  # Unusable: only this call is undone.
    assert result["review_closure"] == [{"file": rel, "item_id": "R1", "status": "open",
                                         "note": "A hívás kétszer sikertelen volt; a tétel nyitva maradt."}]


def test_blocking_error_fixed_in_the_continuation_keeps_everything(call):
    ctx, task, rel = call
    attempts = []
    def invoke():
        attempts.append(1)
        if len(attempts) == 1:
            edit(ctx, "ghp_" + "a" * 36)
            raise steps.CheckFailed([item(PAGE, 8, f"{SECRET_MESSAGE} 'ghp_'", kind=BLOCKING)])
        edit(ctx)
        return {"status": "done"}
    assert run_call(ctx, task, invoke) == {"status": "done"}
    assert "Új, kész mondat." in safefs.read_text(ctx.notes_path, PAGE)


@pytest.mark.parametrize("valid", [True, False])
def test_invalid_output_retries_once_and_keeps_other_work(call, valid):
    ctx, task, rel = call
    attempts = []
    def invoke():
        attempts.append(1)
        edit(ctx)
        safefs.write_text(ctx.notes_path, ".school-notes/result.json", '{"status": "done"}' if valid else "nem json")
        raise BadWork("schema")
    result = run_call(ctx, task, invoke)
    assert len(attempts) == 2 and result["review_closure"][0]["status"] == "open"
    # A valid result.json was not unusable output: the call's files stay.
    assert ("Új, kész mondat." in safefs.read_text(ctx.notes_path, PAGE)) is valid


def test_timeout_leaves_items_open_and_the_run_goes_on(call):
    ctx, task, rel = call
    def invoke():
        edit(ctx)
        raise launch.TimedOut("timeout", details={"count": 1})
    result = run_call(ctx, task, invoke)
    assert result["review_closure"][0]["status"] == "open"
    assert "Új, kész mondat." in safefs.read_text(ctx.notes_path, PAGE)
    def suspended():
        raise launch.TimedOut("timeout", details={"count": 2})
    task2 = phase.create(task.dir.parent, "learner", "notes", "cron", "writing")
    task2.update(**task.data["data"])
    with pytest.raises(launch.TimedOut):  # The two-timeout brake stays (Maradjon).
        correction_calls.run(ctx, task2, 1, suspended, lambda: None)


def test_quota_wait_is_not_a_failure(call):
    ctx, task, rel = call
    def wait():
        raise WaitingQuota("weekly")
    with pytest.raises(WaitingQuota):
        run_call(ctx, task, wait)
    assert safefs.read_json(task.dir / "call-1", "call.json")["failures"] == 0
    assert run_call(ctx, task, lambda: {"status": "done"}) == {"status": "done"}


@pytest.mark.parametrize("legacy", [False, True])
def test_interrupted_call_reuses_its_valid_output(call, legacy):
    """Point 7: also a 2.5.x call interrupted with only its old crash counter."""
    ctx, task, rel = call
    correction_calls.snapshot(ctx.notes_path, task.dir / "call-1")
    if legacy:
        task.update(fix_calls={"1": 1})
    else:
        safefs.write_json(task.dir / "call-1", "call.json", {"failures": 0, "running": True, "items": []})
    output = {"status": "done", "review_closure": [{"file": rel, "item_id": "R1", "status": "fixed"}]}
    result = run_call(ctx, task, lambda: pytest.fail("no second writer"), lambda: output)
    assert result == output


def test_question_in_a_fix_call_leaves_items_open(call):
    ctx, task, rel = call
    result = run_call(ctx, task, lambda: {"status": "question", "questions": [{"text": "?"}]})
    assert result["status"] == "done" and result["review_closure"][0]["status"] == "open"


def test_package_call_failing_twice_stops_for_the_owner_with_files_kept(call):
    ctx, task, rel = call
    task.update(mode=None)
    def invoke():
        edit(ctx)
        safefs.write_text(ctx.notes_path, ".school-notes/result.json", '{"status": "done"}')
        raise BadWork("call failed after a valid result")
    from school_notes2.state.errors import NeedsOwner
    with pytest.raises(NeedsOwner):
        run_call(ctx, task, invoke)
    assert "Új, kész mondat." in safefs.read_text(ctx.notes_path, PAGE)
    assert safefs.read_json(task.dir / "call-1", "call.json")["failures"] == 0  # A continue starts afresh.


@pytest.mark.parametrize("error", [RuntimeError("tool bug"), BadWork("bad result")])
@pytest.mark.parametrize("mode", ["fix", "repair"])
def test_program_error_or_bad_work_never_discards_the_tree(cfg, monkeypatch, error, mode):
    """Opus #2, Fable 1: the tree and the task stay; a program stop waits for a new release."""
    from school_notes2.flows import context, run
    from school_notes2.git import discard
    ctx = context.make(cfg, "first", console=False)
    monkeypatch.setattr(discard, "discard", lambda *a: pytest.fail("work discarded"))
    version = ["2.6.0"]
    monkeypatch.setattr(ctx.__class__, "release", lambda _: version[0])
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "writing")
    task.update(mode=mode)
    with operation.scope(ctx):
        policy.on_error(error, task=task, student=ctx.name, step="run", log=ctx.log, mailer=None)
    task = phase.load(task.dir)
    assert task.phase == "writing" and task.data["needs_owner"] and not task.get("set_aside")
    assert not run._may_run(ctx, task)
    version[0] = "2.6.1"
    assert run._may_run(ctx, task) == (isinstance(error, RuntimeError))


def test_machine_findings_are_recorded_before_each_write(call, monkeypatch):
    """The tool records its own report write first, so no restore can ever undo it."""
    ctx, task, rel = call
    seen = []
    original = safefs.write_text
    def spy(root, path, text, *a, **kw):
        if str(path).startswith("docs/review/") and root == ctx.notes_path:
            seen.append(path in phase.load(task.dir).get("tool_writes", {}))
        return original(root, path, text, *a, **kw)
    monkeypatch.setattr(safefs, "write_text", spy)
    machine_findings.record(ctx, task, [item(PAGE, 7, "unbalanced $$ display-math delimiter")])
    assert seen and all(seen)
