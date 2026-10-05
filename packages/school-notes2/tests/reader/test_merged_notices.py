"""The 2.2.2 placement rules also cover nightly and license-waiting figures."""


from school_notes2.figures import requests
from school_notes2.reader import notices, verdicts
from school_notes2.state import safefs
from .test_notice_regressions import BANNER, META, accept, refresh_twice


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
