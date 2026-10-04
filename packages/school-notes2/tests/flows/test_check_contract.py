"""Check invocation/resume accounting and T-016/T-152 regression coverage."""

from types import SimpleNamespace

import pytest

from school_notes2.flows import checks, finish, handlers, policy, steps, writer
from school_notes2.git import finish as git_finish
from school_notes2.state import phase, safefs
from school_notes2.state.errors import SnError
from school_notes2.wiki.check import item
from tests.flows.test_learning_checks import learning_run, TOPIC


def test_response_errors_first_counts_and_complete_file(learning_run, monkeypatch):
    ctx, task = learning_run
    entries = [item(f"wiki/{n}.md", n, "warning", "warning") for n in range(60)]
    entries += [item("wiki/z.md", 99, "last file's error")]
    monkeypatch.setattr(steps, "check_items", lambda *a: entries)
    answer = handlers.check(ctx, task)
    assert answer["errors"] == 1 and answer["warnings"] == 60 and answer["truncated"]
    assert len(answer["problems"]) == 50 and answer["problems"][0]["severity"] == "error"
    full = safefs.read_json(ctx.notes_path, answer["full_list"])
    assert len(full) == 61
    assert len(task.get("writer_check")["warnings"]) == 60
    assert len(checks.accounting(task, {"status": "done"})) == 60


def test_three_checks_across_reload_and_failed_check(learning_run, monkeypatch):
    ctx, task = learning_run
    checks.begin(task)
    handlers.check(ctx, task)
    task = phase.load(task.dir)
    def crash(*args):
        raise RuntimeError("interrupted check")
    with monkeypatch.context() as m:
        m.setattr(steps, "guard_step", crash)
        with pytest.raises(RuntimeError):
            handlers.check(ctx, task)
    task = phase.load(task.dir)
    handlers.check(ctx, task)
    with monkeypatch.context() as m:
        m.setattr(steps, "guard_step", crash)
        assert handlers.check(ctx, phase.load(task.dir)) == checks.LIMIT
    # fetch input refresh is not a new invocation.
    writer.write_inputs(ctx, task, 1)
    assert handlers.check(ctx, phase.load(task.dir)) == checks.LIMIT
    checks.begin(task)
    assert "limit_reached" not in handlers.check(ctx, task)


def test_last_own_check_decisions_and_unhandled_later_warnings(learning_run):
    ctx, task = learning_run
    path = ctx.notes_path / TOPIC
    path.write_text(path.read_text() + "\nA 2. dia.\n")
    own = handlers.check(ctx, task)["problems"]
    warning = next(i for i in own if i.get("kind") == "source_ref")
    result = {"status": "done", "warnings": [{"id": warning["id"], "action": "rewritten", "reason": "Érthetőbb."}]}
    assert not checks.accounting(task, result)
    path.write_text(path.read_text().replace("A 2. dia.", "A 3. dia."))
    later = checks.after_writer(ctx, task, result, steps.check_items(ctx, task))
    assert len(later) == 1 and later[0]["unhandled"]
    # A later tool check does not replace the writer's obligations.
    assert checks.accounting(task, {"warnings": []})
    assert not checks.accounting(task, result)
    task.reload()
    assert task.get("check_warnings") == later


def test_tool_hash_not_path_or_machine_parts_determines_blame(learning_run):
    ctx, task = learning_run
    path = ctx.notes_path / TOPIC
    steps.record_tool_files(task, ctx.notes_path, [TOPIC])
    error = item(TOPIC, 1, "broken output")
    with pytest.raises(SnError) as caught:
        checks.tool_errors(ctx, task, [error])
    policy.on_error(caught.value, task=task, student=ctx.name, step="check", log=ctx.log, mailer=None)
    assert task.data["llm_failures"] == 0 and task.data["needs_owner"]["class"] == "program"
    path.write_text(path.read_text() + "\nWriter modification.\n")
    checks.tool_errors(ctx, task, [error])
    checks.tool_errors(ctx, task, [item("docs/tool-looking.json", None, "not actually tool-written")])
    checks.tool_errors(ctx, task, [{**error, "severity": "warning"}])


def test_g5_build_failure_twice_and_success_reset(learning_run, monkeypatch):
    ctx, task = learning_run
    task.data["mode"] = "cron"
    monkeypatch.setattr(steps, "content_steps", lambda *a: steps.Prepared({"status": "done"}, False))
    monkeypatch.setattr(finish, "_snapshot", lambda *a: {})
    monkeypatch.setattr(git_finish, "own_commit", lambda *a: "commit")
    def build(commit):
        raise steps.CheckFailed([item(TOPIC, 1, "only build detects this")])
    def run(task_, wt, hooks, *args):
        git_finish.g5_build(task_, wt, SimpleNamespace(build=build))
    monkeypatch.setattr(git_finish, "run", run)
    for n in (1, 2):
        task.set_phase("writing")
        with pytest.raises(steps.CheckFailed) as caught:
            finish.finish(ctx, task, notify_owner_items=lambda _: None)
        policy.on_error(caught.value, task=task, student=ctx.name, step="finish", log=ctx.log, mailer=None)
        task = phase.load(task.dir)
        assert task.data["llm_failures"] == n
    assert task.data["needs_owner"]
    git_finish.g5_build(task, None, SimpleNamespace(build=lambda c: {"commit": c}))
    resumed = phase.load(task.dir)
    assert resumed.phase == "built" and resumed.data["llm_failures"] == 0


def test_interactive_fetch_new_task_does_not_reset_invocation_budget(learning_run):
    ctx, task = learning_run
    handlers.check(ctx, task)
    handlers.check(ctx, task)
    other = phase.create(ctx.task_root(), ctx.name, "notes", "interactive", "writing")
    other.update(**task.data["data"])
    checks.begin(other)
    handlers.check(ctx, other, budget_dir=task.dir)
    assert handlers.check(ctx, phase.load(other.dir), budget_dir=task.dir) == checks.LIMIT


def test_tool_svg_warnings_and_status_counts(learning_run):
    from school_notes2.flows import status
    ctx, task = learning_run
    rel = "wiki/assets/proba/kep.svg"
    safefs.write_text(ctx.notes_path, rel, '<svg><text>A 2. dia.</text></svg>')
    steps.record_tool_files(task, ctx.notes_path, [rel])
    assert rel not in steps.llm_snapshot(ctx, task)
    found = steps.check_items(ctx, task)
    assert any(i.get("kind") == "source_ref" and i["file"] == rel for i in found)
    assert status.summary(ctx)["source_ref_counts"] == {rel: 1}


def test_machine_stamp_does_not_transfer_author_error_to_tool(learning_run):
    ctx, task = learning_run
    path = ctx.notes_path / TOPIC
    path.write_text(path.read_text() + "\n[Broken](missing.md)\n")
    steps.record_tool_files(task, ctx.notes_path, [TOPIC])
    # Exact last-written hash is necessary, but the diff still contains author prose.
    checks.tool_errors(ctx, task, [item(TOPIC, 1, "invalid link")])
    with pytest.raises(steps.CheckFailed):
        steps.check_changed(ctx, task)
