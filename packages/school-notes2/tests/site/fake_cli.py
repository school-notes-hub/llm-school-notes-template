"""Stand-in for study-site's cli.mjs in tests (run with the Python interpreter as `node`).

build: one HTML file per page holding the Markdown text; markers in the text steer failures:
RENDER_FAIL -> page error (exit 3). serve: prints the preview address and waits.
"""
import html
import json
import sys
import time
from pathlib import Path

command, *args = sys.argv[1:]
opts = dict(zip(args[::2], args[1::2]))
if command == "serve":
    print(f"Local preview: http://127.0.0.1:4999{opts['--base']}", flush=True)
    time.sleep(600)
    sys.exit(0)
repo, out = Path(opts["--repo"]), Path(opts["--output"])
config = json.loads(Path(opts["--config"]).read_text())
dates = json.loads(Path(opts["--last-updated"]).read_text())
pages = []
for entry in config["pages"]:
    text = (repo / entry["path"]).read_text()
    if "RENDER_CRASH" in text:                           # cli.mjs: an error outside a page (stack, exit 1)
        print(f"Error: Changed input; review and update its hash: {entry['path']}\n"
              "    at readInput (file:///study-site/lib/paths.mjs:18:42)\n    at async main (cli.mjs:30:5)",
              file=sys.stderr)
        sys.exit(1)
    if "RENDER_FAIL" in text:
        print("study-site-page-error " + json.dumps({"file": entry["path"], "message": "Math rendering failed"}),
              file=sys.stderr)
        sys.exit(3)
    route = entry["path"][5:-3].removesuffix("index").rstrip("/")
    url = config["base"] + (route + "/" if route else "")
    target = out / "site" / route / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"<html><body>{html.escape(text)}<time>{dates.get(entry['path'], '')}</time></body></html>")
    pages.append({"path": entry["path"], "route": route, "url": url, "title": entry["path"]})
(out / "payload.json").write_text(json.dumps({"mode": "public", "base": config["base"],
                                              "site": config["site"], "pages": pages}))
if "PDF_STEP" in "".join((repo / e["path"]).read_text() for e in config["pages"]):
    print("PDFs: 1 generated, 2 reused\nPDF time: 3.5 s")   # lib/pdf.mjs and cli.mjs report the step
if "PDF_FAIL" in "".join((repo / e["path"]).read_text() for e in config["pages"]):
    print("PDF time: 1.5 s failed")                      # cli.mjs: the PDF step threw
    sys.exit(1)
