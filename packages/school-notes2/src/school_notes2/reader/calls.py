"""Bounded role calls with durable receipts and recovery of interrupted output."""

from dataclasses import replace

from ..llm import launch
from ..review import relations
from ..state import safefs
from ..state.errors import BadWork, Transient, WaitingQuota
from . import contracts

TIMEOUTS = {"reader-1": 1800, "reader-2": 600, "recheck": 1200}


def run(repo, view, folder, stage, assigned, configured, *, log, invoke=None):
    invoke = invoke or launch.run_headless
    folder.mkdir(parents=True, exist_ok=True)
    known = relations.inventory(repo)
    saved = safefs.read_json(folder, "receipt.json")
    if saved is not None:
        return saved
    state = safefs.read_json(folder, "state.json", {"attempts": [], "status": "ready"})
    role = replace(configured, role_name=stage, role=replace(configured.role, timeout_s=TIMEOUTS[stage]),
                   mounts=launch.Mounts(work=view / "wiki", work_readonly=True,
                                       in_dir=folder / "in", out_dir=folder / "out"),
                   output_host=folder / "out/review.json", schema=stage,
                   label=folder.parent.name + "-" + stage, task_dir=folder)
    while state["status"] != "missing":
        if state["attempts"] and state["attempts"][-1] == "running":
            try:
                value = contracts.check(safefs.read_json(folder, "out/review.json"), stage, assigned, known)
            except (ValueError, OSError):
                _fail(folder, state, "crash", "interrupted call without valid output")
                continue
            return _save(folder, value, role)
        safefs.write_json(folder, "out/.ready.json", {})
        safefs.unlink(folder, "out/review.json")
        state["attempts"].append("running")
        safefs.write_json(folder, "state.json", state)
        try:
            outcome = invoke(replace(role, attempt=len(state["attempts"])), log=log, snapshot=lambda: launch.tree_fingerprint(folder / "out"))
            value = contracts.check(outcome.output, stage, assigned, known)
        except WaitingQuota:
            state["attempts"].pop()
            safefs.write_json(folder, "state.json", state)
            raise
        except launch.TimedOut as exc:
            _fail(folder, state, "timeout", str(exc))
        except Transient as exc:
            _fail(folder, state, "crash", str(exc))
        except (BadWork, ValueError) as exc:
            _fail(folder, state, "format", str(exc))
        else:
            return _save(folder, value, role)
    receipt = {"status": "not_checked", "reason": state["reason"]}
    safefs.write_json(folder, "receipt.json", receipt)
    return receipt


def _fail(folder, state, kind, message):
    state["attempts"][-1] = kind
    state["reason"] = message
    state["status"] = "missing" if kind == "timeout" or state["attempts"].count(kind) >= 2 else "ready"
    safefs.write_json(folder, "state.json", state)
    safefs.write_json(folder, "in/format-error.json", {"error": message})


def _save(folder, value, role):
    receipt = {"status": "reviewed", "model": f"{role.role.model}/{role.role.effort}", "review": value}
    safefs.write_json(folder, "receipt.json", receipt)
    return receipt
