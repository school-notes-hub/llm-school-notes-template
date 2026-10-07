"""Candidate preflight: what a figure must satisfy before the reviewer looks at it and before
`sn close` writes anything (`sn close --snapshot` and step 0 of `sn close`; a problem is a STOP).

Commission and candidate schema, the files it names, the marker inside the commission section,
the source crop within the source image, an editable source or a render receipt for an SVG,
a render receipt that binds the final bytes, generation proof for a banner or infographic, and a
rights path for every asset (a render, a generation record, an own SVG with an identical SVG
source, or a licensed request with current permission)."""

import hashlib
import io
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image

from ..state import safefs
from ..wiki import rights
from ..wiki.check import check_renders
from . import commissions, context, licenses


def problems(repo: Path, fid: str, *, generated=None) -> list[str]:
    """Every problem of figure `fid` (empty: it may go to review / be inserted). `generated(rel)`
    answers `("generated", proof)` for an output of the host image ledger."""
    try:
        brief = commissions.read(repo, fid)
        commissions.validate_assignments(repo, [{k: brief[k] for k in ("id", "page", "kind")}])
        candidate = commissions.candidate(repo, brief)
        if source := brief.get("source_image"):
            crop_within(safefs.read_bytes(repo, source["path"]), source["crop"])
        if candidate["state"] != "candidate":
            context.embedding(repo, brief, {"alt": "", "caption": ""})
            return [f"nincs jelölt: {candidate['state']} ({candidate.get('reason', '')})"]
        errors = files_and_rights(repo, brief, candidate, generated=generated)
        errors += generation_errors(repo, brief, candidate, generated)
        context.embedding(repo, brief, candidate)
        if not errors:
            context.verdict_key(repo, brief, candidate)
        return errors
    except (ValueError, OSError, KeyError) as exc:
        return [str(exc)]


def crop_within(data: bytes, crop: list[int]) -> None:
    with Image.open(io.BytesIO(data)) as image:
        if crop[2] > image.width or crop[3] > image.height:
            raise ValueError("source crop exceeds image bounds")


def files_and_rights(repo: Path, brief: dict, candidate: dict, *, generated=None) -> list[str]:
    asset, source, receipt = (candidate.get(k) for k in ("asset", "source", "render"))
    missing = [f"missing file: {rel}" for rel in sorted({r for r in (asset, source, receipt) if r})
               if not safefs.is_file(repo, rel)]
    if missing:
        return missing
    errors = []
    if asset and asset.endswith(".svg"):
        try:
            ElementTree.fromstring(safefs.read_text(repo, asset))
        except ElementTree.ParseError:
            errors.append("invalid SVG")
    if asset and not receipt:
        found = rights.rendered(repo)(asset)
        receipt = found[1] if found else None
    if receipt:
        errors += [i["message"] for i in check_renders(repo, [receipt])]
        if not errors:
            outputs = safefs.read_json(repo, receipt)["outputs"]
            name = Path(asset).name if asset else ""
            if (str(Path(receipt).parent / name) != asset or outputs.get(name, {}).get("sha256")
                    != hashlib.sha256(safefs.read_bytes(repo, asset)).hexdigest()):
                errors.append("candidate is not a hashed output of render.json")
    elif asset and asset.endswith(".svg") and not source:
        errors.append("SVG candidate needs editable source or render.json")
    if asset:
        request = licenses.request_for(repo, brief["id"])
        if request:
            licenses.candidate(repo, brief, candidate, request)       # raises without permission

        def fallback(rel):
            return (rights.rendered(repo)(rel) or rights.media(repo)(rel)
                    or (("authored", rel) if rights.authored_candidate(repo, candidate) else None)
                    or (generated(rel) if generated else None))
        if not request and not rights.lookup(repo, fallback)(asset):
            errors.append("candidate has no rights path: render the drawing with tools/visual_tools.py, "
                          "use a generation record or a licensed request, or an own SVG with an identical "
                          "SVG source under wiki/assets/")
    return errors


def generation_errors(repo: Path, brief: dict, candidate: dict, generated=None) -> list[str]:
    if brief["kind"] not in ("banner", "infographic"):
        return []
    asset = candidate.get("asset")
    proof = rights.generated(repo, asset, generated)
    if not asset or not asset.endswith(".webp") or not proof or proof[0] != "generated":
        return ["banner/infographic needs a generated .webp candidate with a generation receipt"]
    return []
