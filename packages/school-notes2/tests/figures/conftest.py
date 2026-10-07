import io

import pytest
from PIL import Image

from school_notes2.state import safefs
from tests.conftest import record_render


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return root


@pytest.fixture
def make_figure(repo):
    def make(fid="forces", page="wiki/physics/forces.md", kind="figure", **changes):
        if not (repo / page).exists():
            safefs.write_text(repo, page, "---\ntitle: Forces\ndescription: Two forces\ntype: topic\n---\n"
                              "# Forces\n\nTwo forces act.\n\n")
        safefs.write_text(repo, page, safefs.read_text(repo, page) + f"<!-- figure: {fid} -->\n\n")
        asset = f"wiki/assets/physics/{fid}.png"
        image = Image.new("RGB", (1000, 500), "white")
        data = io.BytesIO()
        image.save(data, format="PNG")
        safefs.write_bytes(repo, asset, data.getvalue())
        brief = {"id": fid, "page": page, "anchor": "Forces", "kind": kind,
                 "purpose": "Understand the forces", "must_show": ["Two forces"],
                 "avoid_misreading": "Same body", "taught_conventions": [],
                 "text_complete_without_figure": True, **changes}
        candidate = {"state": "candidate", "asset": asset, "alt": "Two opposing arrows",
                     "caption": "The arrows represent forces.", "form": "diagram", "tool": "test",
                     "elements": [{"element": "arrow", "meaning": "force"}],
                     "visible_text": ["F"], "attempt": 1}
        safefs.write_json(repo, f".school-notes/figures/{fid}.json", brief)
        safefs.write_json(repo, f".school-notes/figures/{fid}/figure.json", candidate)
        record_render(repo, asset)
        return brief, candidate
    return make


def add_pending(repo, brief, run_ids=("run-1",), defects=()):
    """A queued figure in docs/figure-pending.json, as the VM fix runs left them."""
    from school_notes2.figures import pending
    entries = [e for e in safefs.read_json(repo, pending.PATH, []) if e["commission"]["id"] != brief["id"]]
    entries.append({"commission": brief, "status": "pending", "runs": len(run_ids), "run_ids": sorted(run_ids),
                    "defects": list(defects), "owner_required": len(run_ids) >= 3})
    safefs.write_json(repo, pending.PATH, sorted(entries, key=lambda e: e["commission"]["id"]))
    return entries[-1]


def add_request(repo, request, original_sha256=None):
    """A figure request in docs/figure-requests.json, bound to its source bytes."""
    from school_notes2.figures import requests
    from school_notes2.wiki.pages import sha256
    records = [r for r in safefs.read_json(repo, requests.PATH, []) if r["id"] != request["id"]]
    records.append({**request, "content_sha256": sha256(repo, request["source"]), "original_sha256": original_sha256})
    records.sort(key=lambda r: (r["source"], r["page"], r["id"]))
    safefs.write_json(repo, requests.PATH, records)
    return records
