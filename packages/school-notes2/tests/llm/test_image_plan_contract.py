"""The documented image plan must match the schema used before generation."""

import json
from importlib import resources
from pathlib import Path
import re

import pytest

from school_notes2 import schemas
from school_notes2.llm.argv import prompt

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("document", ["writer", "fix", "school-notes-run", "media-workflows"])
def test_image_plan_contract_and_example(document):
    is_prompt = document in ("writer", "fix")
    text = prompt(document, grade=9) if is_prompt else (ROOT / f"instructions/{document}.md").read_text()
    schema = json.loads(resources.files(schemas).joinpath("image-plan.json").read_text())
    required, optional = ("Kötelező mezők", "Opcionális mezők") if is_prompt else ("Required fields", "Optional fields")
    # These labels can occur in other contracts: select the image-plan paragraph.
    paragraph = next(p for p in text.split("\n\n") if "`image-plan.json`" in p)
    fields = lambda label: re.findall(r"`([^`]+)`", paragraph.split(label + ": ")[1].split(".")[0].split(";")[0])
    assert fields(required) == schema["required"]
    assert set(fields(optional)) == set(schema["properties"]) - set(schema["required"])
    for field in ("role", "aspect_ratio"):
        assert " | ".join(schema["properties"][field]["enum"]) in paragraph
    examples = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", text, re.S)]
    example = next(value for value in examples if value.get("role") == "banner")
    schemas.validate("image-plan", example)
    assert set(example) == set(schema["required"])
    separation = next(p for p in text.split("\n\n") if "`id`, `kind`, `page`, `purpose`" in p)
    assert "`.school-notes/figures/<id>.json`" in separation
    assert ("nem a képtervbe" if is_prompt else "never in the image plan") in separation
    assert "`decision_reason`" in paragraph and "`{code, text}`" in paragraph
