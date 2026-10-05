"""Offline harness used by both real-bundle and synthetic completion probes."""
import json
import os
import runpy
import sys
from pathlib import Path

args = sys.argv[1:]
if not args or args[0] != "run" or args[-2:] in (["auth", "status"], ["login", "status"]):
    sys.exit(0)
sys.stdin.read()
mount = lambda suffix: next((Path(a.removesuffix(suffix)) for a in args if a.endswith(suffix)), None)
out = mount(":/out:rw")
if out:
    incoming = mount(":/in:ro")
    assigned = json.loads((incoming / "assigned.json").read_text())
    second = any("recheck-r2" in p for p in incoming.parts)
    if "figures" in assigned:
        value = {"figures": [{**f, "verdict": "accept" if second else "repair", "observed": "Két nyíl.",
            "defects": [] if second else [{"severity": "hiba", "location": "nyíl", "observed": "Hibás irány.",
                                          "expected": "Jó irány."}], "text_mismatch": [], "relates_to": None}
            for f in assigned["figures"]], "owner_notes": []}
    elif "items" in assigned:
        value = {"items": [{"key": i["key"], "severity": "hiba", "verdict": "ok" if second else "not-ok",
                            "answer": "A magyarázat helyes." if second else "A magyarázat hiányos."}
                           for i in assigned["items"]],
                 "hits": [{"hit_id": h, "severity": "hiba", "verdict": "téves", "reason": "Ellenőrizve.",
                           "item_key": None} for h in assigned["hits"]], "findings": [], "owner_notes": []}
    elif "pages" in assigned:
        value = {"pages": [{"file": p["file"], "verdict": "ok", "first_glance": "Érthető."}
                           for p in assigned["pages"]], "findings": [], "owner_notes": []}
    else:
        value = {"hits": [{"hit_id": h, "severity": "hiba", "verdict": "téves", "reason": "Ellenőrizve.",
                           "covered_by": None} for h in assigned["hits"]], "owner_notes": []}
    (out / "review.json").write_text(json.dumps(value, ensure_ascii=False))
else:
    sys.argv = ["probe_writer.py", str(mount(":/work:rw"))]
    runpy.run_path(str(Path(__file__).with_name("probe_writer.py")), run_name="__main__")
