"""Check invocation/resume accounting and T-016/T-152 regression coverage."""

from types import SimpleNamespace

import pytest

from school_notes2.flows import checks, handlers, policy, steps, writer
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
    assert not task.get("writer_check")  # Warnings need no decision (#4).


def test_order_and_writer_svg_are_no_errors_but_a_broken_link_is(learning_run):
    """#12 and 6b: reordering is the writer's choice; a writer-drawn SVG needs no commission
    and is authored for publication. A missing link target stays an error (Maradjon)."""
    from school_notes2.wiki import frontmatter
    ctx, task = learning_run
    task.data["mode"] = "cron"
    path = ctx.notes_path / TOPIC
    text = frontmatter.set_keys(path.read_text(), {"order": 20})
    path.write_text(text + "\n[Hiányzó](missing.md)\n![Ábra](../assets/proba/new.svg)\n")
    safefs.write_text(ctx.notes_path, "wiki/assets/proba/new.svg", "<svg/>\n")
    answer = handlers.check(ctx, task)
    errors = [i["message"] for i in answer["problems"] if i["severity"] == "error"]
    assert errors == ["link target does not exist: 'missing.md'"]
    assert safefs.read_json(ctx.notes_path, answer["full_list"]) == answer["problems"]


def test_check_has_no_invocation_limit(learning_run, monkeypatch):
    """#19: the writer may check as often as it likes; an interrupted check costs nothing."""
    ctx, task = learning_run
    def crash(*args):
        raise RuntimeError("interrupted check")
    with monkeypatch.context() as m:
        m.setattr(steps, "guard_step", crash)
        with pytest.raises(RuntimeError):
            handlers.check(ctx, task)
    for _ in range(5):
        assert "limit_reached" not in handlers.check(ctx, phase.load(task.dir))


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


def test_machine_stamp_does_not_transfer_author_error_to_tool(learning_run):
    ctx, task = learning_run
    path = ctx.notes_path / TOPIC
    path.write_text(path.read_text() + "\n[Broken](missing.md)\n")
    steps.record_tool_files(task, ctx.notes_path, [TOPIC])
    # Exact last-written hash is necessary, but the diff still contains author prose.
    checks.tool_errors(ctx, task, [item(TOPIC, 1, "invalid link")])
    with pytest.raises(steps.CheckFailed):
        steps.check_changed(ctx, task)


def test_session_result_without_warning_decisions_is_accepted(learning_run, monkeypatch):
    """#4: a result without warning decisions is complete; nothing is sent back for it."""
    from school_notes2.flows import chat
    ctx, task = learning_run
    safefs.write_json(ctx.notes_path, ".school-notes/result.json", {"status": "done"})
    assert steps.merged_result(ctx, task)["status"] == "done"
    task.data["mode"] = "cron"
    task.update(question=[{"text": "Dátum?"}], ranges=[[0, 0], [0, 0]], writing_k=1)
    monkeypatch.setattr(type(ctx), "lock", lambda _: SimpleNamespace(note=lambda _: None))
    assert chat.session_finish(ctx)["state"] == "saved"
    fresh = phase.load(task.dir)
    assert not fresh.get("question") and fresh.get("writing_k") == 2 and not fresh.data["needs_owner"]


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
