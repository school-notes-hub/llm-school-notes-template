#!/usr/bin/env python3
"""Make the rows of a learner's PROFILE *Wording* table the template's (shared rules 1.22.7,
Wiki workflows *Template updates*): mechanical and deterministic, so every learner carries the
same wording; nothing else in PROFILE.md changes. `--check` only reports a difference (exit 1)."""
import argparse
import re
import sys
from pathlib import Path

HEADER = re.compile(r"^\| Key \| English \| Magyar \|\s*$")


def table(lines):
    """(start, end) of the Wording table's body rows: after the header and its rule line."""
    for i, line in enumerate(lines):
        if HEADER.match(line):
            start = i + 2
            end = start
            while end < len(lines) and lines[end].startswith("|"):
                end += 1
            return start, end
    raise ValueError("no `| Key | English | Magyar |` Wording table")


def synced(template_text, target_text):
    t, g = template_text.split("\n"), target_text.split("\n")
    ts, te = table(t)
    gs, ge = table(g)
    return "\n".join(g[:gs] + t[ts:te] + g[ge:])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True, help="template checkout")
    parser.add_argument("--target", type=Path, required=True, help="learner wiki checkout")
    parser.add_argument("--check", action="store_true", help="report only")
    args = parser.parse_args(argv)
    source = (args.template / "PROFILE.md").read_text(encoding="utf-8")
    path = args.target / "PROFILE.md"
    old = path.read_text(encoding="utf-8")
    new = synced(source, old)
    if new == old:
        print("PROFILE Wording: in sync")
        return 0
    if args.check:
        print("PROFILE Wording: differs from the template")
        return 1
    path.write_text(new, encoding="utf-8")
    print("PROFILE Wording: synced from the template")
    return 0


if __name__ == "__main__":
    sys.exit(main())
