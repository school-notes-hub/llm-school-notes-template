import json
from pathlib import Path

import pytest

from school_notes2.flows.fetch import fetch_json
from school_notes2.schemas import SchemaError, validate
from school_notes2.sources import cards
from school_notes2.sources.duplicates import Known
from school_notes2.sources.place import Downloaded, place_package
from school_notes2.state import phase
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
    """A `card` left in a learner's tools/subjects.json never reaches fetch.json."""
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    write_json(repo / "tools/subjects.json",
               {"subjects": {"statika": {"name": "Statika", "card": {**CARD, "role": "Saját"}}}})
    doc = tmp_path / "document.md"
    doc.write_text("# Tananyag\n")
    placed = place_package(repo, Downloaded("Óra", "statika", "tanari", "", False, True,
                                            [record(doc, "document.md")]), 1, Known())
    assert "card" not in placed.package
    task = phase.create(tmp_path / "tasks", student, "notes", "cron", "moved")
    task.set_phase("prepared", packages=[placed.package], pages=placed.pages, ranges=[[1, 1]])
    assert "card" not in fetch_json(task, 1, grade=9)["packages"][0]
    shared(repo)
    assert cards.load(repo, "statika") == CARD


@pytest.mark.parametrize("student", LEARNERS)
def test_prepared_card_survives_reload_and_card_file_change(tmp_path, student):
    """T-095: no new phase; card input survives the existing preparation/resume boundary."""
    repo = tmp_path / "repo"
    repo.mkdir()
    shared(repo)
    doc = tmp_path / "document.md"
    doc.write_text("# Tananyag\n")
    placed = place_package(repo, Downloaded("Óra", "statika", "tanari", "", False, True,
                                            [record(doc, "document.md")]), 1, Known())
    task = phase.create(tmp_path / "tasks", student, "notes", "cron", "moved")
    task.set_phase("prepared", packages=[placed.package], pages=placed.pages, ranges=[[1, 1]])
    before = fetch_json(task, 1, grade=11)
    assert before["packages"][0]["card"] == CARD
    assert before["learner"] == {"grade": 11}
    shared(repo, {"statika": {**CARD, "role": "Új szerep"}})
    restored = fetch_json(phase.load(task.dir), 1, grade=11)
    assert json.dumps(restored, ensure_ascii=False) == json.dumps(before, ensure_ascii=False)
    restored["packages"][0]["card"]["style"] = ""
    with pytest.raises(SchemaError):
        validate("fetch", restored)


@pytest.mark.parametrize("grade", [0, -1, "9", None])
def test_fetch_requires_a_positive_grade(tmp_path, grade):
    task = phase.create(tmp_path / "tasks", "proba", "notes", "cron", "moved")
    task.set_phase("prepared", packages=[], pages=[], ranges=[[0, 0]])
    with pytest.raises(SchemaError):
        fetch_json(task, 1, grade=grade)


def test_missing_cards_are_listed_in_name_order(tmp_path):
    assert cards.missing(tmp_path, {"b", "a"}) == ["a", "b"]
    shared(tmp_path, {"a": CARD})
    assert cards.missing(tmp_path, ["b", "a", "c"]) == ["b", "c"]


def test_symlinked_card_file_is_not_read(tmp_path):
    from school_notes2.state.safefs import UnsafePath
    target = tmp_path / "outside.json"
    target.write_text('{"cards": {}}')
    (tmp_path / cards.PATH).symlink_to(target)
    with pytest.raises(UnsafePath):
        cards.load(tmp_path, "statika")
