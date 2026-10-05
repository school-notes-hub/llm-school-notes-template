"""Exact accounting, reference validation and canonical output ordering."""

from ..schemas import validate


def exact(values, wanted, field):
    got = [v[field] for v in values]
    if len(got) != len(set(got)) or set(got) != set(wanted):
        raise ValueError(f"{field}: exactly one verdict per assigned identifier required")


def check(value, stage, assigned, known=None, *, allowed_paths=()):
    validate(stage, value)
    if stage == "reader-1":
        check_first(value, assigned, known, allowed_paths)
    elif stage == "reader-2":
        check_list(value, assigned)
    else:
        check_recheck(value, assigned, known, allowed_paths)
    for field, key in (("pages", "file"), ("findings", "id"), ("items", "key"), ("hits", "hit_id")):
        if field in value:
            value[field] = sorted(value[field], key=lambda row: row[key])
    return value


def check_first(value, assigned, known, allowed_paths):
    pages = [p["file"] for p in assigned["pages"]]
    allowed = set(pages) | set(allowed_paths)
    for finding in value["findings"]:
        path = finding["file"]
        canonical = "wiki/" + (path[6:] if path.startswith("/work/") else path)
        if path not in allowed and canonical in allowed:
            finding["file"] = canonical
    ignored = sorted((f for f in value["findings"] if f["file"] not in allowed),
                     key=lambda f: (f["file"], f["id"]))
    value["owner_notes"] += [f"Kihagyott lelet ({f['id']}, {f['file']}): "
                             f"az útvonal nincs a kiosztott vagy kontextusoldalak között. {f['problem']}"
                             for f in ignored]
    value["findings"] = [f for f in value["findings"] if f["file"] in allowed]
    value["pages"] = [p for p in value["pages"] if p["file"] in pages]
    exact(value["pages"], pages, "file")
    if any(p["verdict"] == "changes" and not any(f["file"] == p["file"] for f in value["findings"])
           for p in value["pages"]):
        paths = ", ".join(sorted({f["file"] for f in ignored}))
        raise ValueError("changes page verdict needs a finding" + (f"; ignored paths: {paths}" if paths else ""))
    ids = [f["id"] for f in value["findings"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate finding id")
    for f in value["findings"]:
        decisions = (known or {}).get("pages", {}).get(f["file"], {}).get("decisions", [])
        if f["relates_to"] in decisions and not f.get("new_evidence", "").strip():
            raise ValueError("decision-related finding requires new_evidence")


def check_list(value, assigned):
    exact(value["hits"], assigned["hits"], "hit_id")
    for hit in value["hits"]:
        if hit["covered_by"] is not None and hit["covered_by"] not in assigned["findings"]:
            raise ValueError("covered_by must name a pass1 finding")


def check_recheck(value, assigned, known, allowed_paths):
    ids = [f["id"] for f in value.get("findings", [])]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate finding id")
    for finding in value.get("findings", []):
        path = finding["file"]
        canonical = "wiki/" + (path[6:] if path.startswith("/work/") else path)
        if path not in allowed_paths and canonical in allowed_paths:
            finding["file"] = canonical
        decisions = (known or {}).get("pages", {}).get(finding["file"], {}).get("decisions", [])
        if finding["relates_to"] in decisions and not finding.get("new_evidence", "").strip():
            raise ValueError("decision-related finding requires new_evidence")
    exact(value["items"], [i["key"] for i in assigned["items"]], "key")
    states = {i["key"]: i["status"] for i in assigned["items"]}
    for finding in value.get("findings", []) + value["hits"]:
        if finding.get("item_key") is not None and finding["item_key"] not in states:
            raise ValueError("item_key must name an item corrected in this round")
    for item in value["items"]:
        allowed = ("ok", "not-ok") if states[item["key"]] == "fixed" else ("accept", "keep")
        if item["verdict"] not in allowed:
            raise ValueError("recheck verdict does not match closure status")
    exact(value["hits"], assigned["hits"], "hit_id")
