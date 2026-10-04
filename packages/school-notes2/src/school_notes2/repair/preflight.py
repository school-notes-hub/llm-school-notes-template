"""Read the pinned local main before creating a repair task; never change the tree."""

import json
from pathlib import PurePosixPath

from ..wiki import frontmatter, pages
from . import queue


def require_ready(wt, base, topic):
    book = {}
    entries = wt.run("ls-tree", "-r", "-z", base, "--", "wiki").stdout.split(b"\0")
    for entry in sorted(e for e in entries if e):
        info, raw = entry.split(b"\t", 1)
        rel = raw.decode("utf-8")
        if (info.split()[0] not in (b"100644", b"100755") or not rel.endswith(".md")
                or rel.startswith("wiki/assets/") or PurePosixPath(rel).name in pages.RESERVED):
            continue
        page = frontmatter.split(wt.run("show", f"{base}:{rel}").stdout.decode("utf-8"))
        if page.meta.get("type"):
            book[rel] = page
    stored = wt.run("show", f"{base}:{queue.PATH}", check=False)
    data = queue.validated(json.loads(stored.stdout) if stored.returncode == 0 else None)
    queue.require_ready(topic, data, book)
