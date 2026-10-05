"""Browser links keep both pages and return author-caused failures to the writer."""

import pytest
import hashlib

from school_notes2.flows import call_scope, checks, steps
from school_notes2.site import build
from school_notes2.state import phase, safefs
from school_notes2.state.errors import SnError
from tests.flows.test_learning_checks import learning_run, TOPIC, NOTE


@pytest.mark.parametrize("changed_target", [True, False])
def test_accented_cross_page_anchor_routes_to_writer_only_for_changed_target(learning_run, changed_target):
    ctx, task = learning_run
    repo = ctx.notes_path
    anchor = "2-dia---a-városállam-működése"
    safefs.write_text(repo, TOPIC, safefs.read_text(repo, TOPIC) + f'\n<a id="{anchor}"></a>\n')
    # The source stays tool-owned; only the destination was changed by this run.
    safefs.write_text(repo, NOTE, safefs.read_text(repo, NOTE) + f"\n[Téma](elso.md#{anchor})\n")
    task.update(tool_writes={NOTE: hashlib.sha256(safefs.read_bytes(repo, NOTE)).hexdigest()})
    if not changed_target:
        task.update(tool_writes={**task.get("tool_writes"), TOPIC: hashlib.sha256(safefs.read_bytes(repo, TOPIC)).hexdigest()})
    errors = build._browser_problems([{"path": NOTE, "target": TOPIC,
        "link": f"http://localhost/jegyzet/proba/elso/#{anchor}", "error": "missing fragment"}])
    assert errors[0]["file"] == NOTE and errors[0]["target"] == TOPIC
    assert anchor in errors[0]["message"]
    routed = checks.build_dependencies(ctx, task, errors)
    if not changed_target:
        with pytest.raises(SnError, match="unchanged tool output"):
            checks.tool_errors(ctx, task, routed)
        return
    checks.tool_errors(ctx, task, routed)
    assert {i["file"] for i in routed} == {TOPIC, NOTE}
    task.data["mode"] = "cron"
    task.update(calls=[{"subject": "proba", "packages": [], "seqs": [],
                        "open_review_items": [], "pending_images": []}])
    call_scope.retry(ctx, task, routed)
    task = phase.load(task.dir)
    assert task.phase == "writing"
    assert {i["file"] for i in task.get("retry_items")["1"]} == {TOPIC, NOTE}


def test_multiple_links_on_one_page_are_not_lost():
    result = build._browser_problems([
        {"path": "wiki/m/a.md", "target": "wiki/m/b.md", "link": link, "error": "missing fragment"}
        for link in ("http://localhost/b/#ő", "http://localhost/b/#ű", "http://localhost/b/#ő")])
    assert len(result) == 2
    assert result == build._browser_problems(list(reversed([
        {"path": "wiki/m/a.md", "target": "wiki/m/b.md", "link": link, "error": "missing fragment"}
        for link in ("http://localhost/b/#ő", "http://localhost/b/#ű")])))


def test_cross_subject_referrer_is_returned_with_assigned_target(learning_run):
    ctx, task = learning_run
    task.data["mode"] = "cron"
    task.update(calls=[{"subject": "proba", "packages": [], "seqs": [],
                        "open_review_items": [], "pending_images": []}])
    problem = {"file": "wiki/masik/utalas.md", "line": None, "kind": "browser-link",
               "target": TOPIC, "message": "public build: missing fragment"}
    call_scope.retry(ctx, task, [problem])
    task = phase.load(task.dir)
    assert task.get("retry_items") == {"1": [problem]}
    assert call_scope.current(ctx, task, [problem], 1) == [problem]
