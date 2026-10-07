import json
from pathlib import Path

import pytest

from school_notes2.schemas import SchemaError, validate
from school_notes2.sources import cards
from school_notes2.sources.duplicates import Known
from school_notes2.sources.place import Downloaded, place_package
from school_notes2.state.files import write_json
from tests.sources.test_sources import record

CARD = {"role": "Szaktanár.", "style": "Pontos ábra."}
# Two real learners and a synthetic third: the cards are the same for anyone (G-19).
LEARNERS = ["benedek", "barna", "proba"]
TEMPLATE = Path(__file__).resolve().parents[4]


def shared(repo, entries=None):
    """The template's shared card file, as synced into a learner repo."""
    write_json(repo / cards.PATH, {"cards": {"statika": CARD} if entries is None else entries})


def test_card_load_and_template_file(tmp_path):
    assert cards.load(tmp_path, "statika") is None
    shared(tmp_path)
    assert cards.load(tmp_path, "statika") == CARD
    assert cards.load(tmp_path, "uj") is None
    validate("subject-cards", json.loads((TEMPLATE / cards.PATH).read_text()))
    assert cards.PATH in json.loads((TEMPLATE / "shared-files.json").read_text())["files"]
    assert not (TEMPLATE / "examples/subject-card.json").exists()


def test_card_schema_has_no_taught_conventions():
    schema = json.loads((TEMPLATE / "packages/school-notes2/src/school_notes2/schemas"
                         / "subject-card.json").read_text())
    assert set(schema["properties"]) == {"role", "style"}
    assert schema["required"] == ["role", "style"]


@pytest.mark.parametrize("card", [None, {}, {**CARD, "role": " "}, {**CARD, "style": ""},
                                  {**CARD, "conventions": []}, {**CARD, "grade": 11}])
def test_invalid_cards_are_rejected(tmp_path, card):
    shared(tmp_path, {"statika": card})
    with pytest.raises(SchemaError):
        cards.load(tmp_path, "statika")


@pytest.mark.parametrize("data", [{}, {"cards": []}, {"cards": {"Statika": CARD}},
                                  {"cards": {}, "extra": 1}])
def test_invalid_card_file_is_rejected(tmp_path, data):
    write_json(tmp_path / cards.PATH, data)
    with pytest.raises(SchemaError):
        cards.load(tmp_path, "statika")


@pytest.mark.parametrize("student", LEARNERS)
def test_learner_subjects_card_has_no_effect(tmp_path, student):
    """A `card` left in a learner's tools/subjects.json never reaches the placed package."""
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    write_json(repo / "tools/subjects.json",
               {"subjects": {"statika": {"name": "Statika", "card": {**CARD, "role": "Saját"}}}})
    doc = tmp_path / "document.md"
    doc.write_text("# Tananyag\n")
    placed = place_package(repo, Downloaded("Óra", "statika", "tanari", "", False, True,
                                            [record(doc, "document.md")]), 1, Known())
    assert "card" not in placed.package
    shared(repo)
    assert cards.load(repo, "statika") == CARD


@pytest.mark.parametrize("student", LEARNERS)
def test_the_shared_card_is_snapshot_into_the_placed_package(tmp_path, student):
    repo = tmp_path / "repo"
    repo.mkdir()
    shared(repo)
    doc = tmp_path / "document.md"
    doc.write_text("# Tananyag\n")
    placed = place_package(repo, Downloaded("Óra", "statika", "tanari", "", False, True,
                                            [record(doc, "document.md")]), 1, Known())
    assert placed.package["card"] == CARD
    validate("subject-card", placed.package["card"])


def test_symlinked_card_file_is_not_read(tmp_path):
    from school_notes2.state.safefs import UnsafePath
    target = tmp_path / "outside.json"
    target.write_text('{"cards": {}}')
    (tmp_path / cards.PATH).symlink_to(target)
    with pytest.raises(UnsafePath):
        cards.load(tmp_path, "statika")
