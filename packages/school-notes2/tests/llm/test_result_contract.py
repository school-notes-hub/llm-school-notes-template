"""The output prescribed by each prompt must be accepted by the result schema."""

import json
import re
from importlib.resources import files
from pathlib import Path

import pytest

from school_notes2.flows.writer import merge
from school_notes2.llm.argv import prompt
from school_notes2.schemas import SchemaError, validate

ROOT = Path(__file__).resolve().parents[4]
SOURCE = "sources/proba/ora/document.md"
TARGET = "wiki/proba/tema.md#fogalom"
ADDITIONS = {
    "figures": [{"id": "abra", "kind": "notebook-drawing", "page": "wiki/proba/tema.md"}],
    "notebook_drawings": [{"source": SOURCE, "crop": "bal felső rajz", "figure": "abra"}],
    "figure_requests": [{"id": "kep", "page": "wiki/proba/tema.md", "source": SOURCE,
                         "crop": "teljes kép", "purpose": "felismerés", "origin": "unknown"}],
    "warnings": [{"id": "wiki/proba/tema.md:hash:1", "action": "kept", "reason": "Megengedett."}],
    "coverage": [{"source": SOURCE, "unit": "definíció", "target": TARGET},
                 {"source": SOURCE, "unit": "díszkép", "reason": "Nincs tananyagértéke."}],
}


@pytest.mark.parametrize("role", ["writer", "fix"])
def test_all_output_fields_prescribed_by_prompt_exist_in_schema(role):
    schema = json.loads(files("school_notes2.schemas").joinpath("result.json").read_text())
    contract = prompt(role, grade=9).split("a futás szerződése: ")[1].split(". A pontos mezőket")[0]
    fields = {s.split(":")[0] for s in re.findall(r"`([^`]+)`", contract)}
    # Saved 2.5.x results may still carry these; the prompts no longer ask for them (#4, Fable 4).
    assert fields == set(schema["properties"]) - {"warnings", "infographic_decisions"}
    run = (ROOT / "instructions/school-notes-run.md").read_text()
    example = json.loads(run.split("```json\n")[1].split("\n```")[0])
    assert set(example) == fields
    for key, value in example.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            assert set(value[0]) <= set(schema["properties"][key]["items"]["properties"])
    closure = schema["properties"]["review_closure"]["items"]["properties"]
    assert {"question", "settled"} <= set(closure["status"]["enum"])
    assert {"question_id", "decision_id"} <= set(closure)


def test_additive_lists_validate_and_survive_merge():
    validate("result", {"status": "done"})
    data = {"status": "done", **ADDITIONS}
    validate("result", data)
    merged = merge([data, data])
    validate("result", merged)
    for key, values in ADDITIONS.items():
        assert merged[key] == (values if key == "warnings" else values + values)
    assert merged["checks"] == []  # coverage is not image evidence


@pytest.mark.parametrize("status,key", [("question", "question_id"), ("settled", "question_id"),
                                        ("settled", "decision_id")])
def test_additive_closure_contract(status, key):
    validate("result", {"status": "done", "review_closure": [
        {"file": "docs/review/a.md", "item_id": "R1", "status": status, key: "tema-kerdes"}]})


@pytest.mark.parametrize("changes", [{}, {"target": TARGET, "reason": "ignored"},
                                     {"target": "wiki/proba/tema.md"}, {"reason": " "}])
def test_coverage_requires_one_destination_or_omission_reason(changes):
    with pytest.raises(SchemaError):
        validate("result", {"status": "done", "coverage": [
            {"source": SOURCE, "unit": "fogalom", **changes}]})


@pytest.mark.parametrize("key", ADDITIONS)
def test_additive_records_reject_unknown_fields(key):
    with pytest.raises(SchemaError):
        validate("result", {"status": "done", key: [{**ADDITIONS[key][0], "unknown": True}]})
