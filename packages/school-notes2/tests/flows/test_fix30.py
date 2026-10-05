"""Durable browser dependencies and inherited notice-only browser warnings."""

import pytest
from school_notes2.flows import call_scope, checks, correction, status
from school_notes2.state import phase, safefs
from school_notes2.state.errors import BadWork
from school_notes2.wiki import markers
from tests.flows.test_learning_checks import learning_run, TOPIC, NOTE


def test_result_error_routes_to_first_writer_after_restart(learning_run):
    ctx, task = learning_run
    task.update(calls=[{"subject": "proba"}, {"subject": "masik"}])
    error = {"file": ".school-notes/result.json", "line": None, "message": "missing decision"}
    call_scope.retry(ctx, task, [error])
    task = phase.load(task.dir)
    assert task.get("retry_items") == {"1": [error]}
    assert task.data["needs_owner"] is None


def test_cross_unit_link_scope_survives_consuming_retry_items(learning_run):
    ctx, task = learning_run
    other = "wiki/masik/utalo.md"
    safefs.write_text(ctx.notes_path, other, "# Másik\n\n[Rész](../proba/elso.md#rossz)\n")
    root = task.dir / "before-fix"
    correction.snapshot(ctx.notes_path, root)
    task.update(calls=[{"subject": "proba"}])
    problem = {"file": other, "target": TOPIC, "kind": "browser-link", "line": None, "message": "missing fragment"}
    call_scope.retry(ctx, task, [problem])
    task.update(retry_link_pages=[])  # A retry queued by the preceding release.
    call_scope.write_check(ctx, task, 1)
    task = phase.load(task.dir)
    assert task.get("retry_items") == {}
    safefs.write_text(ctx.notes_path, other, "# Másik\n\n[Rész](../proba/elso.md#jo)\n")
    assert correction.check_scope(ctx, root, []) == []
    correction.check_scope(ctx, root, [], task.get("retry_link_pages"))


@pytest.mark.parametrize("target_changed", [False, True])
def test_notice_only_browser_defect_is_persistent_warning_unless_target_changed(learning_run, target_changed):
    ctx, task = learning_run
    text = safefs.read_text(ctx.notes_path, NOTE)
    safefs.write_text(ctx.notes_path, NOTE, text + "\n" + markers.wrap("pending", "⏳ Jelzés\n"))
    if target_changed:
        safefs.write_text(ctx.notes_path, TOPIC, safefs.read_text(ctx.notes_path, TOPIC) + "\nÚj tartalom.\n")
    error = {"file": NOTE, "target": TOPIC, "kind": "browser-link", "line": None, "message": "missing fragment"}
    remaining = checks.browser_warnings(ctx, task, [error])
    task = phase.load(task.dir)
    assert remaining == ([error] if target_changed else [])
    assert bool(task.get("browser_warnings")) != target_changed


def test_notice_browser_warning_reaches_status_and_build_continues(learning_run, monkeypatch):
    from school_notes2.site import build
    ctx, task = learning_run
    safefs.write_text(ctx.notes_path, NOTE, safefs.read_text(ctx.notes_path, NOTE) + "\n" + markers.wrap("pending", "⏳ Jelzés\n"))
    error = {"file": NOTE, "line": None, "message": "public build: overflow"}
    monkeypatch.setattr(build, "extract", lambda *a: None)
    monkeypatch.setattr(build, "last_updated", lambda *a: {})
    def render(renderer, src, out, dates):
        out.mkdir(parents=True)
        safefs.write_json(out, "payload.json", {"pages": [{"path": NOTE}]})
    monkeypatch.setattr(build, "_render", render)
    def browser(*a):
        raise build.BuildContentError([error])
    monkeypatch.setattr(build, "_browser_check", browser)
    checked = []
    monkeypatch.setattr(build, "_check_public", lambda *a: checked.append(True))
    result = build.build(None, "commit", task.dir, None, changed=[NOTE], log=ctx.log,
                         browser_filter=lambda items: checks.browser_warnings(ctx, task, items))
    assert result.commit == "commit" and checked == [True]
    data = status.summary(ctx)
    assert data["browser_warnings"][0]["file"] == NOTE
    assert "böngészős figyelmeztetés" in status.render(data)


def test_whitespace_only_author_edit_does_not_excuse_browser_error(learning_run):
    ctx, task = learning_run
    safefs.write_text(ctx.notes_path, NOTE, safefs.read_text(ctx.notes_path, NOTE) + "\n")
    error = {"file": NOTE, "line": None, "message": "overflow"}
    assert checks.browser_warnings(ctx, task, [error]) == [error]
