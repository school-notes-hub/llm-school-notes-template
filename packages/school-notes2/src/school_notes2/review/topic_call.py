"""One bounded nightly call with crash-safe output receipts and exact accounting."""

from dataclasses import replace
import time

from ..llm import launch
from ..reader.contracts import exact
from ..schemas import validate
from ..state import safefs
from ..state.errors import BadWork, NeedsOwner, Prerequisite, Transient, WaitingQuota
from . import relations


def check(value, assigned, work):
    validate("nightly", value)
    exact(value["pages"], assigned["pages"], "file")
    exact(value["items"], [i["key"] for i in assigned["items"]], "key")
    exact(value["hits"], assigned["hits"], "hit_id")
    states = {i["key"]: i["status"] for i in assigned["items"]}
    for item in value["items"]:
        allowed = {"fixed": ("ok", "not-ok"), "disagree": ("accept", "keep"),
                   "open": ("open", "resolved"), "owner": ("open", "resolved")}[states[item["key"]]]
        if item["verdict"] not in allowed:
            raise ValueError("item verdict does not match assigned status")
    exact(value["findings"], {f["id"] for f in value["findings"]}, "id")
    known = relations.inventory(work)
    for finding in value["findings"]:
        if not finding["file"].startswith("wiki/") or not safefs.is_file(work, finding["file"]):
            raise ValueError("finding must name an existing wiki file")
        decisions = known["pages"].get(finding["file"], {}).get("decisions", [])
        if finding.get("relates_to") in decisions and not finding.get("new_evidence", "").strip():
            raise ValueError("decision reference requires new_evidence")
    for hit in value["hits"]:
        if hit.get("covered_by") is not None and hit["covered_by"] not in {f["id"] for f in value["findings"]}:
            raise ValueError("covered_by must name an independent finding")
    for field, key in (("pages", "file"), ("findings", "id"), ("items", "key"), ("hits", "hit_id")):
        value[field].sort(key=lambda row: row[key])
    return value


def run(work, folder, assigned, configured, *, log, invoke=None):
    invoke = invoke or launch.run_headless
    saved = safefs.read_json(folder, "receipt.json")
    if saved is not None:
        return saved
    state = safefs.read_json(folder, "call.json", {"attempts": [], "status": "ready", "duration_s": 0})
    configured = replace(configured, mounts=launch.Mounts(work=work, work_readonly=True,
                         in_dir=folder / "in", out_dir=folder / "out"),
                         output_host=folder / "out/review.json", schema="nightly", task_dir=folder)
    while state["status"] != "failed":
        if state["attempts"] and state["attempts"][-1] == "running":
            try:
                value = check(safefs.read_json(folder, "out/review.json"), assigned, work)
            except (ValueError, OSError):
                _fail(folder, state, "crash", "interrupted call without valid output")
                continue
            return _save(folder, value, configured, state)
        safefs.write_json(folder, "out/.ready.json", {})
        safefs.unlink(folder, "out/review.json")
        state["attempts"].append("running")
        safefs.write_json(folder, "call.json", state)
        started = time.monotonic()
        try:
            outcome = invoke(replace(configured, attempt=len(state["attempts"])), log=log,
                             snapshot=lambda: launch.tree_fingerprint(folder / "out"))
            value = check(outcome.output, assigned, work)
        except (WaitingQuota, Prerequisite, NeedsOwner):
            state["attempts"].pop()
            safefs.write_json(folder, "call.json", state)
            raise
        except launch.TimedOut as exc:
            _fail(folder, state, "timeout", str(exc))
            state["timeout_count"] = exc.details.get("count", 2 if exc.details.get("suspended") else 1)
        except Transient as exc:
            _fail(folder, state, "crash", str(exc))
        except (BadWork, ValueError) as exc:
            _fail(folder, state, "format", str(exc))
        else:
            state["duration_s"] += time.monotonic() - started
            return _save(folder, value, configured, state)
        state["duration_s"] += time.monotonic() - started
        safefs.write_json(folder, "call.json", state)
    receipt = {"status": "failed", **state}
    safefs.write_json(folder, "receipt.json", receipt)
    return receipt


def _fail(folder, state, kind, message):
    state["attempts"][-1] = kind
    state["reason"] = message
    state["status"] = "failed" if kind == "timeout" or state["attempts"].count(kind) >= 2 else "ready"
    safefs.write_json(folder, "call.json", state)
    safefs.write_json(folder, "in/format-error.json", {"error": message})


def _save(folder, value, run, state):
    receipt = {"status": "reviewed", "review": value, "model": f"{run.role.model}/{run.role.effort}",
               "duration_s": state["duration_s"]}
    safefs.write_json(folder, "receipt.json", receipt)
    return receipt
