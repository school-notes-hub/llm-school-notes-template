"""Explicit, hash-bound image rights; evidence directories alone grant nothing."""

from pathlib import Path

from ..state import safefs
from .pages import sha256


def generated(repo, rel, proof=None):
    """Generation proof shared by legacy-header checks and candidate review."""
    if not rel or not safefs.is_file(repo, rel):
        return None
    evidence = (proof(rel) if proof else None, media(repo)(rel), lookup(repo, lambda _: None)(rel))
    return next((found for found in evidence if found and found[0] == "generated"), None)


def lookup(repo: Path, fallback, *, known=None, recorded=None):
    """Share publication inheritance and revocable-license precedence with preflight."""
    from ..figures import licenses
    if known is None:
        existing = safefs.read_json(repo, "publication/public.json", {})
        known = {a["path"]: a for a in existing.get("assets", [])}
    recorded = licenses.records(repo) if recorded is None else recorded

    def resolve(rel):
        if recorded.get(rel):
            return licenses.rights(repo, rel, recorded=recorded)
        old = known.get(rel)
        if old and old.get("sha256") == sha256(repo, rel) and old.get("rights") in (
                "authored", "generated", "public-domain", "standard", "licensed"):
            return old["rights"], old.get("rightsEvidence", "")
        return fallback(rel)
    return resolve


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

    compressed = compressed_records(repo, {digest for digest, _ in records})

    def lookup(rel):
        digest = sha256(repo, rel)
        for target, recorded, path in compressed:
            if target == rel and recorded == digest:
                return "generated", path
        for kind, entries in (("generated", records), ("authored", authored)):
            if kind == "authored" and not rel.endswith(".svg"):
                continue
            found = next(((kind, path) for recorded, path in sorted(entries, key=lambda r: r[1])
                          if recorded == digest), None)
            if found:
                return found
        return None
    return lookup


def writer_svgs(repo):
    def lookup(rel):
        return ("authored", "writer-svg") if writer_svg(repo, rel) else None
    return lookup


def writer_svg(repo, rel):
    """A writer-drawn SVG is authored (6b), unless it embeds another image or data."""
    if not rel.startswith("wiki/assets/") or not rel.endswith(".svg") or not safefs.is_file(repo, rel):
        return False
    text = safefs.read_text(repo, rel, errors="replace").lower()
    return "<image" not in text and "data:" not in text and "<foreignobject" not in text


def compressed_records(repo, generated):
    """v1 WebP receipts link published bytes to a proven generated original."""
    records = []
    for path in safefs.glob(repo, "docs/evidence", "docs/evidence/*-banner-compression.json"):
        value = safefs.read_json(repo, path, [])
        entries = value.get("images", []) if isinstance(value, dict) else value
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            original = entry.get("original_sha256", entry.get("source_sha256"))
            if original and original in generated:
                records.append((entry.get("published"), entry.get("published_sha256"), path))
    return records


def authored_candidate(repo: Path, candidate: dict) -> bool:
    """Decide own-SVG eligibility; `rights: authored` only documents this decision.

    The field itself grants no rights. Media lookup also requires an independent
    accept and the current output hash; raster authorship needs render.json.
    """
    asset, source = candidate.get("asset", ""), candidate.get("source", "")
    return (candidate.get("state") == "candidate" and asset.startswith("wiki/assets/") and
            asset.endswith(".svg") and source.startswith("wiki/assets/") and
            source.endswith(".svg") and safefs.is_file(repo, asset) and safefs.is_file(repo, source) and
            (source == asset or safefs.read_bytes(repo, source) == safefs.read_bytes(repo, asset)))


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
