"""Private figure requests, identified by source bytes and a unique hidden marker."""

import re

from ..state import safefs
from ..schemas import validate
from ..wiki import frontmatter, machine, markers
from ..wiki.pages import CODE_FENCE, INLINE_CODE, sha256, wiki_pages

PATH = "docs/figure-requests.json"
MARKER = re.compile(r"^<!-- figure-request: ([a-z0-9-]{1,64}) -->$", re.M)
FIELDS = ("id", "page", "source", "crop", "purpose", "origin")


def load(repo):
    value = safefs.read_json(repo, PATH, [])
    validate("figure-requests", value)
    if len({r["id"] for r in value}) != len(value):
        raise ValueError("duplicate figure request ids")
    return sorted(({k: r[k] for k in (*FIELDS, "content_sha256", "original_sha256")} for r in value),
                  key=lambda r: (r["source"], r["page"], r["id"]))


def original_hash(repo, source, pages=()):
    material = source
    parent = source.rsplit("/", 1)[0]
    while parent.startswith("sources/"):
        if safefs.is_file(repo, parent + "/document.md"):
            material = parent + "/document.md"
            break
        parent = parent.rsplit("/", 1)[0]
    found = {p["original_sha256"].split("#", 1)[0] for p in pages
             if p.get("path") == material and p.get("original_sha256")}
    for page in sorted(wiki_pages(repo)):
        meta = frontmatter.split(safefs.read_text(repo, page)).meta
        originals = machine._full_paths(meta, "original_sha256")
        if material in originals:
            found.add(originals[material].split("#", 1)[0])
    if len(found) != 1 or not re.fullmatch(r"[a-f0-9]{64}", next(iter(found), "")):
        return None
    return found.pop()


def collect(repo, incoming, pages=()):
    existing = {r["id"]: r for r in load(repo)}
    seen = set()
    for request in sorted(incoming, key=lambda r: (r["page"], r["id"])):
        fid = request["id"]
        if fid in seen:
            raise ValueError(f"duplicate figure request: {fid}")
        seen.add(fid)
        if not request["source"].startswith("sources/"):
            raise ValueError("figure request source must be under sources/")
        digest = sha256(repo, request["source"])
        old = existing.get(fid)
        if old and (any(old[k] != request[k] for k in FIELDS) or old["content_sha256"] != digest):
            raise ValueError(f"figure request id was reused: {fid}")
        existing[fid] = old or {**{k: request[k] for k in FIELDS}, "content_sha256": digest,
                               "original_sha256": original_hash(repo, request["source"], pages)}
    found = {}
    for page in sorted(wiki_pages(repo)):
        for fid in marker_ids(safefs.read_text(repo, page)):
            found.setdefault(fid, []).append(page)
    for fid, locations in sorted(found.items()):
        if fid not in existing or locations != [existing[fid]["page"]]:
            raise ValueError(f"figure-request {fid} needs exactly one matching request and page")
    for fid in sorted(seen):
        request = existing[fid]
        inserted = markers.read(safefs.read_text(repo, request["page"]), f"figure-{fid}")
        if fid not in found and inserted is None:
            raise ValueError(f"figure-request {fid} has no marker")
    value = sorted(existing.values(), key=lambda r: (r["source"], r["page"], r["id"]))
    validate("figure-requests", value)
    return value


def marker_ids(text):
    blank = lambda m: re.sub(r"[^\n]", " ", m[0])
    return MARKER.findall(INLINE_CODE.sub(blank, CODE_FENCE.sub(blank, text)))


def active(repo):
    return [r for r in load(repo) if safefs.is_file(repo, r["page"]) and
            r["id"] in marker_ids(safefs.read_text(repo, r["page"]))]


def approved(repo):
    from . import licenses
    return [r for r in active(repo) if licenses.permission(repo, r) is not None]
