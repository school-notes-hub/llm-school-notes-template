"""Which images can be generated now (plan 5.5), decided by the tool alone.

Pending: its marker is in the wiki, its plan exists, attempts are left, today's budget
is not used up, and no paid call has an unknown outcome. Exhausted images are listed
separately for `status` and the one-time e-mail.
"""

from ..state import safefs
from . import plans
from .budget import budget_left, unknown_calls
from .generate import awaiting_review, exhausted
from .settings import ImageSettings


def scan(settings: ImageSettings) -> dict:
    ledger = settings.ledger()
    waiting = bool(unknown_calls(ledger))
    has_budget = budget_left(ledger, settings.today(), settings.daily_usd, settings.reservation_usd,
                       settings.monthly_usd)
    result = {"pending": [], "exhausted": [], "missing_plan": [],
              "waiting_unknown": waiting, "budget_left": has_budget}
    from ..figures import migration_gate
    frozen = set()
    if migration_gate.blocked(settings.worktree):
        frozen = {e["commission"]["id"] for e in safefs.read_json(settings.worktree, migration_gate.PATH, [])}
    for plan_id, pages in sorted(plans.find_markers(settings.worktree).items()):
        if plan_id in frozen:
            continue
        item = {"plan_id": plan_id, "page": pages[0]}
        entry = ledger["jobs"].get(plans.job_id(settings.learner, plan_id))
        if not _plan_exists(settings, plan_id):
            result["missing_plan"].append(item)
        elif entry and exhausted(entry, settings.max_attempts):
            result["exhausted"].append(item)
        elif (entry and awaiting_review(entry)) or (has_budget and not waiting):
            result["pending"].append(item)
    return result


def _plan_exists(settings: ImageSettings, plan_id: str) -> bool:
    return (safefs.is_file(settings.worktree, plans.target(plan_id))
            or (settings.plans_dir / f"{plan_id}.json").is_file())
