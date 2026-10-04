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


def test_content_order_and_public_errors_in_one_check(learning_run):
    from school_notes2.wiki import frontmatter
    ctx, task = learning_run
    task.data["mode"] = "cron"
    path = ctx.notes_path / TOPIC
    text = frontmatter.set_keys(path.read_text(), {"order": 20})
    path.write_text(text + "\n[Hiányzó](missing.md)\n![Ábra](../assets/proba/new.svg)\n")
    safefs.write_text(ctx.notes_path, "wiki/assets/proba/new.svg", "<svg/>\n")
    answer = handlers.check(ctx, task)
    messages = [i["message"] for i in answer["problems"]]
    assert any("link target does not exist" in m for m in messages)
    assert any("`order` of an existing page changed" in m for m in messages)
    assert any("new images with no render.json" in m for m in messages)
    assert safefs.read_json(ctx.notes_path, answer["full_list"]) == answer["problems"]
    assert task.get("writer_check")["count"] == 1


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


def test_interactive_fetch_new_task_has_own_budget(learning_run, monkeypatch):
    from school_notes2.flows import chat
    ctx, task = learning_run
    h = handlers.build(ctx)
    for _ in range(3):
        h.check()
    assert h.check() == checks.LIMIT
    chat.session_fetch(ctx)  # Same task must not reset.
    assert h.check() == checks.LIMIT
    task.reload()
    task.set_phase("done")
    other = phase.create(ctx.task_root(), ctx.name, "notes", "interactive", "writing")
    other.update(**task.data["data"])
    # Make fetch create the next task, whose stale copied count must be reset.
    other.set_phase("done")
    def start(ctx):
        other.set_phase("writing")
        return other
    monkeypatch.setattr(chat, "interactive_fetch", start)
    assert chat.session_fetch(ctx)["run_id"] == other.run_id
    for _ in range(3):
        assert "limit_reached" not in h.check()
    assert h.check() == checks.LIMIT


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


def test_non_source_warning_survives_machine_stamp(learning_run):
    from school_notes2.wiki import frontmatter
    ctx, task = learning_run
    path = ctx.notes_path / TOPIC
    path.write_text(path.read_text() + '\n[^hely]: [Forrás](../../sources/missing.pdf)\n')
    own = handlers.check(ctx, task)["problems"]
    warning = next(i for i in own if "cited source" in i["message"])
    result = {"status": "done", "warnings": [{"id": warning["id"], "action": "kept", "reason": "Hivatkozás."}]}
    path.write_text(frontmatter.set_keys(path.read_text(), {"generated": {"by": "tool", "at": "2026-10-04"}}))
    later = checks.after_writer(ctx, task, result, steps.check_items(ctx, task))
    actual = next(i for i in later if "cited source" in i["message"])
    assert actual["line"] != warning["line"]
    assert actual["id"] == warning["id"] and not actual["unhandled"]


def test_writer_call_accounting_failure_is_bad_work(learning_run, monkeypatch):
    from contextlib import nullcontext
    from school_notes2.llm import launch
    ctx, task = learning_run
    role, harness = ctx.cfg.role("writer")
    monkeypatch.setattr(writer, "mcp", lambda *a: nullcontext(task.dir))
    def call(*args, **kwargs):
        fresh = phase.load(task.dir)
        checks.remember(fresh, [{"severity": "warning", "id": "missed"}])
        return SimpleNamespace(output={"status": "done"})
    monkeypatch.setattr(launch, "run_headless", call)
    with pytest.raises(steps.CheckFailed) as caught:
        writer._call(ctx, task, 1, role, harness, None)
    assert "missing decision for missed" in caught.value.items[0]["message"]
    assert safefs.read_json(ctx.notes_path, ".school-notes/check.json") == caught.value.items
    policy.on_error(caught.value, task=task, student=ctx.name, step="writer", log=ctx.log, mailer=None)
    assert task.data["llm_failures"] == 1 and not task.data.get("needs_owner")


def test_interactive_merged_result_accounting(learning_run):
    ctx, task = learning_run
    checks.remember(task, [{"severity": "warning", "id": "missed"}])
    safefs.write_json(ctx.notes_path, ".school-notes/result.json", {"status": "done"})
    with pytest.raises(steps.CheckFailed) as caught:
        steps.merged_result(ctx, task)
    assert "missing decision" in caught.value.items[0]["message"]
    assert not (task.dir / "result-1.json").exists()
    own = {"status": "done", "warnings": [{"id": "missed", "action": "kept", "reason": "Példa."}]}
    safefs.write_json(ctx.notes_path, ".school-notes/result.json", own)
    assert steps.merged_result(ctx, task)["warnings"] == own["warnings"]


def test_question_session_accounting_feedback_and_resume(learning_run, monkeypatch):
    from school_notes2.flows import chat
    ctx, task = learning_run
    task.data["mode"] = "cron"
    task.update(question=[{"text": "Dátum?"}], ranges=[[0, 0], [0, 0]], writing_k=1)
    checks.remember(task, [{"severity": "warning", "id": "missed"}])
    safefs.write_json(ctx.notes_path, ".school-notes/result.json", {"status": "done"})
    monkeypatch.setattr(type(ctx), "lock", lambda _: SimpleNamespace(note=lambda _: None))
    answer = chat.session_finish(ctx)
    assert answer["state"] == "check_failed" and answer["errors"] == 1
    assert "missing decision for missed" in answer["problems"][0]["message"]
    assert safefs.read_json(ctx.notes_path, answer["full_list"]) == answer["problems"]
    chat._after_question_session(ctx, phase.load(task.dir))
    fresh = phase.load(task.dir)
    assert fresh.data["needs_owner"]["reason"] == "the session result lacks warning decisions"
    assert chat._settle(ctx, fresh, lambda _: "f", lambda _: None)
    assert not (task.dir / "result-1.json").exists()
    safefs.write_json(ctx.notes_path, ".school-notes/result.json", {"status": "done", "warnings": [
        {"id": "missed", "action": "kept", "reason": "Példa."}]})
    assert chat.session_finish(ctx)["state"] == "saved"
    fresh = phase.load(task.dir)
    assert not fresh.get("question") and fresh.get("writing_k") == 2
    assert not chat.save_session_result(ctx, fresh)


@pytest.mark.parametrize("call_finish", [False, True])
def test_incomplete_question_chat_stays_with_owner(learning_run, monkeypatch, call_finish):
    from school_notes2.flows import chat, run
    ctx, task = learning_run
    task.data["mode"] = "cron"
    task.update(question=[{"text": "Dátum?"}], ranges=[[0, 0], [0, 0]], writing_k=1)
    task.mark_needs_owner("question", "answer in chat", "needs_owner")
    own = {"status": "done"}
    def session(ctx, task, harness):
        assert not task.data["needs_owner"]
        checks.remember(task, [{"severity": "warning", "id": "missed"}])
        safefs.write_json(ctx.notes_path, ".school-notes/result.json", own)
        if call_finish:
            assert chat.session_finish(ctx)["state"] == "check_failed"
    monkeypatch.setattr(chat.setup, "ensure", lambda _: None)
    monkeypatch.setattr(chat, "_launch", session)
    assert chat.chat(ctx, None, ask=lambda _: "f", say=lambda _: None) == 0
    fresh = phase.load(task.dir)
    assert fresh.data["needs_owner"]["reason"] == "the session result lacks warning decisions"
    assert fresh.get("question") and fresh.get("writing_k") == 1
    assert fresh.data["llm_failures"] == 0 and fresh.mode == "cron"
    assert not run._may_run(ctx, fresh)
    assert safefs.read_json(ctx.notes_path, ".school-notes/result.json") == own
    assert "missing decision for missed" in safefs.read_json(ctx.notes_path, ".school-notes/check.json")[0]["message"]
    assert not (task.dir / "result-1.json").exists()


@pytest.mark.parametrize("generated", [False, True])
def test_candidate_rights_are_reported_to_writer_using_live_host_ledger(learning_run, monkeypatch, generated):
    from school_notes2.wiki.pages import sha256
    ctx, task = learning_run
    asset = "wiki/assets/proba/candidate.png"
    safefs.write_bytes(ctx.notes_path, asset, b"synthetic image")
    brief = {"id": "candidate", "page": TOPIC, "anchor": "Rajz", "kind": "figure",
             "purpose": "Megértés", "must_show": ["Irány"], "avoid_misreading": "Ellentétes irány",
             "taught_conventions": [], "text_complete_without_figure": True}
    candidate = {"state": "candidate", "asset": asset, "alt": "Irány", "caption": "",
                 "form": "diagram", "tool": "test", "elements": [], "visible_text": [], "attempt": 1}
    safefs.write_text(ctx.notes_path, TOPIC, safefs.read_text(ctx.notes_path, TOPIC) +
                      "\n# Rajz\n\n<!-- figure: candidate -->\n")
    safefs.write_json(ctx.notes_path, ".school-notes/figures/candidate.json", brief)
    safefs.write_json(ctx.notes_path, ".school-notes/figures/candidate/figure.json", candidate)
    result = {"status": "done", "figures": [{k: brief[k] for k in ("id", "kind", "page")}]}
    safefs.write_json(ctx.notes_path, ".school-notes/result.json", result)
    jobs = {"candidate": {"learner": ctx.name, "attempts": [
        {"state": "generated", "preview_sha256": sha256(ctx.notes_path, asset)}]}} if generated else {}
    monkeypatch.setattr(ctx, "image_settings", lambda: SimpleNamespace(learner=ctx.name, ledger=lambda: {"jobs": jobs}))
    answer = handlers.check(ctx, task)
    assert answer["ok"] is generated, answer
    if not generated:
        assert any("no rights path" in p["message"] and p["file"].endswith("candidate/figure.json")
                   for p in answer["problems"])
        with pytest.raises(steps.CheckFailed, match="check"):
            writer._check_call(ctx, task, 1, result)
    else:
        writer._check_call(ctx, task, 1, result)
    assert not safefs.exists(ctx.notes_path, "docs/evidence/image-generation/ledger.json")
