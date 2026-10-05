"""Sequential topic calls under the existing nightly/round admission and quota gate."""

from dataclasses import replace

from ..figures.render import Renderer
from ..llm import launch
from ..log import duration, now_iso
from ..notify import Notice, pending
from ..reader.units import slug
from ..review import night_figures, topic_call, topic_input, topic_result, topics
from ..state import safefs


def run(ctx, task):
    repo, work = ctx.bare(), ctx.worktree("review").work_tree
    from ..figures import migration_gate
    migration_gate.notify(ctx, work)
    configured, harness = ctx.cfg.role("reviewer")
    results = {e["unit"]["topic"]: e for e in task.get("topic_results", [])}
    blocked = {e["topic"]: e for e in topics.unblocked(
        task.get("blocked_topics", []), ctx.cfg.state_dir, ctx.name)}
    failures = {e["topic"]: e for e in topics.unblocked(
        task.get("nightly_state", {}).get("failed_topics", []), ctx.cfg.state_dir, ctx.name)}
    failures.update({e["topic"]: e for e in task.get("failed_topics", [])})
    for topic, entry in results.items():
        if entry["receipt"]["status"] == "reviewed":
            failures.pop(topic, None)
    task.set_phase("reviewing", blocked_topics=[blocked[k] for k in sorted(blocked)],
                   failed_topics=[failures[k] for k in sorted(failures)])
    for unit in task.get("units", []):
        topic = unit["topic"]
        if topic in blocked or topic in results:
            continue
        entry = _topic(ctx, task, unit, configured, harness, repo, work)
        if entry["receipt"]["status"] != "reviewed":
            _failed(ctx, task, unit, entry["receipt"], blocked)
        results[topic] = entry
        task.update(topic_results=[results[k] for k in sorted(results)],
                    blocked_topics=[blocked[k] for k in sorted(blocked)])
    complete = not blocked and all(topic_result.complete(results.get(u["topic"], {}))
                                   for u in task.get("units", []))
    task.update(all_topics_done=complete)
    topic_result.assemble(task, repo, work)
    task.set_phase("reviewed")


def _topic(ctx, task, unit, configured, harness, repo, work):
    topic = unit["topic"]
    folder = task.dir / "nightly" / slug(topic)
    data = safefs.read_json(folder, "input-receipt.json")
    if data is None:
        with duration(ctx.log, "review.topic_input"):
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
        task.update(failed_topics=[e for e in task.get("failed_topics", []) if e["topic"] != topic])
        role, _ = ctx.cfg.role("figure-review") if "figure-review" in ctx.cfg.roles else (replace(configured, timeout_s=1800), harness)
        renderer = Renderer(ctx.release() / "packages/study-site", ctx.cfg.browser,
                            folder / "render", timeout_s=ctx.cfg.timeouts.rasterize_s)
        selected = night_figures.targeted(repo, work, unit, data["items"]) if unit["mode"] == "targeted" else None
        figures = night_figures.run(work, unit, folder, replace(call, role=role), renderer, ctx.log,
                                    view_folder=task.dir / "figure-view", selected=selected)
        entry.update(figure_retries=figures.get("retries", []), figure_records=figures["records"], figure_findings=figures["findings"], figure_notes=figures["notes"],
                     figure_pending=figures.get("pending", []), figure_checked=figures.get("checked", []))
    return entry


def _failed(ctx, task, unit, receipt, blocked):
    previous = topics.unblocked(task.get("nightly_state", {}).get("failed_topics", []),
                                ctx.cfg.state_dir, ctx.name)
    old = next((e for e in previous if e["topic"] == unit["topic"]), {})
    count = max(receipt.get("timeout_count", 0), old.get("count", 0) + 1)
    failures = {r["topic"]: r for r in task.get("failed_topics", [])}
    failures[unit["topic"]] = {"topic": unit["topic"], "count": count, "at": now_iso()}
    task.update(failed_topics=[failures[k] for k in sorted(failures)])
    if count < 2:
        return
    blocked[unit["topic"]] = {"topic": unit["topic"], "since_commit": unit["base"],
                               "reason": receipt["reason"], "at": now_iso()}
    if receipt.get("timeout_count", 0) >= 2:
        return  # T-125 already delivered the second-timeout notice.
    pending.send(ctx, Notice(ctx.name, f"nightly-blocked:{unit['topic']}:{task.run_id}", task.run_id,
                             "nightly", "éjszakai review", f"A témakör két éjszakán sikertelen: {unit['topic']}.",
                             f"Dönts az időkorlátról; school-notes status --clear {ctx.name} reviewer --continue"))
