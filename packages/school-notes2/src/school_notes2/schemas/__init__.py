"""JSON Schemas of every contract (plan 4); every read and write is validated."""

import json
from functools import cache
from importlib import resources

import jsonschema
from referencing import Registry, Resource


class SchemaError(ValueError):
    pass


@cache
def _validator(name: str):
    text = resources.files(__package__).joinpath(f"{name}.json").read_text(encoding="utf-8")
    schema = json.loads(text)
    jsonschema.Draft202012Validator.check_schema(schema)
    card = json.loads(resources.files(__package__).joinpath("subject-card.json").read_text("utf-8"))
    registry = Registry().with_resource("urn:school-notes:subject-card", Resource.from_contents(card))
    return jsonschema.Draft202012Validator(schema, registry=registry)


def errors(name: str, value) -> list[str]:
    found = sorted(_validator(name).iter_errors(value), key=lambda e: list(e.path))
    return [f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in found]


def validate(name: str, value) -> None:
    problems = errors(name, value)
    if problems:
        raise SchemaError(f"{name}: " + "; ".join(problems[:10]))
