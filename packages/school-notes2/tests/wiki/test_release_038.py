"""sn 0.3.8 (rules 1.22.6): lesson dates as quiet meta items in short Hungarian form; an
uncertain date only `~` with its range as the hover tooltip; no ISO date and none of the long
range words in visible text. Each test fails on 95f96a6."""

import re

from school_notes2.wiki import generate, hu_dates, markers
from tests.wiki.test_teaching_order import subject_repo


def test_short_hungarian_dates():
    assert hu_dates.short("2026-10-04", 2026) == "okt. 4."
    assert hu_dates.short("2026-09-22", 2026) == "szept. 22."
    assert hu_dates.short("2025-10-04", 2026) == "2025. okt. 4."          # outside the school year
    assert hu_dates.short("2027-06-15", 2026) == "jún. 15."
    assert hu_dates.full("2026-10-04") == "2026. 10. 04."
    assert hu_dates.part("2026-09-23", 2026) == "szept. vége"
    assert hu_dates.between("szept. 10.", "szept. 19.") == "szept. 10–19."
    assert hu_dates.between("szept. eleje", "okt. eleje") == "szept. eleje – okt. eleje"
    assert hu_dates.range_text("2026-09-23", "2026-10-04", 2026) == "szept. 23. – okt. 4."
    assert hu_dates.range_text("", "2026-10-04", 2026) == "legkésőbb okt. 4."
    assert hu_dates.school_year(["2026-09-03", "2026-10-04"]) == 2026
    assert hu_dates.school_year(["2027-03-01"]) == 2026
    assert hu_dates.meta("okt. 4.") == '<span class="study-when">okt. 4.</span>'
    assert hu_dates.meta("szept. vége", "Dátum nélküli óra: a < b", unsure=True) == (
        '<span class="study-when study-when-unsure" title="Dátum nélküli óra: a &lt; b">~szept. vége</span>')


def visible(text):
    text = re.sub(r"\]\([^)]*\)", "]", text)     # link targets are not shown
    return re.sub(r"<[^>]+>", "", text)          # tags and their attributes (the tooltips) go


def test_the_index_shows_short_dates_and_hides_every_range(tmp_path):
    repo = subject_repo(tmp_path)
    text = generate.subject_index(repo, "proba")
    for name in ("now", "chapters", "lessons"):
        shown = visible(markers.read(text, name))
        assert not re.search(r"\d{4}-\d{2}-\d{2}", shown), shown
        for words in ("dátum nélkül", "után", "legkésőbb", "még tart", "↕"):
            assert words not in shown, (name, words, shown)
    now = markers.read(text, "now")
    assert '[Pótolt óra](2026-10-04-b-jegyzet.md) <span class="study-when study-when-unsure" ' \
           'title="Dátum nélküli óra: szept. 11. – okt. 4.; a helye a sorban nem biztos">~szept. közepe</span>' in now
    assert '<span class="study-when">szept. 22. óta</span>' in now
