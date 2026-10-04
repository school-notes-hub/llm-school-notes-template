"""Small review batches, with only observed-content inputs, never the generating prompt."""

import hashlib
from collections.abc import Callable
from pathlib import Path

from ..review.relations import reviewer_inventory
from ..state import safefs
from ..wiki.pages import links, resolve, wiki_pages
from . import commissions, context, machine
from .render import png

Render = Callable[[str, bytes, str], bytes]


def batches(repo: Path, briefs: list[dict]) -> list[tuple[str, list[dict]]]:
    grouped = {}
    for brief in sorted(briefs, key=lambda b: commissions.order(repo, b)):
        grouped.setdefault(commissions.topic(repo, brief["page"]), []).append(brief)
    result = []
    for topic, figures in sorted(grouped.items()):
        slug = Path(topic).stem + "-" + hashlib.sha256(topic.encode()).hexdigest()[:12]
        for i in range(0, len(figures), 4):
            result.append((f"{slug}-{i // 4 + 1}", figures[i:i + 4]))
    return result


def prepare(repo: Path, briefs: list[dict], folder: Path, render: Render) -> dict:
    if not 1 <= len(briefs) <= 4:
        raise ValueError("a review call needs 1 to 4 figures")
    topics = {commissions.topic(repo, b["page"]) for b in briefs}
    if len(topics) != 1:
        raise ValueError("one primary topic per review call")
    folder.mkdir(parents=True, exist_ok=True)
    items = [_figure(repo, brief, folder, render) for brief in briefs]
    inventory = reviewer_inventory(repo)
    pages = sorted({use["page"] for item in items for use in item["uses"]})
    assigned = {"figures": [{"id": i["commission"]["id"], "key": i["key"]} for i in items]}
    safefs.write_json(folder, "assigned.json", assigned)
    safefs.write_json(folder, "input.json", {
        "figures": items, "topic_figures": topic_figures(repo, topics.pop()),
        "relations": {p: inventory["pages"].get(p, {}) for p in pages}})
    return assigned


def _figure(repo: Path, brief: dict, folder: Path, render: Render) -> dict:
    candidate = commissions.candidate(repo, brief)
    if candidate["state"] != "candidate":
        raise ValueError(f"{brief['id']}: no candidate to review")
    report = machine.report(repo, brief, candidate)
    if report["errors"]:
        raise ValueError("; ".join(report["errors"]))
    fid = brief["id"]
    if "mermaid" in candidate:
        data = context.mermaid_source(repo, brief, candidate).encode()
        kind = "mermaid"
    else:
        data = safefs.read_bytes(repo, candidate["asset"])
        kind = Path(candidate["asset"]).suffix.lstrip(".").lower()
    full = png(render(kind, data, fid))
    safefs.write_bytes(folder, f"images/{fid}.png", full)
    safefs.write_bytes(folder, f"images/{fid}-phone.png", png(full, width=390))
    result = {"commission": brief, "key": context.verdict_key(repo, brief, candidate),
              "full": f"images/{fid}.png", "phone": f"images/{fid}-phone.png",
              "embedding": context.embedding(repo, brief, candidate), "machine": report,
              "uses": [context.page_context(repo, brief["page"])] + context.other_uses(repo, brief, candidate)}
    _source(repo, brief, candidate, folder, result, data, kind)
    return result


def _source(repo, brief, candidate, folder, result, data, kind):
    fid = brief["id"]
    if kind == "mermaid":
        result["source"] = data.decode()
    elif candidate.get("source"):
        result["source"] = safefs.read_text(repo, candidate["source"])
    elif candidate.get("render"):
        raw = safefs.read_json(repo, candidate["render"])
        result["render"] = {key: raw[key] for key in ("engine", "source", "source_sha256", "outputs")
                            if key in raw}
        source = result["render"].get("source")
        if source:
            result["source"] = safefs.read_text(repo, source)
    elif kind == "svg":
        result["source"] = data.decode()
    if brief.get("source_image"):
        source = brief["source_image"]
        cropped = png(safefs.read_bytes(repo, source["path"]), crop=source["crop"])
        result["source_crop"] = f"images/{fid}-crop.png"
        safefs.write_bytes(folder, result["source_crop"], cropped)


def topic_figures(repo: Path, topic: str) -> list[dict]:
    result = []
    for page in sorted(wiki_pages(repo)):
        if commissions.topic(repo, page) != topic:
            continue
        for link in links(safefs.read_text(repo, page)):
            asset = resolve(page, link.target)
            if link.image and asset:
                result.append({"page": page, "asset": asset, "alt": link.text, "line": link.line})
    return result
