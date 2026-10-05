"""An error that already existed on the same page in the base never blocks a run.

The comparison is exact: the same file and the same message in the base check. Such an
error is reported as a warning; the tool never turns it into a review item (A1)."""

import yaml

from ..git.check_base import Tree
from ..wiki import check as wiki_check

KIND = "inherited-check"
MESSAGE = "Régi hiba, önmagában nem blokkolja ezt a futást: "


def classify(ctx, task, items):
    errors = wiki_check.errors(items)
    if not errors:
        return items
    try:
        base = Tree(ctx.worktree("notes"), task.get("base"))
        previous = wiki_check.check_files(ctx.notes_path, sorted({i["file"] for i in errors}), fs=base)
        old = {(i["file"], i["message"]) for i in wiki_check.errors(previous)}
    except (ValueError, yaml.YAMLError):
        ctx.log.event("check.base", "warning", message="Base check unavailable; all errors remain errors.")
        old = set()
    return [{**i, "severity": "warning", "kind": KIND, "message": MESSAGE + i["message"]}
            if i in errors and (i["file"], i["message"]) in old else i for i in items]
