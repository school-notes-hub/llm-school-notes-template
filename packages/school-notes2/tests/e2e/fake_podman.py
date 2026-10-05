#!/usr/bin/env python3
"""A `podman` for the end-to-end test: login checks pass, the writer is fake_writer.py."""

import os
import subprocess
import sys
from pathlib import Path

args = sys.argv[1:]
if not args or args[0] in ("rm", "stop", "info"):
    sys.exit(0)
if args[0] != "run":
    sys.exit(0)
work = next((a.split(":")[0] for a in args if a.endswith(":/work:rw")), None)
image = next(i for i, a in enumerate(args) if a.startswith("localhost/school-notes-agent"))
command = args[image + 1:]
if command[-2:] == ["auth", "status"] or command[-2:] == ["login", "status"]:
    sys.exit(0)
prompt = sys.stdin.read()
out = next((a.split(":")[0] for a in args if a.endswith(":/out:rw")), None)
if out and any("-reader-" in a or "-recheck-" in a for a in args):
    import json
    incoming = next(a.split(":")[0] for a in args if a.endswith(":/in:ro"))
    assigned = json.loads(Path(incoming, "assigned.json").read_text())
    if "items" in assigned:  # the P5 recheck
        review = {"items": [{"severity": "javaslat", "key": i["key"], "verdict": "ok" if i["status"] == "fixed" else "accept",
                             "answer": "Rendben."} for i in assigned["items"]], "findings": [], "owner_notes": []}
    elif "pages" in assigned:
        review = {"pages": [{"file": p["file"], "verdict": "ok", "first_glance": ""}
                            for p in assigned["pages"]], "findings": [], "owner_notes": []}
    else:
        review = {"hits": [{"severity": "hiba", "hit_id": h, "verdict": "téves", "covered_by": None, "reason": "test"}
                           for h in assigned["hits"]], "owner_notes": []}
    Path(out, "review.json").write_text(json.dumps(review))
    sys.exit(0)
if out:                                   # the nightly reviewer: read-only /work, writes /out
    import json
    import re
    incoming = next(a.split(":")[0] for a in args if a.endswith(":/in:ro"))
    patch = Path(incoming, "diff.patch").read_text()
    page = re.search(r"^\+\+\+ b/(\S+)", patch, re.M)[1]
    line, added = 0, None
    for text in patch.split(f"+++ b/{page}\n", 1)[1].splitlines():
        hunk = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)", text)
        if hunk:
            line = int(hunk[1])
        elif text.startswith("+") and added is None:
            added = line
        elif text.startswith("diff "):
            break
        if not hunk and not text.startswith("-"):
            line += 1
    items = json.loads(Path(incoming, "items.json").read_text())
    review = {"findings": [
        {"severity": "hiba", "id": "R1", "file": page, "line": added, "quote": "Új bekezdés.",
         "problem": "Hiányzik egy példa.", "suggestion": "Adj hozzá egy példát.", "relates_to": None},
        {"severity": "hiba", "id": "R2", "file": page, "line": 1, "quote": "---",
         "problem": "Régi sor gondja.", "suggestion": "", "relates_to": None}],
        "items": [{"severity": "javaslat", "key": i["key"], "verdict": "ok" if i["status"] == "fixed" else "accept",
                   "answer": "Rendben."} for i in items], "owner_notes": []}
    Path(out, "review.json").write_text(json.dumps(review), encoding="utf-8")
    sys.exit(0)
writer = Path(__file__).with_name("fake_writer.py")
Path(work).with_name(f"{Path(work).name}-writer-prompt.txt").write_text(prompt, encoding="utf-8")
sys.exit(subprocess.call([sys.executable, str(writer), work, os.environ.get("FAKE_WRITER", "good")]))
