"""Entry points (plan 9.2): a thin layer over the flows."""

import argparse
import json
import os
import resource
import sys
from pathlib import Path

from . import VERSION, config
from .state import phase


def _harden() -> None:
    """No core dumps of a process that holds secrets (7.2); files private by default."""
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        import ctypes
        ctypes.CDLL(None).prctl(4, 0, 0, 0, 0)        # PR_SET_DUMPABLE = 0
    except (OSError, AttributeError):
        pass


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="school-notes", description=f"School Notes v2 ({VERSION})")
    p.add_argument("--config", type=Path, default=None)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("run", "nightly", "setup", "fetch", "finish"):
        sub.add_parser(name).add_argument("learner")
    repair = sub.add_parser("repair")
    repair.add_argument("learner")
    selection = repair.add_mutually_exclusive_group(required=True)
    selection.add_argument("--topic")
    selection.add_argument("--queue", action="store_true")
    repair.add_argument("--no-push", action="store_true")
    login = sub.add_parser("login")
    login.add_argument("learner")
    login.add_argument("role", choices=("writer", "reviewer"))
    chat = sub.add_parser("chat")
    chat.add_argument("learner")
    chat.add_argument("harness", nargs="?", choices=("codex", "claude"))
    status = sub.add_parser("status")
    status.add_argument("learner", nargs="?")
    status.add_argument("--json", action="store_true")
    status.add_argument("--clear", nargs=2, metavar=("LEARNER", "KIND"))
    action = status.add_mutually_exclusive_group()
    action.add_argument("--continue", dest="action", action="store_const", const="continue")
    action.add_argument("--discard", dest="action", action="store_const", const="discard")
    mcp = sub.add_parser("mcp")
    mcp.add_argument("--student", required=True)
    mcp.add_argument("--mode", choices=("cron", "interactive"), required=True)
    mcp.add_argument("--socket", type=Path, required=True)
    sub.add_parser("verify-tasks")
    return p


def main(argv: list[str] | None = None) -> int:
    _harden()
    args = _parser().parse_args(argv)
    cfg = config.load(args.config)
    from .flows import context
    if args.command == "verify-tasks":
        return _verify_tasks(cfg)
    if args.command == "status":
        return _status(cfg, args, context)
    ctx = context.make(cfg, getattr(args, "learner", None) or args.student)
    return _dispatch(ctx, args)


def _dispatch(ctx, args) -> int:
    from .flows import chat, nightly, run, setup
    if args.command == "repair":
        from .flows import repair
        return repair.repair(ctx, topic=args.topic, build_queue=args.queue, no_push=args.no_push)
    if args.command == "run":
        return run.run(ctx)
    if args.command == "nightly":
        return nightly.nightly(ctx)
    if args.command == "setup":
        setup.setup(ctx)
        return 0
    if args.command == "chat":
        return chat.chat(ctx, args.harness)
    if args.command in ("fetch", "finish"):
        return _owner_step(ctx, args.command)
    if args.command == "mcp":
        return _mcp(ctx, args)
    if args.command == "login":
        return _login(ctx, args.role)
    raise SystemExit(f"unknown command {args.command}")


def _owner_step(ctx, command: str) -> int:
    """`fetch`/`finish` from the host shell: the same functions as the session's MCP."""
    from .flows import chat, policy
    lock = ctx.lock()
    lock.acquire(command, on_wait=lambda h: print(f"várok a zárra ({h.get('kind')})…"))
    try:
        answer = chat.session_fetch(ctx) if command == "fetch" else chat.session_finish(ctx)
    except Exception as exc:  # noqa: BLE001 - one error policy for every entry point (8)
        policy.on_error(exc, task=None, student=ctx.name, step=command, log=ctx.log,
                        mailer=None, interactive=True)
        print(f"Hiba: {exc}", file=sys.stderr)
        return 1
    finally:
        lock.release()
    print(json.dumps(answer, ensure_ascii=False, indent=2))
    return 0


def _login(ctx, role_name: str) -> int:
    """The owner's one-off harness login on the role's home volume (7.4, 10.4)."""
    from .llm import launch
    role, harness = ctx.cfg.role(role_name)
    return launch.run_login(learner=ctx.name, role=role_name, harness=harness,
                            image=ctx.image_tag(), log=ctx.log,
                            allowed_domains=ctx.cfg.provider_domains + ctx.cfg.login_domains)


def _mcp(ctx, args) -> int:
    """A standalone MCP server (normally the launcher starts it in-process)."""
    from .flows import handlers
    from .flows.session import secret_values
    from .mcp.server import McpServer
    task = phase.open_task(ctx.task_root(), ctx.name, "notes")
    server = McpServer(student=ctx.name, mode=args.mode, handlers=handlers.build(ctx, None),
                       log=ctx.log, jobs_dir=(task.dir if task else ctx.cfg.state_dir) / "jobs",
                       run_id=lambda: task.run_id if task else "", log_path=str(ctx.cfg.log_path),
                       secrets=secret_values(ctx), wait_s=ctx.cfg.limits.mcp_wait_s)
    server.serve(args.socket)
    return 0


def _status(cfg, args, context) -> int:
    from .flows import clear, status
    if args.clear:
        learner, kind = args.clear
        if kind not in ("notes", "review", "publish") or not args.action:
            raise SystemExit("usage: status --clear <learner> notes|review|publish "
                             "--continue|--discard")
        print(clear.clear(context.make(cfg, learner), kind, args.action))
        return 0
    learners = [args.learner] if args.learner else list(cfg.students)
    data = [status.summary(context.make(cfg, name, console=False)) for name in learners]
    print(json.dumps(data, ensure_ascii=False, indent=2) if args.json
          else "\n\n".join(status.render(d) for d in data))
    return 0


def _verify_tasks(cfg) -> int:
    """For install.sh: every open task must be readable by this release (10.1)."""
    for name in cfg.students:
        try:
            phase.all_tasks(cfg.root, name)
        except RuntimeError as exc:
            print(f"{name}: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
