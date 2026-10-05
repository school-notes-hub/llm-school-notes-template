"""Durable, replay-safe automatic repair counts, independent of finding provenance."""

LIMIT = 3


def inherited(finding, known):
    other = known["items"].get(finding.get("relates_to"), {})
    return {key: other[key] for key in ("repair_attempts", "repair_runs") if key in other}


def record(detail, run_id):
    runs = detail.get("repair_runs", [])
    if run_id not in runs:
        detail["repair_attempts"] = detail.get("repair_attempts", 0) + 1
        detail["repair_runs"] = sorted([*runs, run_id])
    return detail


def failed_status(detail):
    return "owner" if detail.get("repair_attempts", 0) >= LIMIT else "open"


def decision(finding, known):
    ref = finding.get("relates_to")
    return (finding.get("category") == "forrásellentmondás" or
            ref is not None and ref in known["pages"].get(finding.get("file"), {}).get("decisions", []))
