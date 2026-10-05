"""Mechanical replacement briefs for legacy headers; old images stay until acceptance."""

import hashlib

from ..state import safefs
from ..wiki import banners, frontmatter
from ..wiki.pages import wiki_pages


def replacements(repo, entries, texts):
    result = list(entries)
    for path in sorted(wiki_pages(repo)):
        text = texts.get(path, safefs.read_text(repo, path))
        page = frontmatter.split(text)
        asset = banners.asset(path, page.body)
        if (not banners.required(path, page.meta) or not asset or
                banners.generated_header(repo, path, page.body)):
            continue
        existing = next((e for e in result if e["commission"]["page"] == path and
                         e["commission"]["kind"] == "banner"), None)
        if existing:
            brief = existing["commission"]
            brief.update(replaces=asset, decision_reason=reason())
        else:
            brief = commission(path, asset, page.meta)
            result.append({"commission": brief, "status": "pending", "runs": 0,
                           "run_ids": [], "owner_required": False, "defects": []})
        marker = f"<!-- image: {brief['id']} -->"
        if not banners.pending_header(repo, path, page.body, {brief["id"]: brief}):
            text = text.replace(marker + "\n", "")
            cut = len(text) - len(frontmatter.split(text).body)
            texts[path] = text[:cut] + "\n" + marker + "\n\n" + text[cut:].lstrip("\n")
    return sorted(result, key=lambda e: e["commission"]["id"])


def reason():
    return {"code": "c", "text": "A banner gépi ellenőrzése generálási nyugtával igazolt képet kér."}


def commission(page, asset, meta):
    fid = "banner-" + hashlib.sha256((page + "\n" + asset).encode()).hexdigest()[:32]
    return {"id": fid, "page": page, "kind": "banner", "anchor": "Fejléc",
            "purpose": "A témát bemutató generált fejléc.",
            "must_show": [meta["title"]] if meta.get("title") else [],
            "avoid_misreading": "A témát mutassa, ne egy példát vagy a forrást.",
            "taught_conventions": [], "text_complete_without_figure": True,
            "replaces": asset, "decision_reason": reason()}
