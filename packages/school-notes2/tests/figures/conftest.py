import io
from pathlib import Path

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
