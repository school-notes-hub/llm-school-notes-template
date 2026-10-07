"""The read-only content facts `sn done` counts (local/places.py) and the generation ledger
receipt `sn close` writes (local/close.py)."""

from types import SimpleNamespace

from school_notes2.local import places
from school_notes2.local.close import generation_outputs
from school_notes2.state import safefs
from tests.figures.conftest import add_pending

PAGE = "wiki/physics/forces.md"


def test_a_figure_place_without_an_accepted_figure_is_missing_and_orphan(repo, make_figure):
    brief, _ = make_figure()
    assert places.missing_parts(repo) == ({"forces"}, set())
    assert places.orphan_places(repo) == [{"id": "forces", "page": PAGE, "line": 10,
                                           "quote": "<!-- figure: forces -->"}]


def test_a_queued_figure_is_missing_but_no_orphan(repo, make_figure):
    brief, _ = make_figure()
    add_pending(repo, brief)
    assert places.missing_parts(repo)[0] == {"forces"}
    assert places.orphan_places(repo) == []


def test_a_figure_request_marker_is_never_an_orphan(repo, make_figure):
    brief, _ = make_figure()
    text = safefs.read_text(repo, PAGE).replace("<!-- figure:", "<!-- figure-request:")
    safefs.write_text(repo, PAGE, text)
    assert places.orphan_places(repo) == []


def test_places_are_one_per_page_and_id_in_content_order(repo, make_figure):
    make_figure("b-fig")
    make_figure("a-fig")
    safefs.write_text(repo, PAGE, safefs.read_text(repo, PAGE) + "<!-- figure: a-fig -->\n")
    found = places.orphan_places(repo)
    assert [(p["id"], p["line"]) for p in found] == [("b-fig", 10), ("a-fig", 12)]


def test_a_broken_image_link_is_counted(repo, make_figure):
    make_figure()
    safefs.write_text(repo, "wiki/physics/other.md", "---\ntitle: O\n---\n# O\n\n![x](../assets/physics/none.png)\n")
    assert places.missing_parts(repo)[1] == {"wiki/assets/physics/none.png"}


def test_a_textbook_line_without_a_number_is_listed_once_per_page(repo):
    safefs.write_text(repo, "wiki/physics/a.md", "# A\n\n🔖 Tankönyv: a lecke még nincs azonosítva\n\n🔖 Tankönyv: x\n")
    safefs.write_text(repo, "wiki/physics/b.md", "# B\n\n🔖 Tankönyv: 12. lecke, 48. oldal\n")
    safefs.write_text(repo, "wiki/physics/index.md", "# Fizika\n\n🔖 Tankönyv: a jelmagyarázat\n")
    assert places.textbook_lines(repo) == [
        {"page": "wiki/physics/a.md", "line": 3, "quote": "🔖 Tankönyv: a lecke még nincs azonosítva"}]


def test_generation_receipt_lists_only_this_learners_produced_images_sorted():
    attempt = lambda state, sha, preview=None: {"state": state, "sha256": sha, "preview_sha256": preview}
    ledger = {"jobs": {
        "barna-a": {"learner": "barna", "attempts": [attempt("generated", "c", "b"), attempt("failed", "x"),
                                                     attempt("rejected", "a"), attempt("unknown", "y")]},
        "barna-b": {"learner": "barna", "attempts": [attempt("accepted", "a")]},
        "benedek-a": {"learner": "benedek", "attempts": [attempt("generated", "z")]}}}
    settings = SimpleNamespace(learner="barna", ledger=lambda: ledger)
    assert generation_outputs(settings) == ["a", "b", "c"]
