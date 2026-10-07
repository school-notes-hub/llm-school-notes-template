"""Image plans and markers (plan 4.6).

The LLM writes `.school-notes/images/<id>.json` and puts `<!-- image: <id> -->` where the
image belongs. The tool keeps a copy under state/image-plans/<learner>/ so a later run can
resume, and builds learning_image.py's job from it.

The job's target is the plan file itself, not the wiki page: the page keeps changing
while the LLM works, and learning_image.py refuses a job whose sources changed.
"""

import hashlib
import json
import re
from pathlib import Path

from ..schemas import validate
from ..state import safefs
from ..state.files import write_bytes, write_json
from .settings import ImageSettings

PLAN_ID = re.compile(r"^[a-z0-9-]{1,64}$")
IMMUTABLE_PREFIXES = ("sources/", "references/")


class PlanError(ValueError):
    pass


def check_id(plan_id: str) -> str:
    if not isinstance(plan_id, str) or not PLAN_ID.fullmatch(plan_id):
        raise PlanError("plan_id must match ^[a-z0-9-]{1,64}$")
    return plan_id


def job_id(learner: str, plan_id: str) -> str:
    """The ledger key: the ledger is shared by all learners, plan ids are per learner."""
    return f"{learner}-{check_id(plan_id)}"


def target(plan_id: str) -> str:
    return f".school-notes/images/{check_id(plan_id)}.json"


def read_plan(worktree: Path, rel: str) -> dict:
    """The plan file of the worktree, read without following any symlink (7.6)."""
    try:
        plan = json.loads(safefs.read_text(worktree, rel))
    except FileNotFoundError:
        raise PlanError(f"plan file missing: {Path(rel).name}") from None
    except json.JSONDecodeError as exc:
        raise PlanError(f"plan file is not JSON: {exc.msg}") from None
    validate("image-plan", plan)
    return plan


def keep(settings: ImageSettings, plan_id: str) -> Path:
    """Copy the worktree plan to state/image-plans/<learner>/ (validated first)."""
    data = safefs.read_bytes(settings.worktree, target(plan_id))
    read_plan(settings.worktree, target(plan_id))
    kept = settings.plans_dir / f"{plan_id}.json"
    write_bytes(kept, data)
    return kept


def _sha(worktree: Path, rel: str) -> str:
    return hashlib.sha256(safefs.read_bytes(worktree, rel)).hexdigest()


def build_job(settings: ImageSettings, plan_id: str) -> dict:
    """learning_image.py's job; the tool fills request_id, learner, target and hashes."""
    tgt = target(plan_id)
    plan = read_plan(settings.worktree, tgt)
    role = plan.pop("role")
    sources = [{"path": tgt, "sha256": _sha(settings.worktree, tgt)}]
    for claim in plan["claims"]:
        rel = claim["source"]
        if (rel.startswith(IMMUTABLE_PREFIXES) and safefs.is_file(settings.worktree, rel)
                and all(s["path"] != rel for s in sources)):
            sources.append({"path": rel, "sha256": _sha(settings.worktree, rel)})
    return {"id": job_id(settings.learner, plan_id), "request_id": settings.request_id, "learner": settings.learner,
            "target": tgt, "role": role, "sources": sources, "plan": plan}


def job_path(settings: ImageSettings, plan_id: str) -> Path:
    return settings.plans_dir / f"{check_id(plan_id)}.job.json"


def write_job(settings: ImageSettings, plan_id: str, job: dict) -> Path:
    path = job_path(settings, plan_id)
    write_json(path, job)
    return path
