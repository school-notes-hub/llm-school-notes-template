"""publication/public.json, the public site's only release list (plan 4.10).

The public site shows every wiki page. Files under sources/ and references/ never ship; the
renderer leaves out the links and citations pointing to them (study-site lib/markdown.mjs).
"""

import json
import re
from pathlib import Path
from typing import Callable

from . import generate
from ..state import safefs
from .pages import is_file, links, read_text, resolve, sha256, wiki_pages

FIXED = ("version", "mode", "title", "base", "branding", "feedbackRepository", "license", "site",
         "sourceNote")
PRIVATE_PREFIXES = ("sources/", "references/")
SUBJECT_SUFFIX = " — tanulási jegyzet"
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".avif")

# rights(asset_path) -> (rights, evidence path) for an asset the existing file does not know.
RightsLookup = Callable[[str], tuple[str, str] | None]


class PublicError(ValueError):
    """Assets with no known rights class: the `check` stops (plan 4.10, B10)."""

    def __init__(self, paths: list[str],
                 reason: str = "new images with no render.json and no image-ledger record"):
        super().__init__(f"{reason}: " + ", ".join(paths))
        self.paths = paths
        self.reason = reason


def page_order(repo: Path) -> list[str]:
    """B7: root index → per subject: index, chapter pages, lessons table, other lists → info pages."""
    order: list[str] = ["wiki/index.md"]
    for slug in generate.subject_order(repo):
        subject = generate.load_subject(repo, slug)
        seq = ["index.md"]
        for chapter in subject.index_meta.get("chapters") or []:
            seq += [p.file for p in generate.chapter_pages(subject, chapter["id"])]
        seq += [page.file for page, _ in generate.lessons(subject)]
        seq += [p.file for p in generate.by_date_desc(subject.by_type("review"))]
        seq += [p.file for p in generate.by_date_desc(subject.by_type("lesson-notes"))]
        seq += [p.file for p in subject.pages]
        order += [f"wiki/{slug}/{f}" for f in dict.fromkeys(seq)]
    rest = [p for p in wiki_pages(repo) if p not in order]
    return order + rest


def page_entry(repo: Path, rel: str) -> dict:
    entry = {"path": rel, "sha256": sha256(repo, rel)}
    parts = rel.split("/")
    if rel == "wiki/index.md":
        entry["navigationLabel"] = "🏠 Kezdőlap"
    elif len(parts) == 3 and parts[2] == "index.md":
        entry["navigationLabel"] = generate.subject_label(repo, parts[1])
    elif len(parts) == 2:
        entry["navigation"] = "info"     # top-level pages such as a-projektrol.md
    return entry


def collections(repo: Path) -> list[dict]:
    """One PDF per chapter page, grouped under the chapter's summary; one per subject (B6)."""
    out = []
    for slug in generate.subject_order(repo):
        subject = generate.load_subject(repo, slug)
        everything = []
        for chapter in subject.index_meta.get("chapters") or []:
            pages = generate.chapter_pages(subject, chapter["id"])
            summary = next((p for p in pages if p.meta.get("type") == "chapter-summary"), None)
            for page in pages:
                item = {"id": f"{slug}-{page.file[:-3]}", "title": page.meta.get("title", page.file),
                        "pages": [f"wiki/{slug}/{page.file}"], "pdf": True}
                if summary and page is not summary:
                    item["group"] = f"{slug}-{summary.file[:-3]}"
                out.append(item)
                everything.append(f"wiki/{slug}/{page.file}")
        if everything:
            out.append({"id": slug, "title": subject.index_title + SUBJECT_SUFFIX, "pages": everything})
    return out


def linked_targets(repo: Path, pages: list[str]) -> tuple[set[str], set[str]]:
    """(images inside wiki/, citation targets under sources/ or references/)."""
    images, citations = set(), set()
    for rel in pages:
        for link in links(read_text(repo, rel)):
            target = resolve(rel, link.target)
            if target is None:
                continue
            if target.startswith(PRIVATE_PREFIXES):
                citations.add(target)
            elif target.startswith("wiki/") and target.lower().endswith(IMAGE_EXT):
                images.add(target)
            elif target.startswith("wiki/") and target.lower().endswith(".mp4"):
                images.update((target, target[:-4] + ".png"))   # animation and its poster
    return images, citations


def asset_entry(repo: Path, rel: str, known: dict, rights: RightsLookup) -> dict | None:
    entry = {"path": rel, "sha256": sha256(repo, rel)}
    old = known.get(rel)
    if old and old.get("sha256") == entry["sha256"] and old.get("rights") in (
            "authored", "generated", "public-domain", "standard"):
        entry["rights"] = old["rights"]
        if old.get("rightsEvidence"):
            entry["rightsEvidence"] = old["rightsEvidence"]
        return entry
    from ..figures.licenses import rights as licensed_rights
    licensed = licensed_rights(repo, rel)
    found = licensed if old and old.get("rights") == "licensed" else licensed or rights(rel)
    if found is None:
        return None
    entry["rights"], entry["rightsEvidence"] = found
    return entry


def build(repo: Path, rights: RightsLookup, existing: dict | None = None) -> dict:
    """The full public.json value; `existing` supplies fixed fields and known asset rights."""
    existing = existing if existing is not None else read_existing(repo)
    order = page_order(repo)
    images, citations = linked_targets(repo, order)
    known = {a["path"]: a for a in existing.get("assets", [])}
    value = {k: existing[k] for k in FIXED if k in existing}
    note = source_note(repo)
    if note:
        value["sourceNote"] = note
    value.setdefault("version", 1)
    value["pages"] = [page_entry(repo, rel) for rel in order]
    assets = {rel: asset_entry(repo, rel, known, rights)
              for rel in sorted(i for i in images if is_file(repo, i))}
    unknown = [rel for rel, entry in assets.items() if entry is None]
    if unknown:
        raise PublicError(unknown)
    copies = source_copies(repo, [rel for rel in assets if assets[rel]["rights"] != "licensed"])
    copies += [rel for rel in assets if rel.startswith("wiki/assets/orai/")]
    if copies:
        raise PublicError(copies, "a copy of a source photo may not be published as an image")
    value["assets"] = list(assets.values())
    value["collections"] = collections(repo)
    value["citationOnlyLinks"] = sorted(citations)
    return value


def read_existing(repo: Path) -> dict:
    try:
        return json.loads(read_text(repo, "publication/public.json"))
    except FileNotFoundError:
        return {}


def dumps(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def write(repo: Path, rights: RightsLookup) -> bool:
    """Write public.json; True if it changed."""
    rel = "publication/public.json"
    text = dumps(build(repo, rights))
    if is_file(repo, rel) and read_text(repo, rel) == text:
        return False
    safefs.write_text(repo, rel, text)
    return True


def source_copies(repo: Path, new_assets: list[str]) -> list[str]:
    """New assets that are byte copies of a stored source page (its content_sha256)."""
    if not new_assets:
        return []
    from ..sources.duplicates import known_hashes      # sources imports wiki: import late
    sources = set(known_hashes(repo).content)
    return [rel for rel in new_assets if sha256(repo, rel) in sources]


def media_receipt_rights(repo: Path) -> RightsLookup:
    from .rights import media
    return media(repo)


def render_rights(repo: Path) -> RightsLookup:
    from .rights import rendered
    return rendered(repo)


def source_note(repo: Path) -> str | None:
    if not is_file(repo, "PROFILE.md"):
        return None
    profile = read_text(repo, "PROFILE.md")
    if "Not initialized yet" in profile:
        return None
    found = re.search(r"^\* \*\*Student\*\*: ([^\W\d_]+)(?:[. \n]|$)", profile, re.M)
    if not found:
        return None
    return (f"A jegyzet {found[1]} órai jegyzetei és a tanári anyagok alapján készült; "
            "mesterséges intelligencia egészítette ki és javította, és ahol a tankönyv "
            "rendelkezésre áll, azzal összevetette.")


def either(*lookups: RightsLookup) -> RightsLookup:
    def lookup(rel: str):
        return next((r for r in (f(rel) for f in lookups) if r), None)
    return lookup
