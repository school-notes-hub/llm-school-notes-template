"""Writer contracts, unique markers and deterministic primary-topic assignment."""

import re
from pathlib import Path

from ..images.plans import check_id
from ..schemas import validate
from ..state import safefs
from ..wiki import frontmatter, markers as blocks
from ..wiki.pages import CODE_FENCE, INLINE_CODE, links, resolve, wiki_pages

MARKER = re.compile(r"<!-- (?:figure|image): ([a-z0-9-]{1,64}) -->")
MERMAID = re.compile(r"^```mermaid[^\n]*\n(.*?)^```\s*$", re.M | re.S)


def read(repo: Path, figure_id: str) -> dict:
    value = safefs.read_json(repo, f".school-notes/figures/{check_id(figure_id)}.json")
    validate("figure-commission", value)
    if value["id"] != figure_id:
        raise ValueError("commission id differs from filename")
    for path in (value["page"], value.get("replaces"),
                 (value.get("source_image") or {}).get("path")):
        if path:
            safefs.read_bytes(repo, path)
    if value.get("replaces") and not value["replaces"].startswith("wiki/assets/"):
        raise ValueError("replaces must name a wiki asset")
    if "source_image" in value:
        if not value["source_image"]["path"].startswith(("sources/", "references/", "wiki/assets/")):
            raise ValueError("source image must be source evidence or a wiki asset")
        x, y, right, bottom = value["source_image"]["crop"]
        if right <= x or bottom <= y:
            raise ValueError("crop must be a nonempty pixel box: left, top, right, bottom")
    return value


def markers(repo: Path) -> dict[str, list[tuple[str, int]]]:
    found = {}
    for path in sorted(wiki_pages(repo)):
        text = safefs.read_text(repo, path)
        # Blanking code preserves positions used for the page-order tie breaker.
        blank = lambda m: " " * len(m[0])
        text = INLINE_CODE.sub(blank, CODE_FENCE.sub(blank, text))
        for match in MARKER.finditer(text):
            found.setdefault(match[1], []).append((path, match.start()))
    return found


def validate_assignments(repo: Path, assignments: list[dict]) -> list[dict]:
    found, ids, replaced, result = markers(repo), set(), set(), []
    for assignment in sorted(assignments, key=lambda a: a["id"]):
        fid = assignment["id"]
        if fid in ids:
            raise ValueError(f"duplicate figure assignment: {fid}")
        ids.add(fid)
        brief = read(repo, fid)
        if any(brief[k] != assignment[k] for k in ("page", "kind")):
            raise ValueError(f"{fid}: assignment differs from commission")
        if not _inserted(repo, brief) and (len(found.get(fid, [])) != 1 or found[fid][0][0] != brief["page"]):
            raise ValueError(f"{fid}: marker must occur exactly once on its page")
        old = brief.get("replaces")
        if old and old in replaced:
            raise ValueError("at most one replacement per image per run")
        if old:
            replaced.add(old)
        result.append(brief)
    return result


def candidate(repo: Path, brief: dict) -> dict:
    value = safefs.read_json(repo, f".school-notes/figures/{brief['id']}/figure.json")
    if value is None:
        return {"state": "failed", "reason": "missing figure.json"}
    validate("figure-candidate", value)
    if brief["kind"] in ("notebook-drawing", "teacher-drawing"):
        if value["state"] == "no-figure":
            raise ValueError("a source drawing cannot be replaced by no-figure")
        if value["state"] == "candidate" and "corrections" not in value:
            raise ValueError("a source drawing needs corrections (possibly empty)")
    if value.get("source") and not value["source"].startswith(("wiki/assets/", f".school-notes/figures/{brief['id']}/")):
        raise ValueError("editable source must belong to a figure asset or its work folder")
    if value.get("render") and (not value["render"].startswith("wiki/assets/") or not value["render"].endswith("/render.json")):
        raise ValueError("render receipt must be wiki/assets/**/render.json")
    if "asset" in value and not value["asset"].startswith("wiki/assets/"):
        raise ValueError("candidate asset must be under wiki/assets/")
    return value


def topic(repo: Path, page: str) -> str:
    meta = frontmatter.split(safefs.read_text(repo, page)).meta
    for lesson in meta.get("lessons", []):
        if lesson.get("topics"):
            target = resolve(page, lesson["topics"][0])
            if target and safefs.is_file(repo, target):
                return target
    return page


def order(repo: Path, brief: dict) -> tuple:
    page = brief["page"]
    meta = frontmatter.split(safefs.read_text(repo, page)).meta
    rank = 0 if page == topic(repo, page) else 1 if meta.get("lessons") else 2
    matches = markers(repo).get(brief["id"], [])
    return topic(repo, page), rank, page, matches[0][1] if matches else 0, brief["id"]


def check(repo: Path, assignments: list[dict]) -> list[dict]:
    from ..wiki.check import item
    try:
        validate_assignments(repo, assignments)
    except (ValueError, OSError) as exc:
        return [item(".school-notes/result.json", None, f"figures: {exc}")]
    return []


def _inserted(repo: Path, brief: dict) -> bool:
    from .context import verdict_key
    fid = brief["id"]
    if blocks.read(safefs.read_text(repo, brief["page"]), f"figure-{fid}") is None:
        return False
    evidence = safefs.read_json(repo, f"docs/evidence/media/{fid}/figure.json", {})
    return (evidence.get("verdict", {}).get("verdict") == "accept" and
            evidence["verdict"]["key"] == verdict_key(repo, brief, candidate(repo, brief)))
