"""The 2.2.2 placement rules also cover nightly and license-waiting figures."""

import pytest

from school_notes2.figures import requests
from school_notes2.reader import notices, units, verdicts
from school_notes2.review import figure_waiting
from school_notes2.state import safefs
from school_notes2.wiki import markers
from .test_notice_regressions import BANNER, META, accept, legacy_items, refresh_twice


@pytest.mark.parametrize("placement", ["section", "generated", "header"])
def test_nightly_waiting_never_creates_a_notice(setup, placement):
    ctx, _, page = setup
    repo = ctx.notes_path
    section = "# Rész\n\n"
    text = META + BANNER + "\n" + (markers.wrap("notes", section) if placement == "generated" else section)
    text += "\nMondat.\n"
    safefs.write_text(repo, page, text)
    key = units.page_key(repo, page)
    spec = {"id": "night-a", "page": page, "asset": "wiki/assets/banner.png", "kind": "banner",
            "anchor": "" if placement == "header" else "Rész"}
    # Missing image bytes leave a real nightly record active without calling a model.
    safefs.write_json(repo, figure_waiting.PATH, [{"spec": spec}])
    if placement != "header":
        accept(repo, page)
        legacy_items(repo, page, ["Mondat."])
    result = refresh_twice(repo, page)
    assert "⏳" not in result
    assert units.page_key(repo, page) == key
    if placement == "generated":
        assert markers.read(result, "notes") == section
    safefs.write_json(repo, figure_waiting.PATH, [])
    result = refresh_twice(repo, page)
    assert notices.FIGURE not in result
    assert notices.PAGE not in result
    assert notices.SECTION not in result


def test_license_notice_is_idempotent_and_clears_without_invalidating_verdict(setup):
    ctx, _, page = setup
    repo = ctx.notes_path
    text = META + BANNER + "\n# Rész\n\n<!-- figure-request: licensed -->\n\nMondat.\n"
    safefs.write_text(repo, page, text)
    request = {"id": "licensed", "page": page, "source": "sources/material/image.png",
               "crop": "0,0,100,100", "purpose": "Tanító ábra", "origin": "unknown",
               "content_sha256": "a" * 64, "original_sha256": None}
    safefs.write_json(repo, requests.PATH, [request])
    accept(repo, page)
    result = refresh_twice(repo, page)
    assert result.count(notices.FIGURE) == 1
    assert result.index("<!-- figure-request: licensed -->") < result.index(notices.FIGURE)
    assert verdicts.valid(repo, page) is not None
    safefs.write_json(repo, requests.PATH, [])
    assert refresh_twice(repo, page) == text
    assert verdicts.valid(repo, page) is not None
