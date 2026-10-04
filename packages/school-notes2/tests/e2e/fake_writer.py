"""Stands in for the writer LLM: reads fetch.json, writes one lesson page, the log entry and
result.json – exactly the files the real writer is allowed to touch."""

import json
import sys
from pathlib import Path

work = Path(sys.argv[1])
mode = sys.argv[2] if len(sys.argv) > 2 else "good"
fetch = json.loads((work / ".school-notes/fetch.json").read_text())
seqs = [p["seq"] for p in fetch["pages"] if not p["duplicate_of"]]
note = "wiki/proba/2026-10-02-teszt-jegyzet.md"
(work / note).write_text(
    "---\ntitle: Teszt óra (órai jegyzet)\ndescription: Füzetjegyzet a teszt óráról.\n"
    "tags: [proba]\nlessons:\n  - {date: '2026-10-02', title: Teszt óra, topics: [elso.md]}\n"
    "---\n\n# Mit tanultunk ezen az órán\n\n"
    "* [Első](elso.md#elso)\n* [Második](elso.md#masodik)\n* [Példa](elso.md#pelda)\n" + ("[rossz](nincs-ilyen.md)\n" if mode == "badlink" else ""),
    encoding="utf-8")
log = work / "wiki/log.md"
log.write_text(log.read_text(encoding="utf-8") + "\n## 2026-10-03\n\n* **Update**: Teszt óra feldolgozva.\n",
               encoding="utf-8")
result = {"status": "done", "notes": [{"file": note, "pages": seqs}]}
if mode == "question":
    result = {"status": "question", "questions": [{"text": "Melyik tantárgy füzete ez?"}]}
calls = work / ".school-notes" / "calls"
with open(work.parent / f"{work.name}-writer-calls.log", "a") as stream:
    stream.write(f"{fetch['range']['k']}/{fetch['range']['n']}\n")
(work / ".school-notes/result.json").write_text(json.dumps(result), encoding="utf-8")
