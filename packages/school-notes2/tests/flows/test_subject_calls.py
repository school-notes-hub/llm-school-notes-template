"""T-121 and D36, with stable restart checkpoints (T-095)."""

from types import SimpleNamespace

import pytest

from school_notes2.flows import fetch, writer
from school_notes2.sources import calls
from school_notes2.state import phase, safefs
from tests.sources.test_cards import CARD


def data(repo):
    safefs.write_json(repo, "tools/subjects.json", {"subjects": {
        "b": {"card": CARD}, "a": {"card": {**CARD, "role": "Másik tanár"}}}})
    packages = [{"drive_folder": name, "subject": sub, "role": "fuzet", "new_subject": False,
                 "preconverted": False, "files": [], "card": CARD}
                for name, sub in [("same", "a"), ("same", "b"), ("third", "a")]]
    pages = [{"seq": n, "package": p["drive_folder"], "file": "a.jpg", "page": None,
              "path": f"sources/{p['subject']}/p{n}/a.jpg", "sha256": "a" * 64,
              "duplicate_of": None} for n, p in enumerate(packages, 1)]
    return packages, pages


@pytest.mark.parametrize("student", ["benedek", "barna"])
def test_subject_calls_keep_noncontiguous_source_ids_and_cards(tmp_path, student):
    packages, pages = data(tmp_path)
    assigned = calls.assignments(tmp_path, packages, pages, [], [])
    assert [c["subject"] for c in assigned] == ["b", "a"]
    assert [c["seqs"] for c in assigned] == [[2], [1, 3]]
    task = phase.create(tmp_path / "tasks", student, "notes", "cron", "prepared")
    task.update(calls=assigned, packages=packages, pages=pages, ranges=calls.ranges(assigned))
    first, second = fetch.fetch_json(task, 1), fetch.fetch_json(task, 2)
    assert first["pages"] == [pages[1]]
    assert second["pages"] == [pages[0], pages[2]]
    assert first["card"]["role"] != second["card"]["role"]
    assert len(first["packages"]) == 1 and len(second["packages"]) == 2
    assert fetch.fetch_json(task, 2, whole_run=True)["pages"] == pages
    safefs.write_json(tmp_path, "tools/subjects.json", {"subjects": {}})
    assert fetch.fetch_json(phase.load(task.dir), 2) == second


def test_only_one_oversized_package_is_split(tmp_path):
    packages, seed = data(tmp_path)
    pages = [{**seed[0], "seq": n} for n in range(1, 76)]
    assigned = calls.assignments(tmp_path, packages[:1], pages, [], [])
    assert calls.ranges(assigned) == [[1, 30], [31, 60], [61, 75]]
    # Multiple packages of the subject never get the D36 split.
    assert len(calls.assignments(tmp_path, [packages[0], packages[2]], pages, [], [])) == 1


def test_pending_images_and_review_items_are_subject_scoped(tmp_path):
    from school_notes2.review import files
    packages, pages = data(tmp_path)
    path = files.write_review(tmp_path, "2026-10-04", {"verdict": "changes", "findings": [
        {"id": "R1", "file": "wiki/b/topic.md", "problem": "Hiba."}]}, "r", "a", "b")
    reviews = [{"file": path.relative_to(tmp_path).as_posix(), "item_id": "R1"}]
    pending = [{"plan_id": "diagram", "page": "wiki/a/topic.md"}]
    assigned = calls.assignments(tmp_path, packages, pages, reviews, pending)
    assert assigned[0]["open_review_items"] == reviews
    assert assigned[0]["pending_images"] == []
    assert assigned[1]["open_review_items"] == []
    assert assigned[1]["pending_images"] == pending


def test_writer_resume_reuses_validated_result_after_checkpoint_crash(tmp_path, monkeypatch):
    task = phase.create(tmp_path, "barna", "notes", "cron", "prepared")
    task.update(ranges=[[1, 1], [2, 2]], writing_k=1)
    ctx = SimpleNamespace(cfg=SimpleNamespace(role=lambda _: (None, None)))
    invoked = []
    monkeypatch.setattr(writer, "write_inputs", lambda *args: None)
    monkeypatch.setattr(writer, "_call", lambda ctx, task, k, *args: invoked.append(k) or {"status": "done"})
    monkeypatch.setattr(writer, "_check_call", lambda *args: None)
    real = writer.write_json
    def crash(path, result):
        real(path, result)
        raise RuntimeError("checkpoint crash")
    monkeypatch.setattr(writer, "write_json", crash)
    with pytest.raises(RuntimeError):
        writer.run_ranges(ctx, task, None)
    assert invoked == [1]
    monkeypatch.setattr(writer, "write_json", real)
    assert writer.run_ranges(ctx, phase.load(task.dir), None) == "done"
    assert invoked == [1, 2]


def test_writer_rechecks_each_call_before_saving_result(tmp_path, monkeypatch):
    from school_notes2.flows import steps
    task = phase.create(tmp_path, "barna", "notes", "cron", "writing")
    task.update(ranges=[[0, 0]])
    ctx = SimpleNamespace(cfg=SimpleNamespace(role=lambda _: (None, None)))
    monkeypatch.setattr(writer, "write_inputs", lambda *args: None)
    monkeypatch.setattr(writer, "_call", lambda *args: {"status": "done"})
    def bad(*args):
        raise steps.CheckFailed([])
    monkeypatch.setattr(writer, "_check_call", bad)
    monkeypatch.setattr(steps, "write_check_items", lambda *args: None)
    with pytest.raises(steps.CheckFailed):
        writer.run_ranges(ctx, task, None)
    assert not (task.dir / "result-1.json").exists()
    assert phase.load(task.dir).get("writing_k") == 1
