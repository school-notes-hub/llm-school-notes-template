"""An old asset is not permission to add an unreviewed image link."""

import pytest

from school_notes2.figures import insert
from school_notes2.state import safefs
from school_notes2.wiki.guard import Change, GuardInput, parts_hash, run
from school_notes2.wiki.pages import sha256
from test_insert import receipt


@pytest.mark.parametrize("verdict", [None, "reject", "repair"])
@pytest.mark.parametrize("tool_asset", [False, True])
def test_old_unaccepted_asset_cannot_be_newly_embedded(repo, make_figure, verdict, tool_asset):
    brief, candidate = make_figure()
    page, asset = brief["page"], candidate["asset"]
    if verdict:
        safefs.write_json(repo, "docs/evidence/media/forces/figure.json", {
            "commission": brief, "candidate": candidate, "output_sha256": sha256(repo, asset),
            "verdict": receipt(repo, brief, candidate, verdict)["review"]["figures"][0]})
    base = {p: safefs.read_bytes(repo, p) for p in safefs.walk_files(repo)}
    safefs.write_text(repo, page, safefs.read_text(repo, page).replace(
        "<!-- figure: forces -->", "![force](../assets/physics/forces.png)"))
    problems = run(GuardInput(repo, [Change(page, "modified")], base.get,
                              tool_files={asset: sha256(repo, asset)} if tool_asset else {}))
    assert len(problems) == 1
    assert "independent acceptance" in problems[0].message and not problems[0].owner


def test_unchanged_legacy_link_survives_page_edit(repo, make_figure):
    brief, _ = make_figure()
    page = brief["page"]
    safefs.write_text(repo, page, safefs.read_text(repo, page).replace(
        "<!-- figure: forces -->", "![force](../assets/physics/forces.png)"))
    base = {p: safefs.read_bytes(repo, p) for p in safefs.walk_files(repo)}
    safefs.write_text(repo, page, safefs.read_text(repo, page) + "More teaching text.\n")
    assert not run(GuardInput(repo, [Change(page, "modified")], base.get))


@pytest.mark.parametrize("outside", [False, True])
def test_acceptance_only_allows_links_inside_its_block(repo, make_figure, outside):
    brief, candidate = make_figure()
    page = brief["page"]
    base = {p: safefs.read_bytes(repo, p) for p in safefs.walk_files(repo)}
    insert.insert(repo, brief, receipt(repo, brief, candidate), at="date")
    text = safefs.read_text(repo, page)
    if outside:
        text += "\n![force](../assets/physics/forces.png)\n"
        safefs.write_text(repo, page, text)
    problems = run(GuardInput(repo, [Change(page, "modified")], base.get,
                              tool_parts={page: parts_hash(text)}))
    assert bool(problems) == outside
