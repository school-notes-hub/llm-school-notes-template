"""`sn` – the local, interactive command line (local pipeline plan 3.2). It knows only these
commands; each lives in `school_notes2/local/<command>.py`:

  sn fetch <t> [--apply]                     Drive inbox: list; --apply: download, place, move
  sn book <t> <subject> <code> [<source>] [--offset N]   a textbook into references/
  sn check <t> <page…>                       page check, read-only
  sn gen <t> <figure-id> [--note FILE]       one paid image generation (ledger, ≤ 3 attempts)
  sn gen [<t>] --settle                      settle interrupted (unknown-outcome) attempts
  sn gen <t> <figure-id> --grant             a new frame of attempts – only on the owner's word
  sn close <t> [--subject a,b] [--check]     insert accepted figures, machine blocks, indexes
  sn close <t> --subject a --snapshot [--only id,…]   keys.json + diff.patch for the reviewer
  sn close <t> --rekey                       renew figure verdict keys recorded by sn 0.3.8 (only that)
  sn close <t> --dates                       hand-written date spans and lessons legends as generated
  sn done <t>                                content finished? exit 0/1
  sn publish <t> [--reviewed] [--build-only DIR]   push main, build, gate, gh-pages, live
  sn podcast <t> <subject> <page> --snapshot  the podcast script's checks + keys.json for the reviewer
  sn podcast <t> <subject> <page>            release an accepted episode: paid speech, name check, mix,
                                             page block, Podcast page, receipt, Drive

Exit codes: 0 done, 1 not done or an error, 2 `sn close` or `sn podcast` stopped before writing.
"""

import argparse
import os
import resource
import sys
from pathlib import Path

from . import VERSION
from .state.errors import SnError


def _harden() -> None:
    """No core dumps of a process that holds secrets; files private by default."""
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        import ctypes
        ctypes.CDLL(None).prctl(4, 0, 0, 0, 0)        # PR_SET_DUMPABLE = 0
    except (OSError, AttributeError):
        pass


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sn", description=f"School Notes, local ({VERSION})",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--config", type=Path, default=None)
    p.set_defaults(only=None, snapshot=False, rekey=False, dates=False)
    sub = p.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="Drive inbox")
    fetch.add_argument("learner")
    fetch.add_argument("--apply", action="store_true")
    book = sub.add_parser("book", help="a textbook into references/")
    book.add_argument("learner")
    book.add_argument("subject")
    book.add_argument("code", help="the book's stock number, e.g. OH-MIR11TB")
    book.add_argument("source", nargs="?", type=Path, help="the doc-extract folder; without it the map is regenerated")
    book.add_argument("--offset", type=int, help="printed page = PDF page - N (negative for an excerpt: --offset=-4)")
    check = sub.add_parser("check", help="page check, read-only")
    check.add_argument("learner")
    check.add_argument("pages", nargs="+")
    gen = sub.add_parser("gen", help="one paid image generation")
    gen.add_argument("learner", nargs="?")
    gen.add_argument("figure_id", nargs="?")
    gen.add_argument("--note", type=Path, help="repair note for the next attempt")
    gen.add_argument("--settle", action="store_true")
    gen.add_argument("--grant", action="store_true", help="only on the owner's explicit word")
    close = sub.add_parser("close", help="close a learner after the passes")
    close.add_argument("learner")
    close.add_argument("--subject", help="comma-separated subjects (default: every hand-over)")
    mode = close.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="dry run on a private copy")
    mode.add_argument("--snapshot", action="store_true",
                      help="before the reviewer (and before the confirmation pass with --only): "
                           "keys.json and diff.patch into the hand-over folder")
    mode.add_argument("--rekey", action="store_true",
                      help="only renew figure verdict keys recorded with the sn 0.3.8 key (exact matches)")
    mode.add_argument("--dates", action="store_true",
                      help="only rewrite hand-written date spans and the lessons legends as generated")
    close.add_argument("--only", help="with --snapshot: comma-separated figure ids to snapshot again")
    done = sub.add_parser("done", help="is the content finished?")
    done.add_argument("learner")
    publish = sub.add_parser("publish", help="release HEAD")
    publish.add_argument("learner")
    publish.add_argument("--reviewed", action="store_true", help="move claude-reviewed to HEAD")
    publish.add_argument("--build-only", type=Path, metavar="DIR", help="build into DIR, push nothing")
    podcast = sub.add_parser("podcast", help="one podcast episode about a topic page")
    podcast.add_argument("learner")
    podcast.add_argument("subject")
    podcast.add_argument("page", help="the topic page's file name without .md")
    podcast.add_argument("--snapshot", action="store_true",
                         help="before the reviewer: check the script, write keys.json; nothing is paid")
    return p


def main(argv: list[str] | None = None) -> int:
    _harden()
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "gen":
        if args.settle and args.grant:
            parser.error("--settle and --grant are separate")
        if not args.settle and not (args.learner and args.figure_id):
            parser.error("sn gen <learner> <figure-id> (or --settle)")
    if args.only and not (args.command == "close" and args.snapshot):
        parser.error("--only belongs to --snapshot")
    from .config import ConfigError
    from .local import common
    local = None
    try:
        learner = args.learner
        if learner is None:                      # `sn gen --settle`: the ledger is shared
            learner = common.learners(args.config)[0]
        local = common.load(learner, args.config)
        return _dispatch(local, args)
    except (SnError, ConfigError, ValueError, OSError) as exc:
        todo = getattr(exc, "todo", "")
        print(f"Hiba: {exc}" + (f"\nTeendő: {todo}" if todo else ""), file=sys.stderr)
        if local is not None:
            local.record(args.command, "error", error_class=getattr(exc, "kind", type(exc).__name__),
                         message=str(exc)[:300])
        return 1


def _dispatch(local, args) -> int:
    if args.command == "fetch":
        from .local import fetch
        return fetch.run(local, args.apply)
    if args.command == "book":
        from .local import book
        return book.run(local, args.subject, args.code, args.source, args.offset)
    if args.command == "check":
        from .local import check
        return check.run(local, args.pages)
    if args.command == "gen":
        from .local import gen
        return gen.run(local, args.figure_id, args.note, settle=args.settle, grant=args.grant)
    if args.command == "close":
        from .local import close
        subjects = sorted(s.strip() for s in args.subject.split(",") if s.strip()) if args.subject else None
        only = sorted(s.strip() for s in args.only.split(",") if s.strip()) if args.only else None
        if args.rekey:
            return close.rekey_only(local)
        if args.dates:
            return close.dates_only(local)
        return close.run(local, subjects, args.check, take_snapshot=args.snapshot, snapshot_only=only)
    if args.command == "done":
        from .local import done
        return done.run(local)
    if args.command == "publish":
        from .local import publish
        return publish.run(local, args.reviewed, args.build_only)
    if args.command == "podcast":
        from .local import podcast
        return podcast.run(local, args.subject, args.page, args.snapshot)
    raise SystemExit(f"unknown command {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
