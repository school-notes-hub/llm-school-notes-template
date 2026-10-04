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

CARD = {"role": "Mérnök-tanár", "conventions": ["x jobbra", "y lefelé"], "style": "Pontos rajz"}


def subjects(repo, card=CARD):
    (repo / "tools").mkdir(exist_ok=True)
    write_json(repo / "tools/subjects.json", {"subjects": {"statika": {"name": "Statika", "card": card}}})


def test_card_load_and_template_example(tmp_path):
    assert cards.load(tmp_path, "statika") is None
    subjects(tmp_path)
    assert cards.load(tmp_path, "statika") == CARD
    assert cards.load(tmp_path, "uj") is None
    example = Path(__file__).resolve().parents[4] / "examples/subject-card.json"
    validate("subject-card", json.loads(example.read_text()))


@pytest.mark.parametrize("card", [None, {}, {**CARD, "role": " "}, {**CARD, "style": ""},
                                  {**CARD, "conventions": "y lefelé"},
                                  {**CARD, "conventions": ["x", "x"]},
                                  {**CARD, "conventions": [""]}, {**CARD, "grade": 11}])
def test_invalid_cards_are_rejected(tmp_path, card):
    subjects(tmp_path, card)
    with pytest.raises(SchemaError):
        cards.load(tmp_path, "statika")


@pytest.mark.parametrize("student", ["benedek", "barna"])
def test_prepared_card_survives_reload_and_config_change(tmp_path, student):
    """T-095: no new phase; card input survives the existing preparation/resume boundary."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subjects(repo)
    doc = tmp_path / "document.md"
    doc.write_text("# Tananyag\n")
    placed = place_package(repo, Downloaded("Óra", "statika", "tanari", "", False, True,
                                            [record(doc, "document.md")]), 1, Known())
    task = phase.create(tmp_path / "tasks", student, "notes", "cron", "moved")
    task.set_phase("prepared", packages=[placed.package], pages=placed.pages, ranges=[[1, 1]])
    before = fetch_json(task, 1)
    assert before["packages"][0]["card"] == CARD
    subjects(repo, {**CARD, "role": "Új szerep"})
    restored = fetch_json(phase.load(task.dir), 1)
    assert json.dumps(restored, ensure_ascii=False) == json.dumps(before, ensure_ascii=False)
    restored["packages"][0]["card"]["style"] = ""
    with pytest.raises(SchemaError):
        validate("fetch", restored)


def test_symlinked_subject_config_is_not_read(tmp_path):
    from school_notes2.state.safefs import UnsafePath
    (tmp_path / "tools").mkdir()
    target = tmp_path / "outside.json"
    target.write_text('{"subjects": {}}')
    (tmp_path / "tools/subjects.json").symlink_to(target)
    with pytest.raises(UnsafePath):
        cards.load(tmp_path, "statika")
