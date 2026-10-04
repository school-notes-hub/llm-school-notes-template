import hashlib
import copy

import pytest

from school_notes2.figures import commissions, context, inputs, machine, pending
from school_notes2.schemas import validate
from school_notes2.state import safefs


def test_commission_marker_and_replacement_contract(repo, make_figure):
    brief, _ = make_figure()
    assignment = {k: brief[k] for k in ("id", "kind", "page")}
    assert commissions.validate_assignments(repo, [assignment]) == [brief]
    with pytest.raises(ValueError, match="duplicate"):
        commissions.validate_assignments(repo, [assignment, assignment])
    text = safefs.read_text(repo, brief["page"])
    safefs.write_text(repo, brief["page"], text + "```md\n<!-- figure: forces -->\n```\n")
    assert commissions.validate_assignments(repo, [assignment]) == [brief]
    safefs.write_text(repo, brief["page"], text + "<!-- image: forces -->\n")
    with pytest.raises(ValueError, match="exactly once"):
        commissions.validate_assignments(repo, [assignment])


@pytest.mark.parametrize("kind", ["notebook-drawing", "teacher-drawing"])
def test_drawings_require_crop_and_cannot_be_omitted(repo, make_figure, kind):
    brief, candidate = make_figure(kind=kind)
    with pytest.raises(ValueError):
        commissions.read(repo, brief["id"])
    brief["source_image"] = {"path": candidate["asset"], "crop": [0, 0, 400, 200]}
    safefs.write_json(repo, ".school-notes/figures/forces.json", brief)
    commissions.read(repo, brief["id"])
    with pytest.raises(ValueError, match="corrections"):
        commissions.candidate(repo, brief)
    safefs.write_json(repo, ".school-notes/figures/forces/figure.json", {"state": "no-figure", "reason": "skip"})
    with pytest.raises(ValueError, match="no-figure"):
        commissions.candidate(repo, brief)


@pytest.mark.parametrize("field", ["purpose", "must_show", "text_complete_without_figure"])
def test_commission_required_fields(make_figure, field):
    brief, _ = make_figure()
    del brief[field]
    with pytest.raises(ValueError):
        validate("figure-commission", brief)


def test_replacement_needs_reason_and_existing_asset(repo, make_figure):
    old, candidate = make_figure("old")
    brief, _ = make_figure("new", replaces=candidate["asset"])
    with pytest.raises(ValueError):
        commissions.read(repo, brief["id"])
    brief["decision_reason"] = {"code": "c", "text": "reviewer requested correction"}
    safefs.write_json(repo, ".school-notes/figures/new.json", brief)
    assert commissions.read(repo, "new") == brief


def test_pending_counts_runs_not_resumes_and_restores_full_commission(repo, make_figure):
    brief, _ = make_figure()
    defects = [{"location": "arrow", "observed": "wrong direction", "expected": "left"}]
    for run in ["1", "1", "2"]:
        pending.record(repo, brief, run, defects)
    assert pending.load(repo)[0]["runs"] == 2
    before = safefs.read_bytes(repo, pending.PATH)
    pending.record(repo, brief, "2", defects)
    assert safefs.read_bytes(repo, pending.PATH) == before
    safefs.unlink(repo, ".school-notes/figures/forces.json")
    pending.restore(repo, {brief["page"]})
    assert commissions.read(repo, "forces") == brief
    assert pending.record(repo, brief, "3", defects)["owner_required"]
    pending.record(repo, brief, "4", defects)
    assert pending.load(repo)[0]["runs"] == 3
    assert not pending.eligible(repo, {brief["page"]})


def test_batch_order_is_topic_then_page_then_position(repo, make_figure):
    briefs = [make_figure(f"f-{i}")[0] for i in range(6)]
    brief, _ = make_figure("lesson", "wiki/physics/lesson.md")
    text = safefs.read_text(repo, brief["page"]).replace("type: topic", "type: lesson-notes\nlessons:\n  - topics: [forces.md]")
    safefs.write_text(repo, brief["page"], text)
    briefs.append(brief)
    groups = inputs.batches(repo, list(reversed(briefs)))
    assert [len(items) for _, items in groups] == [4, 3]
    assert [b["id"] for _, items in groups for b in items] == [f"f-{i}" for i in range(6)] + ["lesson"]


def test_svg_hints_are_only_warnings(repo, make_figure):
    brief, candidate = make_figure()
    asset = "wiki/assets/physics/forces.svg"
    safefs.write_text(repo, asset, '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="500"><text font-size="10">42. dia</text></svg>')
    source = "wiki/assets/physics/forces.dot"
    safefs.write_text(repo, source, 'digraph { a -> b [style=invis]; }')
    candidate.update(asset=asset, source=source, alt="Forces")
    safefs.write_json(repo, "wiki/assets/physics/render.json", {
        "source": source, "source_sha256": hashlib.sha256(safefs.read_bytes(repo, source)).hexdigest(),
        "outputs": {"forces.svg": {"sha256": hashlib.sha256(safefs.read_bytes(repo, asset)).hexdigest()}}})
    report = machine.report(repo, brief, candidate)
    assert not report["errors"]
    assert {w["code"] for w in report["warnings"]} == {"phone-font", "numbers", "source-pattern", "invisible-edges", "alt-title"}


def test_symlink_source_is_never_read(repo, make_figure, tmp_path):
    brief, _ = make_figure()
    outside = tmp_path / "private"
    outside.write_text("private")
    (repo / "sources").symlink_to(tmp_path, target_is_directory=True)
    brief["source_image"] = {"path": "sources/private", "crop": [0, 0, 1, 1]}
    safefs.write_json(repo, ".school-notes/figures/forces.json", brief)
    with pytest.raises(safefs.UnsafePath):
        commissions.read(repo, "forces")


def test_marker_must_be_in_the_reviewed_section(repo, make_figure):
    brief, candidate = make_figure()
    text = safefs.read_text(repo, brief["page"]).replace("<!-- figure:", "# Another section\n\n<!-- figure:")
    safefs.write_text(repo, brief["page"], text)
    with pytest.raises(ValueError, match="outside"):
        context.verdict_key(repo, brief, candidate)


@pytest.mark.parametrize("kind", ["png", "svg"])
def test_no_direct_self_insertion_for_new_images(repo, make_figure, kind):
    from school_notes2.wiki.guard import Change, GuardInput, run
    brief, candidate = make_figure()
    page = brief["page"]
    asset = f"wiki/assets/physics/forces.{kind}"
    safefs.write_bytes(repo, asset, b"candidate")
    text = safefs.read_text(repo, page).replace("<!-- figure: forces -->", f"![force](../assets/physics/forces.{kind})")
    safefs.write_text(repo, page, text)
    problems = run(GuardInput(repo, [Change(page, "added")], lambda p: None))
    assert len(problems) == 1 and "independent acceptance" in problems[0].message


def test_mermaid_requires_commission_in_both_modes(repo, make_figure):
    from school_notes2.wiki.guard import Change, GuardInput, run
    brief, candidate = make_figure()
    page = brief["page"]
    safefs.write_text(repo, page, safefs.read_text(repo, page) + "```mermaid\ngraph LR\n A --> B\n```\n")
    for interactive in (False, True):
        g = GuardInput(repo, [Change(page, "added")], lambda p: None, interactive=interactive)
        assert "Mermaid" in run(g)[0].message
    candidate.pop("asset")
    candidate["mermaid"] = hashlib.sha256(b"graph LR\n A --> B\n").hexdigest()
    safefs.write_json(repo, ".school-notes/figures/forces/figure.json", candidate)
    assert not run(g)


def test_result_check_stays_valid_after_tool_insertion(repo, make_figure):
    from school_notes2.figures.insert import insert
    brief, candidate = make_figure()
    key = context.verdict_key(repo, brief, candidate)
    verdict = {"id": brief["id"], "key": key, "verdict": "accept", "observed": "Arrows",
               "defects": [], "text_mismatch": [], "relates_to": None}
    insert(repo, brief, {"status": "reviewed", "model": "reviewer/high",
                        "review": {"figures": [verdict], "owner_notes": []}}, at="date")
    assert not commissions.check(repo, [{k: brief[k] for k in ("id", "page", "kind")}])


@pytest.mark.parametrize("mutation", ["none", "source", "output", "schema"])
def test_render_receipt_is_a_hard_check(repo, make_figure, mutation):
    import hashlib
    brief, candidate = make_figure()
    source = "wiki/assets/physics/source.py"
    safefs.write_text(repo, source, "draw()")
    receipt = {"source": source, "source_sha256": hashlib.sha256(b"draw()").hexdigest(),
               "outputs": {"forces.png": {"sha256": hashlib.sha256(safefs.read_bytes(repo, candidate["asset"])).hexdigest()}}}
    if mutation == "source":
        safefs.write_text(repo, source, "changed()")
    if mutation == "output":
        safefs.write_bytes(repo, candidate["asset"], b"changed")
    if mutation == "schema":
        receipt["outputs"] = []
    candidate["render"] = "wiki/assets/physics/render.json"
    safefs.write_json(repo, candidate["render"], receipt)
    report = machine.report(repo, brief, candidate)
    assert bool(report["errors"]) == (mutation != "none")
    safefs.write_json(repo, ".school-notes/figures/forces/figure.json", candidate)
    assert bool(commissions.check(repo, [{k: brief[k] for k in ("id", "page", "kind")}])) == (mutation != "none")


def test_changed_asset_alone_cannot_bypass_independent_review(repo, make_figure):
    from school_notes2.wiki.guard import Change, GuardInput, run
    brief, candidate = make_figure()
    page, asset = brief["page"], candidate["asset"]
    safefs.write_text(repo, page, safefs.read_text(repo, page).replace("<!-- figure: forces -->", "![force](../assets/physics/forces.png)"))
    base = {p: safefs.read_bytes(repo, p) for p in safefs.walk_files(repo)}
    safefs.write_bytes(repo, asset, b"changed")
    found = run(GuardInput(repo, [Change(asset, "modified")], base.get))
    assert len(found) == 1 and found[0].path == page
