#!/usr/bin/env python3
"""Make the rows of a learner's PROFILE *Wording* table the template's (shared rules 1.22.8,
Wiki workflows *Template updates*): mechanical and deterministic, so every learner carries the
same wording.

The table is the first one under the `# Wording` heading. The learner's own column layout
stays (a learner has `| Key | Magyar |`, the template `| Key | English | Magyar |`): of each
template row only the columns the learner's table has are taken. Learner-bound rows are never
touched: the keys in `KEEP`, and any row whose value holds the learner's name (the first word of
the learner's `wiki title`). A row only the learner has stays, after the template's rows, in its
own order. Nothing else in PROFILE.md changes. `--check` only reports the keys that would change
(exit 1)."""
import argparse
import re
import sys
from pathlib import Path

KEEP = ("wiki title",)                     # learner-bound: never synced


def cells(line):
    """The cells of a Markdown table row; an escaped `\\|` stays inside its cell."""
    parts = re.split(r"(?<!\\)\|", line.strip())
    return [p.strip() for p in parts[1:-1]]


def table(lines):
    """(header cells, first body row, end) of the first table under `# Wording`."""
    start = next((i for i, line in enumerate(lines) if re.match(r"^#{1,3} Wording\s*$", line)), None)
    if start is None:
        raise ValueError("no `# Wording` heading")
    for i in range(start + 1, len(lines)):
        if re.match(r"^#{1,3} ", lines[i]):
            break
        if lines[i].startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s|:-]+\|\s*$", lines[i + 1]):
            end = i + 2
            while end < len(lines) and lines[end].startswith("|"):
                end += 1
            return cells(lines[i]), i + 2, end
    raise ValueError("no table under `# Wording`")


def learner_name(rows):
    title = next((r[1] for r in rows if r and r[0] == "wiki title" and len(r) > 1), "").strip("`")
    words = re.findall(r"[^\W\d_]+", title)
    return words[0] if words and not title.startswith("<") else ""


def synced(template_text, target_text):
    t, g = template_text.split("\n"), target_text.split("\n")
    t_head, ts, te = table(t)
    g_head, gs, ge = table(g)
    missing = [c for c in g_head[1:] if c not in t_head]
    if missing:
        raise ValueError(f"the template's Wording table has no column {missing}")
    columns = [t_head.index(c) for c in g_head]
    own_rows = [cells(line) for line in g[gs:ge]]
    own = {r[0]: line for line, r in zip(g[gs:ge], own_rows) if r}
    name = learner_name(own_rows)
    rows, seen = [], set()
    for line in t[ts:te]:
        r = cells(line)
        if not r:
            continue
        key = r[0]
        seen.add(key)
        mine = own.get(key)
        bound = key in KEEP or (name and mine and name in mine)
        if bound and not mine:
            continue
        rows.append(mine if bound else "| " + " | ".join(r[i] for i in columns) + " |")
    rows += [own[r[0]] for r in own_rows if r and r[0] not in seen]
    return "\n".join(g[:gs] + rows + g[ge:])


def changed_keys(old, new):
    def rows(text):
        lines = text.split("\n")
        _, start, end = table(lines)
        return {cells(line)[0]: line for line in lines[start:end] if cells(line)}
    a, b = rows(old), rows(new)
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--template", type=Path, required=True, help="template checkout")
    parser.add_argument("--target", type=Path, required=True, help="learner wiki checkout")
    parser.add_argument("--check", action="store_true", help="report only")
    args = parser.parse_args(argv)
    source = (args.template / "PROFILE.md").read_text(encoding="utf-8")
    path = args.target / "PROFILE.md"
    old = path.read_text(encoding="utf-8")
    new = synced(source, old)
    keys = changed_keys(old, new)
    if not keys:
        print("PROFILE Wording: in sync")
        return 0
    print(f"PROFILE Wording: {len(keys)} rows differ from the template: {', '.join(keys)}")
    if args.check:
        return 1
    path.write_text(new, encoding="utf-8")
    print("PROFILE Wording: synced from the template")
    return 0


if __name__ == "__main__":
    sys.exit(main())
