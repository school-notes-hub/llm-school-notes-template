"""sn 0.4.1 `sn close` fixes found live on 2026-10-10 (each test fails on fd6ad0d):

* a replacing figure (`replaces`): the „[Az ábra megnyitása nagy méretben](…)” link to the old
  asset was rewritten to the new one before the key check, so the reviewed key no longer matched
  („stale verdict key”) and the page stayed half written (Benedek, `okori-kelet-terkep-20261010`).
"""

import io

import pytest
from PIL import Image

from school_notes2.figures import insert
from school_notes2.local import close, done
from school_notes2.state import safefs
from tests.local.conftest import git
from tests.local.test_close import ACCEPT, PAGE, handoff, learner_tree, quiet  # noqa: F401

OLD = "wiki/assets/physics/old.png"


def replacing(repo, make_figure):
    """The page as the writer leaves it: the old figure (committed), its open-large link, the
    new figure's marker."""
    image = io.BytesIO()
    Image.new("RGB", (800, 400), "white").save(image, format="PNG")
    safefs.write_bytes(repo, OLD, image.getvalue())
    safefs.write_text(repo, PAGE, safefs.read_text(repo, PAGE) + "![Old arrows](../assets/physics/old.png)\n\n"
                      "[Az ábra megnyitása nagy méretben](../assets/physics/old.png)\n\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "old figure")
    make_figure(replaces=OLD, decision_reason={"code": "a", "text": "The old figure is out of date."})
    handoff(repo, [{"id": "forces", "page": PAGE, "route": "figure", "replaces": OLD}], {"forces": ACCEPT})


def test_a_replacing_figure_goes_in_with_the_key_its_snapshot_had_and_its_link_follows(
        repo, make_figure, fake_local):
    replacing(repo, make_figure)
    local = fake_local(repo)
    out = []
    assert close.snapshot(local, None, None, out.append) == 0, out
    lines = []
    assert close.close(local, repo, None, lines.append) == 0, lines
    text = safefs.read_text(repo, PAGE)
    assert "school-notes:generated figure-forces" in text and "<!-- figure: forces -->" not in text
    assert "[Az ábra megnyitása nagy méretben](<../assets/physics/forces.png>)" in text
    assert "../assets/physics/old.png" not in text
    assert insert.invalidated(repo) == []                        # the recorded key is the page's key
    assert not any("stale" in p for _, problems in done.problems(repo, local.git()) for p in problems)


def test_a_failing_insertion_leaves_the_page_as_it_was(repo, make_figure, fake_local, monkeypatch):
    replacing(repo, make_figure)
    local = fake_local(repo)
    assert close.snapshot(local, None, None, quiet) == 0
    before = safefs.read_text(repo, PAGE)

    def broken(*args, **kwargs):
        raise ValueError("forces: stale verdict key")
    monkeypatch.setattr(insert, "insert", broken)
    with pytest.raises(ValueError):
        close.close(local, repo, None, quiet)
    assert safefs.read_text(repo, PAGE) == before


@pytest.mark.parametrize("first", ["forces", "torque"])
def test_a_replacing_figure_and_another_in_the_same_section_both_go_in(repo, make_figure, fake_local, first):
    """Review of 0.4.1 (M2): the open-large link is section text of every figure there; its target
    is the tool's and is not part of any verdict key, so the rewrite invalidates neither."""
    replacing(repo, make_figure)
    make_figure(fid="torque")
    entries = {"forces": {"id": "forces", "page": PAGE, "route": "figure", "replaces": OLD},
               "torque": {"id": "torque", "page": PAGE, "route": "figure"}}
    order = [first] + [f for f in entries if f != first]
    handoff(repo, [entries[f] for f in order], {"forces": ACCEPT, "torque": ACCEPT})
    local = fake_local(repo)
    out = []
    assert close.snapshot(local, None, None, out.append) == 0, out
    lines = []
    assert close.close(local, repo, None, lines.append) == 0, lines
    text = safefs.read_text(repo, PAGE)
    assert "school-notes:generated figure-forces" in text and "school-notes:generated figure-torque" in text
    assert "[Az ábra megnyitása nagy méretben](<../assets/physics/forces.png>)" in text
    assert insert.invalidated(repo) == []


def test_a_verdict_with_the_040_key_stays_valid_and_is_renewed(repo, make_figure, fake_local):
    """The open-large link's target left the key in 0.4.1: a verdict recorded with the 0.4.0 key
    (target in it) is still valid and `rekey` gives it the current key, nothing else changes."""
    from school_notes2.figures import context
    replacing(repo, make_figure)
    local = fake_local(repo)
    assert close.snapshot(local, None, None, quiet) == 0
    assert close.close(local, repo, None, quiet) == 0
    records = safefs.read_json(repo, insert.VERDICTS)
    [record] = [r for r in records if r.get("id") == "forces"]
    current = record["key"]
    old = context.verdict_key(repo, record["commission"], record["candidate"], legacy="0.4.0")
    assert old != current
    record["key"] = old
    safefs.write_json(repo, insert.VERDICTS, records)
    evidence = safefs.read_json(repo, "docs/evidence/media/forces/figure.json")
    safefs.write_json(repo, "docs/evidence/media/forces/figure.json",
                      {**evidence, "verdict": {**evidence["verdict"], "key": old}})
    assert insert.invalidated(repo) == []
    assert sorted(context.rekey(repo)) == ["docs/evidence/media/forces/figure.json", insert.VERDICTS]
    assert [r["key"] for r in safefs.read_json(repo, insert.VERDICTS) if r.get("id") == "forces"] == [current]
