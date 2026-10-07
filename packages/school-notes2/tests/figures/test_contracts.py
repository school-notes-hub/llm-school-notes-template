
import pytest

from school_notes2.figures import commissions, context
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
