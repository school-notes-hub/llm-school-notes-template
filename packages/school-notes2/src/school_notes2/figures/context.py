"""The exact teaching context behind a figure verdict (T-052, T-154)."""

import hashlib
import json
import re
from pathlib import Path

from ..state import safefs
from ..wiki import frontmatter, markers
from ..wiki.pages import CODE_FENCE, LINK, links, relative, resolve, wiki_pages
from .commissions import MARKER, MERMAID, markers as figure_markers

HEAD = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.M)
DESCRIPTION = re.compile(r"\s*<!-- image-description(?:\n|:).*?-->", re.S)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def without_replaced(text: str, page: str, asset: str | None) -> str:
    if not asset:
        return text
    def remove(match):
        return "" if match["img"] and resolve(page, match["target"].strip("<>")) == asset else match[0]
    # Only remove the comment belonging to this image, never another image's evidence.
    pattern = re.compile(LINK.pattern + r"(?:\s*<!-- image-description(?:\n|:).*?-->)?", re.S)
    def old_block(match):
        if any(link.image and resolve(page, link.target) == asset for link in links(match["body"])):
            return ""
        return match[0]
    text = markers.BLOCK.sub(old_block, text)
    return pattern.sub(remove, text)


def canonical(text: str, page: str, brief: dict) -> str:
    # Other figures and tool bookkeeping cannot invalidate this figure's context.
    # Its own image, alt and caption are bound separately in verdict_key.
    text = markers.BLOCK.sub("", text)
    text = DESCRIPTION.sub("", text)
    text = LINK.sub(lambda m: "" if m["img"] else m[0], text)
    text = MARKER.sub("", text)
    return re.sub(r"\n(?:[ \t]*\n)+", "\n\n", text).strip()


def with_markers(text: str) -> str:
    def block(match):
        name = match["name"]
        return f"<!-- figure: {name[7:]} -->" if name.startswith("figure-") else ""
    text = markers.BLOCK.sub(block, text)
    return MARKER.sub(lambda m: f"<!-- figure: {m[1]} -->", text)


def section(text: str, anchor: str) -> tuple[str, str]:
    """Full embedding section for the key; adjacent paragraphs for the reviewer."""
    body = frontmatter.split(text).body
    blank = CODE_FENCE.sub(lambda m: re.sub(r"[^\n]", " ", m[0]), body)
    heads = list(HEAD.finditer(blank))
    matches = [i for i, h in enumerate(heads) if h[2] == anchor]
    if len(matches) != 1:
        raise ValueError(f"section title must occur exactly once: {anchor}")
    i = matches[0]
    start = heads[i].start()
    end = next((h.start() for h in heads[i + 1:] if len(h[1]) <= len(heads[i][1])), len(body))
    before = body[:start].strip().split("\n\n")[-1:]
    after = body[end:].strip().split("\n\n")[:1]
    return body[start:end].strip(), "\n\n".join(before + [body[start:end].strip()] + after)


def embedding(repo: Path, brief: dict, candidate: dict) -> dict:
    page = brief["page"]
    text = with_markers(safefs.read_text(repo, page))
    meta = frontmatter.split(text).meta
    if brief["kind"] == "banner":
        return {"page": page, "title": meta.get("title", ""),
                "description": meta.get("description", ""),
                "alt": candidate["alt"], "caption": candidate["caption"].rstrip("\n")}
    body, around = section(text, brief["anchor"])
    if f"<!-- figure: {brief['id']} -->" not in body:
        raise ValueError("figure marker is outside the commission section")
    if "mermaid" in candidate and mermaid_source(repo, brief, candidate) not in body:
        raise ValueError("Mermaid block is outside the commission section")
    return {"page": page, "section": canonical(body, page, brief), "context": around,
            "alt": candidate["alt"], "caption": candidate["caption"].rstrip("\n")}


def verdict_key(repo: Path, brief: dict, candidate: dict) -> str:
    fid = brief["id"]
    text = safefs.read_text(repo, brief["page"])
    if markers.read(text, f"figure-{fid}") is None:
        found = figure_markers(repo).get(fid, [])
        if len(found) != 1 or found[0][0] != brief["page"]:
            raise ValueError("figure has no unique insertion marker or inserted block")
    candidate = embedded_candidate(repo, brief, candidate)
    context = embedding(repo, brief, candidate)
    if brief["kind"] == "banner":
        context.pop("alt", None)
        context.pop("caption", None)
    context.pop("context", None)  # neighbours are context, not the embedding section
    if "mermaid" in candidate:
        image = mermaid_source(repo, brief, candidate)
        sha = hashlib.sha256(image.encode()).hexdigest()
    else:
        sha = hashlib.sha256(safefs.read_bytes(repo, candidate["asset"])).hexdigest()
    if brief["kind"] != "banner":
        context["other_uses"] = usage_keys(repo, brief, candidate)
    return digest({"image_sha256": sha, **context})


def mermaid_source(repo: Path, brief: dict, candidate: dict) -> str:
    text = safefs.read_text(repo, brief["page"])
    body, _ = section(text, brief["anchor"])
    graphs = [m[1] for m in MERMAID.finditer(body)
              if hashlib.sha256(m[1].encode()).hexdigest() == candidate["mermaid"]]
    if len(graphs) != 1:
        raise ValueError("Mermaid source hash must identify exactly one block in the commission section")
    return graphs[0]


def page_context(repo: Path, page: str) -> dict:
    text = safefs.read_text(repo, page)
    parsed = frontmatter.split(text)
    questions = []
    for match in HEAD.finditer(parsed.body):
        if "Nyitott kérdések" in match[2] or "Open questions" in match[2]:
            questions.append(section(text, match[2])[0])
    return {"page": page, "questions": questions,
            "decisions": sorted(parsed.meta.get("decisions", []), key=lambda d: d["id"])}


def other_uses(repo: Path, brief: dict, candidate: dict) -> list[dict]:
    """Every real use, with its local text and questions; no author self-evaluation."""
    result = []
    asset = candidate.get("asset")
    for page in sorted(wiki_pages(repo)):
        if page == brief["page"]:
            continue
        text = safefs.read_text(repo, page)
        uses = [link for link in links(text) if link.image and resolve(page, link.target) == asset]
        if asset and uses:
            result.append({**page_context(repo, page), "text": text,
                           "alts": [link.text for link in uses]})
    return result


def embedded_candidate(repo: Path, brief: dict, candidate: dict) -> dict:
    block = markers.read(safefs.read_text(repo, brief["page"]), f"figure-{brief['id']}")
    if block is None:
        return candidate
    match = re.match(r"!\[((?:\\.|[^\]])*)\]\(<([^>]+)>\)\n\n", block)
    if not match:
        raise ValueError("inserted figure link is missing or malformed")
    asset = resolve(brief["page"], match[2])
    if not asset or not asset.startswith("wiki/assets/"):
        raise ValueError("inserted asset is outside wiki/assets")
    caption = block[match.end():].split("<!-- image-description", 1)[0].rstrip("\n")
    alt = re.sub(r"\\(.)", r"\1", match[1])
    return {**candidate, "asset": asset, "alt": alt, "caption": caption}


def usage_keys(repo: Path, brief: dict, candidate: dict) -> list[dict]:
    result = []
    asset = candidate.get("asset")
    if not asset:
        return result
    for page in sorted(wiki_pages(repo)):
        if page == brief["page"]:
            continue
        text = safefs.read_text(repo, page)
        for link in links(text):
            if not link.image or resolve(page, link.target) != asset:
                continue
            position = sum(len(line) for line in text.splitlines(keepends=True)[:link.line - 1])
            before = text[:position]
            heads = list(HEAD.finditer(CODE_FENCE.sub("", before)))
            body = section(text, heads[-1][2])[0] if heads else frontmatter.split(text).body
            block = next((m for m in markers.BLOCK.finditer(text)
                          if m.start() <= position < m.end() and m["name"].startswith("figure-")), None)
            caption = embedded_candidate(repo, {"page": page, "id": block["name"][7:]}, candidate)["caption"] if block else ""
            result.append({"page": page, "alt": link.text,
                           "caption": caption,
                           "section_sha256": digest(canonical(body, page, brief))})
    return result
