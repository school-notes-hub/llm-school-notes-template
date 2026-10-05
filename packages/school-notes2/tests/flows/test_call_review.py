"""K-3/K-4: run-wide capacity, total assignment and independent finish retries."""

from types import SimpleNamespace

import pytest

from school_notes2.flows import fetch, handlers, steps, writer
from school_notes2.review import files
from school_notes2.sources import calls
from school_notes2.state import phase, safefs
from school_notes2.state.files import write_json
from school_notes2.wiki import check, frontmatter
from tests.flows.test_subject_calls import data


def review(repo, locations):
    path = files.write_review(repo, "2026-10-04", {"verdict": "changes", "findings": [
        {"severity": "hiba", "id": f"R{n}", "file": rel, "problem": "Hiba."} for n, rel in enumerate(locations, 1)]},
        "r", "a", "b")
    return path.relative_to(repo).as_posix()


@pytest.mark.parametrize("student", ["benedek", "barna"])
def test_two_subjects_share_twenty_closures_without_untouched_overflow(tmp_path, student):
    packages, _ = data(tmp_path)
    pages = []
    rel = review(tmp_path, [f"wiki/{s}/topic.md" for s in ("a", "b") for _ in range(12)])
    text = safefs.read_text(tmp_path, rel)
    details = frontmatter.split(text).meta["item_details"]
    details["R24"]["round"] = 2
    safefs.write_text(tmp_path, rel, frontmatter.set_keys(text, {"item_details": details}))
    reviews = files.open_items(tmp_path, "cron")
    selected = calls.select_reviews(list(reversed(reviews)), repo=tmp_path)
    assert selected[0]["item_id"] == "R24"
    assigned = calls.assignments(tmp_path, packages, pages, reviews, [])
    assert [len(c["open_review_items"]) for c in assigned] == [12, 0]
    assert assigned == calls.assignments(tmp_path, packages, pages, list(reversed(reviews)), [])
    task = phase.create(tmp_path / "tasks", student, "notes", "cron", "prepared")
    task.update(calls=assigned, ranges=calls.ranges(assigned), packages=packages, pages=pages,
                open_review_items=selected)
    closures = [{**{k: i[k] for k in ("file", "item_id")}, "status": "fixed"}
                for c in assigned for i in c["open_review_items"]]
    for n, c in enumerate(assigned, 1):
        result = {"status": "done", "review_closure": [i for i in closures
                  if i["item_id"] in {r["item_id"] for r in c["open_review_items"]}]}
        from school_notes2.wiki.check_result import check_result
        assert not check_result(tmp_path, result, fetch.fetch_json(task, n, grade=9),
                                {(i["file"], i["item_id"]) for i in c["open_review_items"]}, 20,
                                whole_run=False)
    whole = fetch.fetch_json(task, 2, grade=9, whole_run=True)
    assert len(whole["open_review_items"]) == len(closures) == 12
    files.apply_closure(tmp_path, "test", closures, whole["open_review_items"], 5)
    final = safefs.read_text(tmp_path, rel)
    assert "nem érintett" not in final
    assert {i["item_id"] for i in files.open_items(tmp_path, "cron")} == {f"R{n}" for n in range(1, 13)}


def test_review_capacity_orders_round_then_date_then_numeric_id():
    items = [{"file": f"docs/review/{date}-review.md", "item_id": key, "round": rnd}
             for date, key, rnd in [("2026-10-04", "R10", 1), ("2026-10-04", "R2", 1),
                                    ("2026-10-03", "R9", 1), ("2026-10-05", "R8", 2)]]
    assert [i["item_id"] for i in calls.select_reviews(items, 3)] == ["R8", "R9", "R2"]


def test_unlocated_and_asset_work_is_assigned_once_even_for_d36(tmp_path):
    packages, seed = data(tmp_path)
    safefs.write_text(tmp_path, "wiki/a/topic.md", "![A](../assets/figure.svg)\n")
    safefs.write_text(tmp_path, "wiki/b/topic.md", "```md\n![A](../assets/figure.svg)\n```\n")
    review(tmp_path, ["wiki/index.md", "unknown", "wiki/assets/figure.svg"])
    pending = [{"plan_id": "global", "page": "wiki/index.md"},
               {"plan_id": "asset", "page": "wiki/assets/figure.svg"}]
    reviews = files.open_items(tmp_path, "cron")
    assigned = calls.assignments(tmp_path, packages, seed, reviews, pending)
    assert [c["subject"] for c in assigned] == ["b", "a"]
    assert [i["item_id"] for i in assigned[0]["open_review_items"]] == ["R1", "R2"]
    assert [i["item_id"] for i in assigned[1]["open_review_items"]] == ["R3"]
    assert [i["plan_id"] for i in assigned[0]["pending_images"]] == ["global"]
    assert [i["plan_id"] for i in assigned[1]["pending_images"]] == ["asset"]
    many = [{**seed[0], "seq": n} for n in range(1, 62)]
    split = calls.assignments(tmp_path, packages[:1], many, reviews, pending)
    assert len(split) == 3
    assert sum(len(c["open_review_items"]) for c in split) == 3
    assert sum(len(c["pending_images"]) for c in split) == 2
    assert all(not c["open_review_items"] and not c["pending_images"] for c in split[1:])


def test_only_unlocated_work_still_has_a_call(tmp_path):
    review(tmp_path, ["unknown"])
    assigned = calls.assignments(tmp_path, [], [], files.open_items(tmp_path, "cron"), [])
    assert len(assigned) == 1 and len(assigned[0]["open_review_items"]) == 1


def task_context(tmp_path):
    packages, pages = data(tmp_path)
    packages.append({**packages[0], "subject": "c"})
    assigned = calls.assignments(tmp_path, packages, pages, [], [])
    task = phase.create(tmp_path / "tasks", "barna", "notes", "cron", "finishing")
    task.update(calls=assigned, ranges=calls.ranges(assigned), packages=packages, pages=pages, writing_k=4)
    for k in range(1, 4):
        write_json(task.dir / f"result-{k}.json", {"status": "done"})
    ctx = SimpleNamespace(notes_path=tmp_path, student=SimpleNamespace(grade=11),
                          cfg=SimpleNamespace(role=lambda _: (None, None),
                           limits=SimpleNamespace(review_closures_per_run=20, max_agents=3)))
    return ctx, task


def test_per_call_validation_and_mcp_hide_other_subject_errors(tmp_path, monkeypatch):
    ctx, task = task_context(tmp_path)
    task.update(writing_k=1)
    monkeypatch.setattr(steps, "guard_step", lambda *a: None)
    errors = [check.item("wiki/a/topic.md", None, "other subject")]
    def changed(*a, **kw):
        raise steps.CheckFailed(errors)
    monkeypatch.setattr(steps, "check_changed", changed)
    monkeypatch.setattr("school_notes2.wiki.check_result.check_result", lambda *a, **kw: [])
    with pytest.raises(steps.CheckFailed):
        writer._check_call(ctx, task, 1, {"status": "done"})
    monkeypatch.setattr(steps, "check_items", lambda *a: errors)
    monkeypatch.setattr("school_notes2.flows.learning.refresh", lambda *a: None)
    monkeypatch.setattr(handlers, "public_problems", lambda *a: [])
    monkeypatch.setattr("school_notes2.flows.generation_receipts.rights", lambda *a: lambda _: None)
    assert not handlers.check(ctx, task)["ok"]
    errors.append(check.item("wiki/b/topic.md", None, "own subject"))
    with pytest.raises(steps.CheckFailed) as failed:
        writer._check_call(ctx, task, 1, {"status": "done"})
    assert [i["file"] for i in failed.value.items] == ["wiki/a/topic.md", "wiki/b/topic.md"]
