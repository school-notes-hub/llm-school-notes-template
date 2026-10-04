"""Content-derived review units and author-only page verdict keys (T-052)."""

import hashlib
import re
from pathlib import Path

from ..figures import commissions
from ..review import relations
from ..state import safefs
from ..wiki import frontmatter
from ..wiki.pages import links, resolve, wiki_pages


def page_key(repo: Path, page: str, *, legacy_notices=False) -> str:
    from ..flows.steps import _llm_part
    text = _llm_part(safefs.read_text(repo, page), legacy_notices=legacy_notices)
    text = re.sub(r"\n?" + commissions.MARKER.pattern + r"\n{0,2}", "", text)
    return hashlib.sha256(text.replace("\r\n", "\n").rstrip("\n").encode()).hexdigest()


def slug(topic: str) -> str:
    return Path(topic).stem + "-" + hashlib.sha256(topic.encode()).hexdigest()[:12]


def collect(repo: Path, changed: list[str], closures=(), briefs=()) -> list[dict]:
    pages = set(wiki_pages(repo))
    affected = {p for p in changed if p in pages}
    known = relations.inventory(repo)["items"]
    affected.update(known.get(c["file"] + "#" + c["item_id"], {}).get("file", "")
                    for c in closures)
    affected.update(b["page"] for b in briefs)
    groups = {}
    for page in sorted(affected & pages):
        topic = commissions.topic(repo, page)
        groups.setdefault(topic, set()).update((topic, page))
    # An unchanged related lesson is context; only its primary topic owns its verdict.
    for page in sorted(pages):
        topic = commissions.topic(repo, page)
        if topic in groups:
            groups[topic].add(page)
    result = []
    for topic, assigned in sorted(groups.items()):
        context = set()
        for page in sorted(pages - assigned):
            meta = frontmatter.split(safefs.read_text(repo, page)).meta
            if meta.get("type") in ("summary", "review") and any(
                    resolve(page, link.target.split("#", 1)[0]) == topic
                    for link in links(safefs.read_text(repo, page))):
                context.add(page)
        result.append({"topic": topic, "pages": sorted(assigned), "context": sorted(context),
                       "keys": {p: page_key(repo, p) for p in sorted(assigned)}})
    return result
