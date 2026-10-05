"""Exact accounting, reference validation and canonical output ordering."""

from ..schemas import validate


def exact(values, wanted, field):
    got = [v[field] for v in values]
    if len(got) != len(set(got)) or set(got) != set(wanted):
        raise ValueError(f"{field}: exactly one verdict per assigned identifier required")


def check(value, stage, assigned, known=None, *, allowed_paths=()):
    validate(stage, value)
    pages = [p["file"] for p in assigned.get("pages", [])]
    _own_pages(value, set(pages) | set(allowed_paths))
    if stage == "reader-1":
        value["pages"] = [p for p in value["pages"] if p["file"] in pages]
        exact(value["pages"], pages, "file")
        if any(p["verdict"] == "changes" and not any(f["file"] == p["file"] for f in value["findings"])
               for p in value["pages"]):
            raise ValueError("changes page verdict needs a finding")
    else:
        exact(value["items"], [i["key"] for i in assigned["items"]], "key")
        states = {i["key"]: i["status"] for i in assigned["items"]}
        for finding in value.get("findings", []):
            if finding.get("item_key") is not None and finding["item_key"] not in states:
                raise ValueError("item_key must name an item corrected in this run")
        for item in value["items"]:
            allowed = ("ok", "not-ok") if states[item["key"]] == "fixed" else ("accept", "keep")
            if item["verdict"] not in allowed:
                raise ValueError("recheck verdict does not match closure status")
    ids = [f["id"] for f in value.get("findings", [])]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate finding id")
    for f in value.get("findings", []):
        decisions = (known or {}).get("pages", {}).get(f["file"], {}).get("decisions", [])
        if f["relates_to"] in decisions and not f.get("new_evidence", "").strip():
            raise ValueError("decision-related finding requires new_evidence")
    for field, key in (("pages", "file"), ("findings", "id"), ("items", "key")):
        if field in value:
            value[field] = sorted(value[field], key=lambda row: row[key])
    return value


def _own_pages(value, allowed):
    """A finding on a page outside the assignment is an owner note, never an item."""
    findings = value.get("findings", [])
    for finding in findings:
        path = finding["file"]
        canonical = "wiki/" + (path[6:] if path.startswith("/work/") else path)
        if path not in allowed and canonical in allowed:
            finding["file"] = canonical
    outside = sorted((f for f in findings if f["file"] not in allowed), key=lambda f: (f["file"], f["id"]))
    value["owner_notes"] = value["owner_notes"] + [
        f"Kiosztáson kívüli oldal ({f['file']}): {f['problem']}" for f in outside]
    value["findings"] = [f for f in findings if f["file"] in allowed]
