"""Explicit, hash-bound image rights; evidence directories alone grant nothing."""

from pathlib import Path

from ..state import safefs
from .pages import sha256


def media(repo: Path):
    records = []
    for path in safefs.glob(repo, "docs/evidence/media", "docs/evidence/media/**/review-*.json"):
        value = safefs.read_json(repo, path, {})
        if value.get("decision") == "accepted":
            digest = value.get("publication", {}).get("sha256", value.get("sha256"))
            records.append((digest, path))
    for path in safefs.glob(repo, "docs/evidence/image-generation", "docs/evidence/image-generation/*.json"):
        value = safefs.read_json(repo, path, {})
        if value.get("rights") == "generated":
            records.extend((digest, path) for digest in value.get("outputs", []))
    # New independent reviews record the actual published bytes, not a filename stem.
    for path in safefs.glob(repo, "docs/evidence/media", "docs/evidence/media/**/figure.json"):
        value = safefs.read_json(repo, path, {})
        if value.get("verdict", {}).get("verdict") == "accept" and value.get("rights") == "generated":
            records.append((value.get("output_sha256"), path))

    def lookup(rel):
        digest = sha256(repo, rel)
        return next((("generated", path) for recorded, path in sorted(records, key=lambda r: r[1])
                     if recorded == digest), None)
    return lookup


def rendered(repo: Path):
    records = []
    for path in safefs.glob(repo, "wiki/assets", "wiki/assets/**/render.json"):
        try:
            value = safefs.read_json(repo, path, {})
        except (OSError, ValueError):
            continue
        outputs = value.get("outputs", {})
        if not isinstance(outputs, dict):
            continue
        for name, output in sorted(outputs.items()):
            if isinstance(output, dict):
                records.append((f"{path.rsplit('/', 1)[0]}/{name}", output.get("sha256"), path))

    def lookup(rel):
        digest = sha256(repo, rel)
        return next((("authored", path) for target, recorded, path in records
                     if target == rel and recorded == digest), None)
    return lookup
