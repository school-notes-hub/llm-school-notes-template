"""A real public build with a released episode (needs the study-site's node_modules and Chromium:
`STUDY_BROWSER=<chrome> uv run --group dev pytest tests/podcast/test_site_build.py`): the browser
check (3 widths, 2 themes) and the public gate pass, the Podcast page is the menu item right
under the home page, the topic page has the player, the PDF only the line."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from school_notes2.log import Log
from school_notes2.site import build as site_build
from school_notes2.state import safefs
from tests.local.conftest import git
from tests.podcast.conftest import needs_ffmpeg, release

pytestmark = [needs_ffmpeg, pytest.mark.skipif(not os.environ.get("STUDY_BROWSER"), reason="STUDY_BROWSER not set")]


def test_public_build_with_an_episode(world, tmp_path):
    repo = world["repo"]
    value = json.loads(safefs.read_text(repo, "publication/public.json"))
    safefs.write_text(repo, "publication/public.json", json.dumps({**value, "site": "https://example.github.io"}))
    safefs.write_text(repo, "wiki/a-projektrol.md", "# A projektről\n\nEgy kis szöveg.\n")
    assert release(world)[0] == 0
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "podcast")
    head = git(repo, "rev-parse", "HEAD").strip()
    renderer = site_build.Renderer(study_site=Path(__file__).parents[3] / "study-site",
                                   browser=Path(os.environ["STUDY_BROWSER"]), pdf_cache=tmp_path / "pdf")
    record = site_build.build(world["local"].git(), head, tmp_path / "task", renderer, changed=None,
                              log=Log(None, console=False))
    site = record.output / "site"
    assert json.loads((record.output / "privacy-report.json").read_text())["errors"] == []
    assert '<audio controls preload="none"' in (site / "proba" / "elso" / "index.html").read_text()
    assert '<audio controls preload="none"' in (site / "podcast" / "index.html").read_text()
    home = (site / "index.html").read_text()
    assert home.index("🏠 Kezdőlap") < home.index("🎧 Podcast") < home.index("🧪 Próba")
    [pdf] = list((site / "pdf").glob("proba-elso-*.pdf"))
    text = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    assert "Képben vagy? · Az első téma röviden" in text
