"""Resolve section IDs with the installed site's Markdown renderer, without a browser."""

import json
import subprocess
from pathlib import Path

from ..state import safefs

RENDERER = Path(__file__).resolve().parents[4] / "study-site" / "lib" / "markdown.mjs"
SCRIPT = """
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
const {renderMarkdown} = await import(pathToFileURL(process.argv[1]).href);
const sources = JSON.parse(fs.readFileSync(0, 'utf8'));
const result = {};
for (const [page, source] of Object.entries(sources)) {
  const {html} = await renderMarkdown(source, {resolveUrl: async url => url,
                                             mermaid: async () => ''});
  result[page] = [...new Set([...html.matchAll(/\\bid="([^"]+)"/g)].map(m => m[1]))].sort();
}
process.stdout.write(JSON.stringify(result));
"""


def collect(repo, paths):
    sources = {p: safefs.read_text(repo, p) for p in sorted(set(paths))}
    if not sources:
        return {}
    result = subprocess.run(["node", "--input-type=module", "-e", SCRIPT, str(RENDERER)],
                            input=json.dumps(sources), capture_output=True, text=True,
                            timeout=30, check=True)
    return {p: set(ids) for p, ids in json.loads(result.stdout).items()}
