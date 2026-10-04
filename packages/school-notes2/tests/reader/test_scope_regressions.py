"""K-12, K-14, K-15: malformed paths and inherited defects never trap a run."""

import copy
from types import SimpleNamespace

import pytest

from school_notes2.figures import pending
from school_notes2.flows import correction, inspection, review_phases
from school_notes2.reader import calls, notices, report, units, verdicts
from school_notes2.review import relations
from school_notes2.state import phase, safefs
from school_notes2.wiki.check_result import check_result
from .test_phases import finding, install_reader
from .test_reader import pass1
from .test_review_fixes import figure


@pytest.mark.parametrize("path", ["/work/m/summary.md", "../wiki/m/summary.md", "wiki/m/missing.md"])
def test_unassigned_unknown_path_does_not_fail_or_recur(setup, monkeypatch, path):
    ctx, task, page = setup
    invoked = []
    def invoke(*args, **kwargs):
        invoked.append(1)
        return SimpleNamespace(output={**pass1(page), "findings": [finding(path)]})
    monkeypatch.setattr(calls.launch, "run_headless", invoke)
    inspection.prepare(ctx, task)
    inspection.inspect(ctx, task)
    inspection.inspect(ctx, phase.load(task.dir))
    assert invoked == [1]
    assert not relations.inventory(ctx.notes_path)["items"]
    assert path in task.get("reader_owner_notes")[0]
    assert verdicts.valid(ctx.notes_path, page) is not None
    task.set_phase("review_ready")
    review_phases.advance(ctx, task, lambda _: None)
    assert task.phase == "finishing" and task.data["needs_owner"] is None


def test_context_finding_has_section_notice_and_separate_assignment_flag(setup, monkeypatch):
    ctx, task, page = setup
    other = "wiki/m/summary.md"
    safefs.write_text(ctx.notes_path, other, "---\ntype: summary\n---\n# Összefoglaló\n\n[Topic](topic.md)\n\nHibás állítás.\n")
    def invoke(*args, **kwargs):
        return SimpleNamespace(output={**pass1(page), "findings": [
            {**finding(other), "quote": "Hibás állítás."}]})
    monkeypatch.setattr(calls.launch, "run_headless", invoke)
    inspection.prepare(ctx, task)
    inspection.inspect(ctx, task)
    record = next(iter(relations.inventory(ctx.notes_path)["items"].values()))
    assert record["outside_assignment"] and not record["unlocated"]
    assert correction.assigned(ctx, task) == []
    # Another unit has reviewed this page; the unrelated context finding stays local.
    verdicts.record(ctx.notes_path, pass1(other)["pages"], {other: units.page_key(ctx.notes_path, other)},
                    "model/high", task.data["created"])
    notices.refresh(ctx.notes_path, [other])
    text = safefs.read_text(ctx.notes_path, other)
    assert notices.SECTION in text and notices.PAGE not in text
    # The same fields survive supplements on a later attempt, not just report creation.
    report.append(ctx.notes_path, task.get("inspection_report"), [
        {**finding(other), "origin": "reader", "outside_assignment": True,
         "quote": "[Topic](topic.md)"}], [], "second")
    records = relations.inventory(ctx.notes_path)["items"].values()
    assert all(r["outside_assignment"] and not r["unlocated"] for r in records)


@pytest.mark.parametrize("damage", ["page", "marker", "anchor", "source", "crop", "replacement"])
@pytest.mark.parametrize("inherited", [False, True])
def test_pending_damage_is_writer_error_only_when_base_was_valid(setup, monkeypatch, damage, inherited):
    ctx, task, page = setup
    brief, candidate = figure(ctx, task, page)
    if damage in ("source", "crop"):
        brief["source_image"] = {"path": candidate["asset"], "crop": [0, 0, 20, 10]}
    if damage == "replacement":
        brief.update(replaces="wiki/assets/old.png", decision_reason={"code": "a", "text": "Hibás"})
        safefs.write_bytes(ctx.notes_path, brief["replaces"], safefs.read_bytes(ctx.notes_path, candidate["asset"]))
    safefs.write_json(ctx.notes_path, ".school-notes/figures/f.json", brief)
    entry = pending.record(ctx.notes_path, brief, "previous", [])
    if not inherited:
        brief = copy.deepcopy(brief)
    task.update(pending_figures=[entry], inspection_result={"status": "done"})
    base = {p: safefs.read_bytes(ctx.notes_path, p) for p in safefs.walk_files(ctx.notes_path)}
    if damage in ("page", "source", "replacement"):
        safefs.unlink(ctx.notes_path, {"page": page, "source": candidate["asset"],
                                     "replacement": brief.get("replaces")}[damage])
    elif damage == "crop":
        brief["source_image"]["crop"] = [0, 0, 200, 100]
        safefs.write_json(ctx.notes_path, ".school-notes/figures/f.json", brief)
    else:
        old, new = ("<!-- figure: f -->", "") if damage == "marker" else ("# Téma", "# Más cím")
        safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page).replace(old, new))
    if inherited:
        base = {p: safefs.read_bytes(ctx.notes_path, p) for p in safefs.walk_files(ctx.notes_path)}
    # Candidate is run-local, so its absence must not make a previously valid brief invalid.
    safefs.unlink(ctx.notes_path, ".school-notes/figures/f/figure.json")
    fetch = {"packages": [], "pages": [], "pending_figures": [entry]}
    problems = check_result(ctx.notes_path, {"status": "done"}, fetch, set(), base_content=base.get)
    assert bool(problems) is not inherited
    if not inherited:
        return
    install_reader(monkeypatch, page)
    review_phases.advance(ctx, task, lambda _: None)
    assert task.phase == "finishing" and task.data["needs_owner"] is None
    assert task.get("inspection_figures")[0]["candidate"]["state"] == "failed"
    assert pending.load(ctx.notes_path)[0]["defects"]
    review_phases.finalize(ctx, phase.load(task.dir))
    assert pending.load(ctx.notes_path)[0]["runs"] == 2


def test_valid_pending_requires_candidate_or_explicit_failure(setup):
    ctx, task, page = setup
    brief, _ = figure(ctx, task, page)
    entry = pending.record(ctx.notes_path, brief, "previous", [])
    base = {p: safefs.read_bytes(ctx.notes_path, p) for p in safefs.walk_files(ctx.notes_path)}
    fetch = {"packages": [], "pages": [], "pending_figures": [entry]}
    safefs.unlink(ctx.notes_path, ".school-notes/figures/f/figure.json")
    assert check_result(ctx.notes_path, {"status": "done"}, fetch, set(), base_content=base.get)
    safefs.write_json(ctx.notes_path, ".school-notes/figures/f/figure.json", {"state": "failed", "reason": "Nem sikerült"})
    assert not check_result(ctx.notes_path, {"status": "done"}, fetch, set(), base_content=base.get)


def test_inherited_broken_notebook_drawing_is_not_a_p1_accounting_error(setup):
    ctx, task, page = setup
    brief, candidate = figure(ctx, task, page)
    brief.update(kind="notebook-drawing", source_image={"path": candidate["asset"], "crop": [0, 0, 20, 10]})
    safefs.write_json(ctx.notes_path, ".school-notes/figures/f.json", brief)
    entry = pending.record(ctx.notes_path, brief, "previous", [])
    safefs.unlink(ctx.notes_path, page)
    base = {p: safefs.read_bytes(ctx.notes_path, p) for p in safefs.walk_files(ctx.notes_path)}
    result = {"status": "done", "figures": [{k: brief[k] for k in ("id", "kind", "page")}],
              "notebook_drawings": [{"figure": "f", "source": candidate["asset"], "crop": "whole"}]}
    fetch = {"packages": [], "pages": [], "pending_figures": [entry]}
    assert not check_result(ctx.notes_path, result, fetch, set(), base_content=base.get)
