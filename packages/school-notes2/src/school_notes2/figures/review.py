"""Independently callable, bounded and resumable figure-review role (no phase wiring)."""

from dataclasses import replace
from pathlib import Path

from ..llm import launch
from ..schemas import validate
from ..state import safefs
from ..state.errors import BadWork, Transient
from . import commissions, context, inputs


def validate_output(value: dict, assigned: dict, repo: Path, briefs: list[dict]) -> None:
    validate("figure-review", value)
    wanted = {i["id"]: i["key"] for i in assigned["figures"]}
    got = [i["id"] for i in value["figures"]]
    if len(got) != len(set(got)) or set(got) != set(wanted):
        raise ValueError("every assigned figure needs exactly one verdict, no extras")
    by_id = {b["id"]: b for b in briefs}
    for verdict in value["figures"]:
        brief = by_id[verdict["id"]]
        current = context.verdict_key(repo, brief, commissions.candidate(repo, brief))
        if verdict["key"] != wanted[verdict["id"]] or current != verdict["key"]:
            raise ValueError(f"{verdict['id']}: stale verdict key")
        if verdict["verdict"] == "accept" and (verdict["defects"] or verdict["text_mismatch"]):
            raise ValueError("accept cannot contain outstanding defects or text mismatches")
        uses = [context.page_context(repo, brief["page"])] + context.other_uses(
            repo, brief, commissions.candidate(repo, brief))
        decisions = {d["id"] for use in uses for d in use["decisions"]}
        if verdict["relates_to"] in decisions and not verdict.get("new_evidence", "").strip():
            raise ValueError("decision-related finding requires new_evidence")


def run_batch(repo: Path, briefs: list[dict], name: str, run: launch.RoleRun, *,
              render: inputs.Render, log, invoke=launch.run_headless) -> dict:
    """Returns a trusted receipt or pending. The caller owns scheduling/quota/notifications.

    A saved valid response is reused after interruption. Retry counters are written before
    launch, so repeated crashes never create an unbounded loop. No writer home or MCP mount.
    """
    if run.harness.name != "claude-review":
        raise ValueError("figure review requires the configured claude-review harness")
    if not name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in name):
        raise ValueError("invalid review batch name")
    briefs = sorted(briefs, key=lambda b: commissions.order(repo, b))
    folder = run.task_dir / "figure-review" / name
    saved = safefs.read_json(folder, "accepted.json")
    if saved is not None:
        assigned = {"figures": [{"id": v["id"], "key": v["key"]} for v in saved["review"]["figures"]]}
        if {b["id"] for b in briefs} != {v["id"] for v in assigned["figures"]}:
            raise ValueError("saved review belongs to different assignments")
        validate_output(saved["review"], assigned, repo, briefs)
        _save(repo, name, saved)
        return saved
    assigned = inputs.prepare(repo, briefs, folder / "in", render)
    signature = context.digest({p: context.digest(safefs.read_bytes(folder, p).hex())
                                for p in safefs.walk_files(folder, "in") if p != "in/format-error.json"})
    state = safefs.read_json(folder, "state.json", {})
    if state and state["input"] != signature:
        raise ValueError("review input changed; use a new review batch (repair/recheck)")
    if not state:
        state = {"input": signature, "attempts": [], "status": "ready"}
        safefs.write_json(folder, "state.json", state)
    configured = replace(run, role_name="figure-review", role=replace(run.role, timeout_s=1800),
                         mounts=launch.Mounts(work=repo / "wiki", work_readonly=True,
                                             in_dir=folder / "in", out_dir=folder / "out"),
                         output_host=folder / "out/review.json", schema="figure-review",
                         label=name)
    return _resume(repo, briefs, name, configured, folder, assigned, state, log, invoke)


def _resume(repo, briefs, name, run, folder, assigned, state, log, invoke):
    while True:
        saved = safefs.read_json(folder, "accepted.json")
        if saved is not None:
            validate_output(saved["review"], assigned, repo, briefs)
            _save(repo, name, saved)
            return saved
        if state["status"] == "pending":
            return {"status": "pending", "reason": state["reason"]}
        if state["attempts"] and state["attempts"][-1] == "running":
            try:
                output = safefs.read_json(folder, "out/review.json")
                validate_output(output, assigned, repo, briefs)
            except (ValueError, OSError):
                _failure(folder, state, "crash", "interrupted call without valid output")
            else:
                return _accept(repo, briefs, name, run, folder, state, output)
        if state["status"] == "pending":
            continue
        safefs.unlink(folder, "out/review.json")
        state["attempts"].append("running")
        safefs.write_json(folder, "state.json", state)
        # Create the output directory before mounting it.
        safefs.write_json(folder, "out/.ready.json", {})
        try:
            outcome = invoke(run, log=log, snapshot=lambda: launch.tree_fingerprint(folder / "out"))
            output = outcome.output
            validate_output(output, assigned, repo, briefs)
        except launch.TimedOut:
            _failure(folder, state, "timeout", "figure reviewer timed out")
        except Transient as exc:
            _failure(folder, state, "crash", str(exc))
        except (BadWork, ValueError) as exc:
            _failure(folder, state, "format", str(exc))
        else:
            return _accept(repo, briefs, name, run, folder, state, output)


def _failure(folder, state, kind, reason):
    state["attempts"][-1] = kind
    state["reason"] = reason
    state["status"] = ("pending" if kind == "timeout" or state["attempts"].count(kind) >= 2
                       else "ready")
    safefs.write_json(folder, "state.json", state)
    safefs.write_json(folder, "in/format-error.json", {"error": reason})


def _accept(repo, briefs, name, run, folder, state, output):
    by_id = {v["id"]: v for v in output["figures"]}
    output = {**output, "figures": [by_id[b["id"]] for b in briefs]}
    receipt = {"status": "reviewed", "model": f"{run.role.model}/{run.role.effort}",
               "review": output, "input": state["input"]}
    safefs.write_json(folder, "accepted.json", receipt)  # durable before either repo write
    _save(repo, name, receipt)
    return receipt


def _save(repo, name, receipt):
    safefs.write_json(repo, f".school-notes/figure-review/{name}.json", receipt["review"])
    safefs.write_json(repo, f".school-notes/figure-review/{name}.receipt.json", receipt)
