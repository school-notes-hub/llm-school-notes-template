"""Shared review runtime; independent of P3/P5 orchestration."""

import subprocess

from ..figures import review as figure_review
from ..figures.render import Renderer
from ..llm import launch


def folder(task):
    path = task.dir / f"attempt-{task.get('attempt', 1)}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def role(ctx, task, name="reader"):
    configured, harness = ctx.cfg.role(name if name == "reader" or name in getattr(ctx.cfg, "roles", {}) else "reviewer")
    return launch.RoleRun(ctx.name, task.run_id, "reader-1", configured, harness,
                          ctx.image_tag(), launch.Mounts(), task.dir / "unused.json",
                          "reader-1", folder(task), grade=ctx.student.grade,
                          allowed_domains=ctx.cfg.provider_domains,
                          max_agents=task.get("max_agents", ctx.cfg.limits.max_agents),
                          lease_dir=ctx.cfg.state_dir / "agent-leases", attempt=task.get("attempt", 1))


def figures(ctx, task, batch, name):
    renderer = render(ctx, task)
    try:
        receipt = figure_review.run_batch(ctx.notes_path, batch, name, role(ctx, task, "figure-review"),
                                       render=renderer, log=ctx.log)
        from ..images import judgement
        judgement.record(ctx.image_settings(), batch, receipt)
        return receipt
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "pending", "reason": str(exc)}


def render(ctx, task):
    return Renderer(ctx.release() / "packages/study-site", ctx.cfg.browser,
                        folder(task) / "render", timeout_s=ctx.cfg.timeouts.rasterize_s)
