"""Explicit, hash-bound image rights; evidence directories alone grant nothing."""

from pathlib import Path

from ..state import safefs
from .pages import sha256


def media(repo: Path):
    records = []
    authored = []
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
        if value.get("verdict", {}).get("verdict") != "accept":
            continue
        if value.get("rights") == "generated":
            records.append((value.get("output_sha256"), path))
        elif (value.get("rights") in (None, "authored") and
              not value.get("license_request") and not value.get("license") and
              authored_candidate(repo, value.get("candidate", {}))):
            authored.append((value.get("output_sha256"), path))

    def lookup(rel):
        digest = sha256(repo, rel)
        for kind, entries in (("generated", records), ("authored", authored)):
            found = next(((kind, path) for recorded, path in sorted(entries, key=lambda r: r[1])
                          if recorded == digest), None)
            if found:
                return found
        return None
    return lookup


def authored_candidate(repo: Path, candidate: dict) -> bool:
    """A local editable source identifies the writer's own, non-licensed candidate."""
    asset, source = candidate.get("asset", ""), candidate.get("source", "")
    return (candidate.get("state") == "candidate" and asset.startswith("wiki/assets/") and
            source.startswith("wiki/assets/") and safefs.is_file(repo, source))


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
