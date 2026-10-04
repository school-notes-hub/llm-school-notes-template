"""Exact accounting, reference validation and canonical output ordering."""

from ..schemas import validate


def exact(values, wanted, field):
    got = [v[field] for v in values]
    if len(got) != len(set(got)) or set(got) != set(wanted):
        raise ValueError(f"{field}: exactly one verdict per assigned identifier required")


def check(value, stage, assigned, known=None):
    validate(stage, value)
    if stage == "reader-1":
        pages = [p["file"] for p in assigned["pages"]]
        value["pages"] = [p for p in value["pages"] if p["file"] in pages]
        exact(value["pages"], pages, "file")
        if any(p["verdict"] == "changes" and not any(f["file"] == p["file"] for f in value["findings"])
               for p in value["pages"]):
            raise ValueError("changes page verdict needs a finding")
        ids = [f["id"] for f in value["findings"]]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate finding id")
        for f in value["findings"]:
            decisions = (known or {}).get("pages", {}).get(f["file"], {}).get("decisions", [])
            if f["relates_to"] in decisions and not f.get("new_evidence", "").strip():
                raise ValueError("decision-related finding requires new_evidence")
    elif stage == "reader-2":
        exact(value["hits"], assigned["hits"], "hit_id")
        for hit in value["hits"]:
            if hit["covered_by"] is not None and hit["covered_by"] not in assigned["findings"]:
                raise ValueError("covered_by must name a pass1 finding")
    else:
        exact(value["items"], [i["key"] for i in assigned["items"]], "key")
        states = {i["key"]: i["status"] for i in assigned["items"]}
        for item in value["items"]:
            allowed = ("ok", "not-ok") if states[item["key"]] == "fixed" else ("accept", "keep")
            if item["verdict"] not in allowed:
                raise ValueError("recheck verdict does not match closure status")
        exact(value["hits"], assigned["hits"], "hit_id")
    for field, key in (("pages", "file"), ("findings", "id"), ("items", "key"), ("hits", "hit_id")):
        if field in value:
            value[field] = sorted(value[field], key=lambda row: row[key])
    return value
