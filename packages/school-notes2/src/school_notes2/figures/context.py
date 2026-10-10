"""The exact teaching context behind a figure verdict (T-052, T-154)."""

import hashlib
import json
import re
from pathlib import Path

from ..state import safefs
from ..wiki import frontmatter, markers
from ..wiki.pages import CODE_FENCE, LINK, links, relative, resolve, sub_links, wiki_pages
from .commissions import MARKER, MERMAID, markers as figure_markers

HEAD = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.M)
DESCRIPTION = re.compile(r"\s*<!-- image-description(?:\n|:).*?-->", re.S)
# A section's lesson line and textbook line - a complete, closed `<sub>🗓️ Óra: …</sub>` or
# `<sub>🔖 Tankönyv: …</sub>` line, its footnote references allowed after it and nothing else: when
# and where the material was taught, never what the figure must show. Left out of the key since
# sn 0.3.9 (exactly this form since 0.3.10), so a date-form edit does not invalidate a verdict;
# anything else on such a line keeps the line in the key.
from ..wiki.date_spans import META_LINE  # noqa: E402 - shared with the date normaliser


OPEN_LARGE_TEXT = "Az ábra megnyitása nagy méretben"
OPEN_LARGE = f"[{OPEN_LARGE_TEXT}]"
# The verdict keys a recorded verdict may still carry (`key_matches`, renewed by `rekey`):
# "0.4.0" – sn 0.3.9-0.4.0, the open-large link's target still in the key; True – sn 0.3.8 and
# before, also the lesson and textbook lines.
LEGACY = ("0.4.0", True)


def follow_replacement(text: str, brief: dict, candidate: dict) -> str:
    """A replacing figure's „open large” link to the old asset, pointed at the new one – what the
    insertion writes (sn 0.4.1: in the one page write of the figure, so a failing insertion writes
    nothing). The link's target is not part of any verdict key (`canonical`): the rewrite changes
    no figure's key, the replacing one's or another's in the same section."""
    old, new = brief.get("replaces"), candidate.get("asset")
    if not old or not new:
        return text
    page = brief["page"]
    return text.replace(f"{OPEN_LARGE}({relative(page, old)})", f"{OPEN_LARGE}(<{relative(page, new)}>)")


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
    return sub_links(text, remove, pattern)


def canonical(text: str, page: str, brief: dict, legacy: bool | str = False) -> str:
    # Other figures and tool bookkeeping cannot invalidate this figure's context.
    # Its own image, alt and caption are bound separately in verdict_key; the „open large” link
    # keeps its words, its target is the tool's (sn 0.4.1, `follow_replacement`). `legacy`
    # (`LEGACY`): "0.4.0" kept that target, True (sn 0.3.8) also the lesson and textbook lines.
    text = markers.BLOCK.sub("", text)
    if legacy is not True:
        text = META_LINE.sub("", text)
    text = DESCRIPTION.sub("", text)

    def link(m):
        if m["img"]:
            return ""
        if not legacy and m["text"] == OPEN_LARGE_TEXT:
            return OPEN_LARGE
        return m[0]
    text = sub_links(text, link)
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


def embedding(repo: Path, brief: dict, candidate: dict, legacy: bool | str = False) -> dict:
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
    return {"page": page, "section": canonical(body, page, brief, legacy), "context": around,
            "alt": candidate["alt"], "caption": candidate["caption"].rstrip("\n")}


def verdict_key(repo: Path, brief: dict, candidate: dict, legacy: bool | str = False) -> str:
    fid = brief["id"]
    text = safefs.read_text(repo, brief["page"])
    if markers.read(text, f"figure-{fid}") is None:
        found = figure_markers(repo).get(fid, [])
        if len(found) != 1 or found[0][0] != brief["page"]:
            raise ValueError("figure has no unique insertion marker or inserted block")
    candidate = embedded_candidate(repo, brief, candidate)
    context = embedding(repo, brief, candidate, legacy)
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
        context["other_uses"] = usage_keys(repo, brief, candidate, legacy)
    return digest({"image_sha256": sha, **context})


def key_matches(repo: Path, brief: dict, candidate: dict, stored: str) -> bool:
    """A recorded verdict key is valid for the content as it is now: the current key, or an older
    key of the same content (`LEGACY`: sn 0.4.0, sn 0.3.8) a verdict still carries until `rekey`
    renews it."""
    try:
        if stored == verdict_key(repo, brief, candidate):
            return True
        return any(stored == verdict_key(repo, brief, candidate, legacy=level) for level in LEGACY)
    except (OSError, ValueError):
        return False


def rekey(repo: Path) -> list[str]:
    """One mechanical step (sn close, before any insertion): a figure verdict whose recorded key is
    an older key (`LEGACY`) of the content exactly as it is now gets the current key – safe,
    because the keys differ only by the lesson and textbook lines (sn 0.3.8) and the open-large
    link's target (sn 0.4.0). In `docs/review/verdicts.json` and the figure's evidence record;
    returns the paths written."""
    from .insert import VERDICTS, removed
    records = safefs.read_json(repo, VERDICTS, []) if safefs.is_file(repo, VERDICTS) else []
    written, renewed = [], {}
    for record in records:
        if record.get("role") != "figure-review" or record.get("night_spec") or removed(repo, record):
            continue
        try:
            new = verdict_key(repo, record["commission"], record["candidate"])
            if record.get("key") != new and any(record.get("key") == verdict_key(
                    repo, record["commission"], record["candidate"], legacy=level) for level in LEGACY):
                renewed[record["key"]] = new
                record["key"] = new
        except (OSError, ValueError, KeyError):
            continue
    if renewed:
        safefs.write_json(repo, VERDICTS, sorted(records, key=lambda r: (r["file"], r["key"], r["role"])))
        written.append(VERDICTS)
    media = "docs/evidence/media"
    for fid in sorted(safefs.listdir(repo, media)) if safefs.is_dir(repo, media) else []:
        rel = f"{media}/{fid}/figure.json"
        if not safefs.is_file(repo, rel):
            continue
        evidence = safefs.read_json(repo, rel, {})
        old = evidence.get("verdict", {}).get("key")
        if not old:
            continue
        new = renewed.get(old)
        if new is None and evidence.get("commission") and evidence.get("candidate"):
            try:
                current = verdict_key(repo, evidence["commission"], evidence["candidate"])
                if old != current and any(old == verdict_key(repo, evidence["commission"], evidence["candidate"],
                                                             legacy=level) for level in LEGACY):
                    new = current
            except (OSError, ValueError, KeyError):
                new = None
        if new and new != old:
            safefs.write_json(repo, rel, {**evidence, "verdict": {**evidence["verdict"], "key": new}})
            written.append(rel)
    return written


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


def usage_keys(repo: Path, brief: dict, candidate: dict, legacy: bool | str = False) -> list[dict]:
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
                           "section_sha256": digest(canonical(body, page, brief, legacy))})
    return result
