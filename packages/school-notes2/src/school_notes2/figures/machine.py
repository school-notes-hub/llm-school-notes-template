"""Hard file/render checks and non-blocking hints for the independent figure reviewer."""

import hashlib
import re
from pathlib import Path
from xml.etree import ElementTree

from ..state import safefs
from ..wiki.check import check_renders
from ..wiki import frontmatter, rights
from . import context, licenses

NUMBER = re.compile(r"(?<![\w#])[-+]?\d+(?:[.,]\d+)?")


def report(repo: Path, brief: dict, candidate: dict, *, generated=None, request=None) -> dict:
    errors, warnings = [], []
    asset = candidate.get("asset")
    source = candidate.get("source")
    receipt = candidate.get("render")
    for rel in sorted({r for r in (asset, source, receipt) if r}):
        if not safefs.is_file(repo, rel):
            errors.append(f"missing file: {rel}")
    if errors:
        return {"errors": errors, "warnings": warnings}
    errors.extend(rights_errors(repo, brief, candidate, generated=generated, request=request))
    if source:
        source_text = safefs.read_text(repo, source)
        edges = re.findall(r"(?:->|--)\s*[^;\n]+", source_text)
        if edges and all(re.search(r"style\s*=\s*[\"']?invis", edge) for edge in edges):
            warnings.append({"code": "invisible-edges", "message": "Every Graphviz edge is invisible"})
    if asset and Path(asset).suffix == ".svg":
        try:
            warnings += svg_hints(safefs.read_text(repo, asset), brief,
                                  context.embedding(repo, brief, candidate))
        except ElementTree.ParseError:
            errors.append("invalid SVG")
    meta = frontmatter.split(safefs.read_text(repo, brief["page"])).meta
    if candidate["alt"] == meta.get("title"):
        warnings.append({"code": "alt-title", "message": "alt equals page title"})
    return {"errors": sorted(errors), "warnings": sorted(warnings, key=lambda w: w["code"])}


def rights_errors(repo, brief, candidate, *, generated=None, request=None):
    """Resolve a candidate's publication route before spending a review call."""
    def fallback(rel):
        return (rights.rendered(repo)(rel) or rights.media(repo)(rel) or
                (("authored", rel) if rights.authored_candidate(repo, candidate) else None) or
                (generated(rel) if generated else None))

    asset, source, receipt = (candidate.get(k) for k in ("asset", "source", "render"))
    errors = []
    if asset and not receipt:
        rendered = rights.rendered(repo)(asset)
        receipt = rendered[1] if rendered else None
    if receipt:
        errors.extend(i["message"] for i in check_renders(repo, [receipt]))
        if not errors:
            data = safefs.read_json(repo, receipt)
            name = Path(asset).name if asset else ""
            entry = data["outputs"].get(name, {})
            if (str(Path(receipt).parent / name) != asset or
                    entry.get("sha256") != hashlib.sha256(safefs.read_bytes(repo, asset)).hexdigest()):
                errors.append("candidate is not a hashed output of render.json")
    elif asset and Path(asset).suffix == ".svg":
        if not source:
            errors.append("SVG candidate needs editable source or render.json")
    if asset:
        request = request or licenses.request_for(repo, brief["id"])
        if request:
            licenses.candidate(repo, brief, candidate, request)
        elif not rights.lookup(repo, fallback)(asset):
            errors.append("candidate has no rights path: render the drawing with tools/visual_tools.py, "
                          "use a generation record or licensed request, or use an own SVG with an "
                          "identical SVG source under wiki/assets/")
    return errors


def svg_hints(text: str, brief: dict, embedding: dict) -> list[dict]:
    root = ElementTree.fromstring(text)
    labels = " ".join("".join(e.itertext()) for e in root.iter() if e.tag.split("}")[-1] == "text")
    warnings = []
    try:
        width = float(re.split(r"[\s,]+", root.get("viewBox", "").strip())[2])
    except (ValueError, IndexError):
        width = 0
    if not width:
        match = re.match(r"[\d.]+", root.get("width", "0"))
        try:
            width = float(match[0]) if match else 0
        except ValueError:
            width = 0
    sizes = [float(n) for n in re.findall(r"font-size[=:]\s*[\"']?(\d+(?:\.\d+)?)", text)]
    if sizes and width and min(sizes) * 390 / width < 12:
        warnings.append({"code": "phone-font", "message": "Projected smallest font below 12 px",
                         "px": round(min(sizes) * 390 / width, 2)})
    expected = " ".join(brief["must_show"]) + " " + embedding.get("section", "")
    extra = sorted(set(NUMBER.findall(labels)) - set(NUMBER.findall(expected)))
    if extra:
        warnings.append({"code": "numbers", "message": "SVG numbers absent from commission/text", "values": extra})
    return warnings


def generation_errors(repo, brief, candidate, generated=None):
    if brief["kind"] not in ("banner", "infographic"):
        return []
    asset = candidate.get("asset")
    proof = rights.generated(repo, asset, generated)
    if not asset or not asset.endswith(".webp") or not proof or proof[0] != "generated":
        return ["banner/infographic needs a generated .webp candidate with a generation receipt"]
    return []
