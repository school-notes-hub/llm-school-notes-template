"""Writer contracts, unique markers and deterministic primary-topic assignment."""

import re
from pathlib import Path

from ..images.plans import check_id
from ..schemas import validate
from ..state import safefs
from ..wiki import frontmatter, markers as blocks
from ..wiki.pages import CODE_FENCE, INLINE_CODE, links, resolve, wiki_pages

MARKER = re.compile(r"<!-- (?:figure|image|figure-request): ([a-z0-9-]{1,64}) -->")
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
        check_identity(repo, brief)
        if any(brief[k] != assignment[k] for k in ("page", "kind")):
            raise ValueError(f"{fid}: assignment differs from commission")
        if not _inserted(repo, brief) and (len(found.get(fid, [])) != 1 or found[fid][0][0] != brief["page"]):
            raise ValueError(f"{fid}: marker must occur exactly once on its page")
        for page, position in found.get(fid, []):
            text = safefs.read_text(repo, page)
            start, end = text.rfind("\n", 0, position) + 1, text.find("\n", position)
            if not MARKER.fullmatch(text[start:end if end >= 0 else len(text)]):
                raise ValueError(f"{fid}: marker must stand alone on an unindented line")
        old = brief.get("replaces")
        if old and old in replaced:
            raise ValueError("at most one replacement per image per run")
        if old:
            replaced.add(old)
        result.append(brief)
    return result


def check_identity(repo: Path, brief: dict) -> None:
    fid = brief["id"]
    directory = f"docs/evidence/media/{fid}"
    evidence = safefs.read_json(repo, f"{directory}/figure.json", {})
    if safefs.exists(repo, directory) and evidence.get("commission") != brief:
        raise ValueError(f"{fid}: figure id already has a different evidence record")
    if evidence and evidence.get("candidate") != candidate(repo, brief):
        raise ValueError(f"{fid}: figure id already has a different accepted candidate; use a new id")
    for page in sorted(wiki_pages(repo)):
        if blocks.read(safefs.read_text(repo, page), f"figure-{fid}") is not None:
            if page != brief["page"] or evidence.get("commission") != brief:
                raise ValueError(f"{fid}: figure id already has an inserted block")
    from . import pending
    for entry in pending.load(repo):
        previous = entry["commission"]
        if previous["id"] == fid and any(previous[k] != brief[k] for k in ("page", "kind")):
            raise ValueError(f"{fid}: figure id already belongs to another pending commission")


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
    if any(c in value.get("alt", "") for c in "\r\n"):
        raise ValueError("alt must fit on one line")
    from . import licenses
    return licenses.candidate(repo, brief, value)


def topic(repo: Path, page: str) -> str:
    meta = frontmatter.split(safefs.read_text(repo, page)).meta
    for lesson in meta.get("lessons", []):
        if lesson.get("topics"):
            target = resolve(page, lesson["topics"][0].split("#", 1)[0])
            if target and safefs.is_file(repo, target):
                return target
    return page


def order(repo: Path, brief: dict) -> tuple:
    page = brief["page"]
    meta = frontmatter.split(safefs.read_text(repo, page)).meta
    rank = 0 if page == topic(repo, page) else 1 if meta.get("lessons") else 2
    matches = markers(repo).get(brief["id"], [])
    return topic(repo, page), rank, page, matches[0][1] if matches else 0, brief["id"]


def assignments(result: dict, pending: list[dict]) -> list[dict]:
    listed = list(result.get("figures", []))
    ids = {a["id"] for a in listed}
    listed += [{k: entry["commission"][k] for k in ("id", "page", "kind")}
               for entry in pending if entry["commission"]["id"] not in ids]
    return sorted(listed, key=lambda a: a["id"])


def check(repo: Path, assignments: list[dict], drawings: list[dict] = ()) -> list[dict]:
    from ..wiki.check import item
    out = []
    try:
        validate_assignments(repo, assignments)
    except (ValueError, OSError) as exc:
        out.append(item(".school-notes/result.json", None, f"figures: {exc}"))
    assigned = {a["id"]: a for a in assignments}
    for drawing in sorted(drawings, key=lambda d: (d["figure"], d["source"], d["crop"])):
        if assigned.get(drawing["figure"], {}).get("kind") != "notebook-drawing":
            out.append(item(".school-notes/result.json", None,
                            f"notebook_drawings: {drawing['figure']} needs an assigned notebook-drawing commission"))
    for fid in sorted(assigned):
        path = f".school-notes/figures/{fid}/figure.json"
        try:
            brief = read(repo, fid)
            if not safefs.is_file(repo, path):
                raise ValueError("missing figure.json; write a candidate or an explicit failed state with reason")
            out.extend(item(path, None, message) for message in preflight(repo, brief))
        except (ValueError, OSError) as exc:
            out.append(item(path, None, str(exc)))
    return out


def preflight(repo: Path, brief: dict) -> list[str]:
    from . import context, machine
    from .render import png
    value = candidate(repo, brief)
    if source := brief.get("source_image"):
        png(safefs.read_bytes(repo, source["path"]), crop=source["crop"])
    if value["state"] != "candidate":
        context.embedding(repo, brief, {"alt": "", "caption": ""})
        return []
    errors = machine.report(repo, brief, value)["errors"]
    context.embedding(repo, brief, value)
    if not errors:
        context.verdict_key(repo, brief, value)
    return errors


def _inserted(repo: Path, brief: dict) -> bool:
    from .context import verdict_key
    fid = brief["id"]
    if blocks.read(safefs.read_text(repo, brief["page"]), f"figure-{fid}") is None:
        return False
    evidence = safefs.read_json(repo, f"docs/evidence/media/{fid}/figure.json", {})
    return (evidence.get("verdict", {}).get("verdict") == "accept" and
            evidence["verdict"]["key"] == verdict_key(repo, brief, candidate(repo, brief)))
