"""Ú-3/Ú-5: preparation must leave the owner's repair path usable."""

import pytest

from school_notes2.flows import fetch, handlers, learning, steps, writer
from school_notes2.review import files, relations
from school_notes2.sources import calls
from school_notes2.state import phase, safefs
from school_notes2.state.errors import NeedsOwner
from school_notes2.wiki import check, frontmatter
from tests.flows.test_learning_checks import learning_run, NOTE, TOPIC


def prepare(ctx, task, monkeypatch):
    monkeypatch.setattr(fetch, "_validated_base", lambda *a: task.get("base"))
    task.set_phase("moved", selected=[])
    fetch.prepare(ctx, task, new_subject_index=fetch.new_subject)
    return fetch.fetch_json(phase.load(task.dir), 1)


def test_interactive_fetch_prioritizes_owner_over_twenty_one_open_items(learning_run, monkeypatch):
    ctx, task = learning_run
    for day, count, owner in [("2026-09-01", 21, False), ("2026-10-04", 1, True)]:
        path = files.write_review(ctx.notes_path, day, {"verdict": "changes", "findings": [
            {"id": f"R{n}", "file": TOPIC, "problem": "Hiba."} for n in range(1, count + 1)]},
            "r", "a", "b")
        if owner:
            path.write_text(frontmatter.set_keys(path.read_text(), {"items": {"R1": "owner"}}))
    repair = "docs/review/20261003-0100-ab12-repair.md"
    safefs.write_text(ctx.notes_path, repair, frontmatter.set_keys("# Javítás\n", {
        "items": {"R1": "owner"}, "item_details": {"R1": {"file": TOPIC}}}))
    # All three reports belong to the preparation base.
    wt = ctx.worktree("notes")
    wt.run("add", "docs")
    wt.run("commit", "-qm", "review backlog")
    task.update(base=wt.out("rev-parse", "HEAD").strip())
    inp = prepare(ctx, task, monkeypatch)
    selected = inp["open_review_items"]
    assert len(selected) == 20
    assert [(i["file"], i["status"]) for i in selected[:2]] == [
        (repair, "owner"), ("docs/review/2026-10-04-review.md", "owner")]
    assert len([i for i in selected if i["status"] == "open"]) == 18
    assert selected == calls.select_reviews(list(reversed(files.open_items(ctx.notes_path, "interactive"))),
                                             mode="interactive")
    result = {"status": "done", "review_closure": [
        {"file": i["file"], "item_id": i["item_id"], "status": "fixed"} for i in selected[:2]]}
    from school_notes2.wiki.check_result import check_result
    assert not check_result(ctx.notes_path, result, inp,
                            {(i["file"], i["item_id"]) for i in selected}, 20, whole_run=False)


@pytest.mark.parametrize("invalid", ["broken: [\n", "- not-a-mapping\n"])
def test_prepare_skips_unreadable_page_and_old_error_needs_owner(learning_run, monkeypatch, invalid):
    ctx, task = learning_run
    valid = safefs.read_text(ctx.notes_path, NOTE)
    safefs.write_text(ctx.notes_path, NOTE, "---\n" + invalid + "---\n![X](../assets/x.svg)\n")
    wt = ctx.worktree("notes")
    wt.run("add", "wiki")
    wt.run("commit", "-qm", "old invalid metadata")
    task.update(base=wt.out("rev-parse", "HEAD").strip())
    inp = prepare(ctx, task, monkeypatch)
    assert inp["mode"] == "interactive"
    assert NOTE not in relations.related_pages(ctx.notes_path)
    assert relations.page_ids(ctx.notes_path, NOTE) == (set(), set())
    with pytest.raises(NeedsOwner, match="invalid metadata predating this run"):
        learning.validate(ctx, phase.load(task.dir))
    # Fixing the YAML in chat makes the same check usable again.
    safefs.write_text(ctx.notes_path, NOTE, valid)
    learning.validate(ctx, phase.load(task.dir))


def test_new_yaml_and_asset_errors_stay_with_writer(learning_run, monkeypatch):
    ctx, task = learning_run
    task.data["mode"] = "cron"
    task.update(calls=[{"subject": "proba", "packages": [], "seqs": [],
                        "open_review_items": [], "pending_images": []}], writing_k=1)
    safefs.write_text(ctx.notes_path, NOTE, "---\nbroken: [\n---\n")
    asset = check.item("wiki/assets/orphan.svg", None, "asset defect")
    def guard(*a):
        raise steps.CheckFailed([asset])
    monkeypatch.setattr(steps, "guard_step", guard)
    answer = handlers.check(ctx, task)
    assert not answer["ok"]
    assert {i["file"] for i in answer["problems"]} == {NOTE, asset["file"]}
    with pytest.raises(steps.CheckFailed) as failed:
        writer._check_call(ctx, task, 1, {"status": "done"})
    assert {i["file"] for i in failed.value.items} == {NOTE, asset["file"]}
