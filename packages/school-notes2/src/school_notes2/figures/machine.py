"""Hard file/render checks and non-blocking hints for the independent figure reviewer."""

import hashlib
import re
from pathlib import Path
from xml.etree import ElementTree

from ..state import safefs
from ..wiki.check import check_renders
from ..wiki import frontmatter, source_refs
from . import context

NUMBER = re.compile(r"(?<![\w#])[-+]?\d+(?:[.,]\d+)?")


def report(repo: Path, brief: dict, candidate: dict) -> dict:
    errors, warnings = [], []
    asset = candidate.get("asset")
    source = candidate.get("source")
    receipt = candidate.get("render")
    for rel in sorted({r for r in (asset, source, receipt) if r}):
        if not safefs.is_file(repo, rel):
            errors.append(f"missing file: {rel}")
    if errors:
        return {"errors": errors, "warnings": warnings}
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
    if any(pattern.search(labels) for pattern in source_refs.PATTERNS):
        warnings.append({"code": "source-pattern", "message": "Source-reference pattern in SVG labels"})
    return warnings
