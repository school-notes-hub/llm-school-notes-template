"""The reviewer's verdicts are checked against the current content before any insertion."""

import pytest

from school_notes2.figures import context, review


def response(assigned, verdict="accept", defects=()):
    return {"figures": [{**item, "verdict": verdict, "observed": "Two opposing arrows.",
                         "defects": list(defects), "text_mismatch": [], "relates_to": None}
                        for item in assigned["figures"]], "owner_notes": []}


@pytest.mark.parametrize("failure", ["missing", "duplicate", "extra", "key"])
def test_review_completeness_and_hash(repo, make_figure, failure):
    brief, candidate = make_figure()
    assigned = {"figures": [{"id": brief["id"], "key": context.verdict_key(repo, brief, candidate)}]}
    value = response(assigned)
    if failure == "missing":
        value["figures"] = []
    if failure == "duplicate":
        value["figures"] *= 2
    if failure == "extra":
        value["figures"].append({**value["figures"][0], "id": "extra"})
    if failure == "key":
        value["figures"][0]["key"] = "0" * 64
    with pytest.raises(ValueError):
        review.validate_output(value, assigned, repo, [brief])


DEFECT = {"severity": "hiba", "location": "the left arrow", "observed": "the arrow points left", "expected": "it points right"}


@pytest.mark.parametrize("verdict, defects, error", [
    ("accept", [], None),
    ("accept", [DEFECT], "accept cannot contain"),
    ("repair", [], "requires a hiba"),
    ("reject", [{**DEFECT, "severity": "javaslat"}], "requires a hiba"),
    ("repair", [DEFECT], None),
])
def test_an_accept_has_no_error_and_a_rejection_names_one(repo, make_figure, verdict, defects, error):
    brief, candidate = make_figure()
    assigned = {"figures": [{"id": brief["id"], "key": context.verdict_key(repo, brief, candidate)}]}
    value = response(assigned, verdict, defects)
    if error is None:
        review.validate_output(value, assigned, repo, [brief])
    else:
        with pytest.raises(ValueError, match=error):
            review.validate_output(value, assigned, repo, [brief])


def test_only_hiba_findings_travel_with_the_verdict():
    receipt = {"review": {"figures": [{"id": "a", "verdict": "repair", "defects": [
        DEFECT, {**DEFECT, "severity": "javaslat"}], "text_mismatch": []}]}}
    assert review.verdict_for(receipt, "a")["defects"] == [DEFECT]
    assert review.verdict_for(receipt, "b") == {}
    assert review.is_error({"observed": "an old receipt without severity"})
