"""Regressions from the independent unit 2a review (K-1 through K-12)."""

import hashlib

import pytest

from school_notes2.figures import commissions, context, insert
from school_notes2.state import safefs
from tests.figures.conftest import add_pending
from school_notes2.wiki import markers
from school_notes2.wiki.check import check_links
from test_insert import receipt


def assignment(brief):
    return {k: brief[k] for k in ("id", "page", "kind")}


@pytest.mark.parametrize("prefix,suffix", [("- ", ""), ("  ", ""), ("Text ", ""), ("", " text")])
def test_marker_must_be_its_own_unindented_line(repo, make_figure, prefix, suffix):
    brief, _ = make_figure()
    text = safefs.read_text(repo, brief["page"]).replace("<!-- figure: forces -->", prefix + "<!-- figure: forces -->" + suffix)
    safefs.write_text(repo, brief["page"], text)
    with pytest.raises(ValueError, match="stand alone"):
        commissions.validate_assignments(repo, [assignment(brief)])


@pytest.mark.parametrize("record", ["accepted", "pending", "block"])
def test_id_cannot_be_reused_on_another_page(repo, make_figure, record):
    old, candidate = make_figure()
    if record == "accepted":
        insert.insert(repo, old, receipt(repo, old, candidate), at="date")
    elif record == "pending":
        add_pending(repo, old)
        safefs.write_text(repo, old["page"], "# Forces\n")
    else:
        safefs.write_text(repo, old["page"], markers.wrap("figure-forces", "old"))
    brief, _ = make_figure(page="wiki/physics/other.md")
    with pytest.raises(ValueError, match="already"):
        commissions.validate_assignments(repo, [assignment(brief)])
    with pytest.raises(ValueError, match="already"):
        commissions.check_identity(repo, brief)


def test_two_replacements_in_one_section_survive_insertion_and_resume(repo, make_figure):
    pairs = []
    for fid in ("first", "second"):
        asset = f"wiki/assets/physics/old-{fid}.png"
        safefs.write_bytes(repo, asset, b"old")
        brief, candidate = make_figure(fid, replaces=asset, decision_reason={"code": "c", "text": "correction"})
        text = safefs.read_text(repo, brief["page"])
        safefs.write_text(repo, brief["page"], text + f"![old](../assets/physics/old-{fid}.png)\n\n<!-- image-description\nobserved: old\n-->\n")
        pairs.append((brief, candidate))
    judged = [receipt(repo, b, c) for b, c in pairs]
    for (brief, _), result in zip(pairs, judged):
        insert.insert(repo, brief, result, at="date")
    for (brief, _), result in zip(pairs, judged):
        insert.insert(repo, brief, result, at="date")
    assert not insert.invalidated(repo)
    assert len(markers.names(safefs.read_text(repo, pairs[0][0]["page"]))) == 2


def test_other_use_machine_blocks_do_not_change_key(repo, make_figure):
    brief, candidate = make_figure()
    page = "wiki/physics/other.md"
    text = "# Other\n\nContext.\n\n![force](../assets/physics/forces.png)\n"
    safefs.write_text(repo, page, text)
    key = context.verdict_key(repo, brief, candidate)
    safefs.write_text(repo, page, text + markers.wrap("pending", "Pending") + markers.wrap("figure-other", "image"))
    assert context.verdict_key(repo, brief, candidate) == key
    safefs.write_text(repo, page, text.replace("Context.", "Different context."))
    assert context.verdict_key(repo, brief, candidate) != key


def test_mermaid_reordering_keeps_keys(repo, make_figure):
    brief, candidate = make_figure()
    source = "graph LR\n A --> B\n"
    candidate.pop("asset")
    candidate["mermaid"] = hashlib.sha256(source.encode()).hexdigest()
    safefs.write_json(repo, ".school-notes/figures/forces/figure.json", candidate)
    text = safefs.read_text(repo, brief["page"]) + f"```mermaid\n{source}```\n"
    safefs.write_text(repo, brief["page"], text)
    insert.insert(repo, brief, receipt(repo, brief, candidate), at="date")
    extra = "# Other\n\n```mermaid\ngraph LR\n C --> D\n```\n\n"
    old = text + "\n" + extra
    new = extra + text
    safefs.write_text(repo, brief["page"], old)
    assert not insert.invalidated(repo)
    safefs.write_text(repo, brief["page"], new)
    assert not insert.invalidated(repo)


@pytest.mark.parametrize("target", ["force.svg", "https://example.org/a.png", "//example.org/a.png", "data:image/png;base64,eA=="])
def test_check_refuses_non_asset_images(repo, target):
    assert check_links(repo, "wiki/physics/forces.md", f"![force]({target})")


def test_other_use_caption_is_bound_even_in_a_generated_block(repo, make_figure):
    brief, candidate = make_figure()
    page = "wiki/physics/other.md"
    body = "![force](<../assets/physics/forces.png>)\n\nOther caption.\n\n<!-- image-description\nobserved: force\n-->"
    text = "# Other\n\nContext.\n\n" + markers.wrap("figure-other", body)
    safefs.write_text(repo, page, text)
    key = context.verdict_key(repo, brief, candidate)
    safefs.write_text(repo, page, text.replace("Other caption.", "A changed claim."))
    assert context.verdict_key(repo, brief, candidate) != key
