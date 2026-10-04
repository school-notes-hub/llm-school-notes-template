"""Sequential topic calls under the existing nightly/round admission and quota gate."""

from dataclasses import replace

from ..figures.render import Renderer
from ..llm import launch
from ..log import now_iso
from ..notify import Notice, pending
from ..reader.units import slug
from ..review import night_figures, topic_call, topic_input, topic_result
from ..state import safefs
from ..state.files import read_json


def run(ctx, task):
    repo, work = ctx.bare(), ctx.worktree("review").work_tree
    configured, harness = ctx.cfg.role("reviewer")
    results = {e["unit"]["topic"]: e for e in task.get("topic_results", [])}
    blocked = {e["topic"]: e for e in task.get("blocked_topics", [])}
    cleared = read_json(ctx.cfg.state_dir / ctx.name / "nightly-cleared.json", {}).get("at", "")
    blocked = {k: v for k, v in blocked.items() if v.get("at", "") > cleared or not cleared}
    task.set_phase("reviewing", blocked_topics=[blocked[k] for k in sorted(blocked)])
    for unit in task.get("units", []):
        topic = unit["topic"]
        if topic in blocked or topic in results:
            continue
        folder = task.dir / "nightly" / slug(topic)
        data = safefs.read_json(folder, "input-receipt.json")
        if data is None:
            data = topic_input.prepare(repo, work, task, unit, folder / "in")
            safefs.write_json(folder, "input-receipt.json", data)
        call = launch.RoleRun(ctx.name, task.run_id, "reviewer", configured, harness,
                              ctx.image_tag(), launch.Mounts(), folder / "out/review.json", "nightly", folder,
                              grade=ctx.student.grade, label=slug(topic),
                              allowed_domains=ctx.cfg.provider_domains,
                              max_agents=task.get("max_agents", ctx.cfg.limits.max_agents),
                              lease_dir=ctx.cfg.state_dir / "agent-leases")
        receipt = topic_call.run(work, folder, data["assigned"], call, log=ctx.log)
        entry = {"unit": unit, "input": data, "receipt": receipt}
        if receipt["status"] == "reviewed":
            role, _ = ctx.cfg.role("figure-review") if "figure-review" in ctx.cfg.roles else (replace(configured, timeout_s=1800), harness)
            renderer = Renderer(ctx.release() / "packages/study-site", ctx.cfg.browser,
                                folder / "render", timeout_s=ctx.cfg.timeouts.rasterize_s)
            figures = night_figures.run(work, unit, folder, replace(call, role=role), renderer, ctx.log)
            entry.update(figure_records=figures["records"], figure_findings=figures["findings"], figure_notes=figures["notes"])
        else:
            _failed(ctx, task, unit, receipt, blocked)
        results[topic] = entry
        task.update(topic_results=[results[k] for k in sorted(results)],
                    blocked_topics=[blocked[k] for k in sorted(blocked)])
    complete = not blocked and all(results.get(u["topic"], {}).get("receipt", {}).get("status") == "reviewed"
                                   for u in task.get("units", []))
    task.update(all_topics_done=complete)
    topic_result.assemble(task, repo, work)
    task.set_phase("reviewed")


def _failed(ctx, task, unit, receipt, blocked):
    previous = task.get("nightly_state", {}).get("failed_topics", [])
    old = next((e for e in previous if e["topic"] == unit["topic"]), {})
    cleared = read_json(ctx.cfg.state_dir / ctx.name / "nightly-cleared.json", {}).get("at", "")
    previous_count = old.get("count", 0) if old.get("at", "") > cleared else 0
    count = receipt.get("timeout_count", previous_count + 1)
    failures = {r["topic"]: r for r in task.get("failed_topics", [])}
    failures[unit["topic"]] = {"topic": unit["topic"], "count": count, "at": now_iso()}
    task.update(failed_topics=[failures[k] for k in sorted(failures)])
    if count < 2:
        return
    blocked[unit["topic"]] = {"topic": unit["topic"], "since_commit": unit["base"],
                               "reason": receipt["reason"], "at": now_iso()}
    if "timeout_count" in receipt:
        return  # T-125 already delivered the second-timeout notice.
    pending.send(ctx, Notice(ctx.name, f"nightly-blocked:{unit['topic']}:{task.run_id}", task.run_id,
                             "nightly", "éjszakai review", f"A témakör két éjszakán sikertelen: {unit['topic']}.",
                             f"Dönts az időkorlátról; school-notes status --clear {ctx.name} reviewer --continue"))
