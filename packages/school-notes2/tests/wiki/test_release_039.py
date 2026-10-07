"""sn 0.3.9 (rules 1.22.7): `after` orders lessons the dates cannot; a folder's page order is
evidence only for one notebook; a partly legible date is a "Bizonytalan dátum"; Hungarian range
form; the approximate day; the legend texts. Each test fails on 3c0b811."""

import json

from school_notes2.wiki import generate, hu_dates, machine, markers, teaching_order
from tests.wiki.test_teaching_order import INDEX, lesson_log, topic
from tests.wiki.conftest import write


def base(tmp_path):
    repo = tmp_path / "repo"
    write(repo, "wiki/index.md", "# Jegyzetek\n")
    write(repo, "wiki/proba/index.md", INDEX)
    write(repo, "tools/subjects.json", '{"subjects": {"proba": {"name": "Próba"}}}')
    topic(repo, "alap", "elso", 10)
    topic(repo, "uj", "masodik", 10)
    return repo


def titles(repo):
    return [lesson["title"] for _, lesson in generate.lessons(generate.load_subject(repo, "proba"))]


def test_after_orders_lessons_the_dates_cannot(tmp_path):
    repo = base(tmp_path)
    note = "date_note: '2026-09-04 után, legkésőbb 2026-09-10'"
    lesson_log(repo, "a-jegyzet.md", "proba/a", [f"{{{note}, title: 4. óra, topics: [alap.md], after: b-jegyzet.md}}"])
    lesson_log(repo, "b-jegyzet.md", "proba/b", [f"{{{note}, title: Gyakorlás, topics: [alap.md]}}",
                                                f"{{{note}, title: Gráfok, topics: [alap.md]}}"])
    assert titles(repo) == ["4. óra", "Gráfok", "Gyakorlás"]                  # newest first
    found = generate.ordered_lessons(generate.load_subject(repo, "proba"))
    assert not any(lesson.uncertain for lesson in found)                     # all in a known order
    lesson_log(repo, "a-jegyzet.md", "proba/a", [f"{{{note}, title: 4. óra, topics: [alap.md], after: b-jegyzet.md#1}}"])
    assert titles(repo).index("4. óra") < titles(repo).index("Gyakorlás")
    lesson_log(repo, "a-jegyzet.md", "proba/a", [f"{{{note}, title: 4. óra, topics: [alap.md], after: nincs-jegyzet.md}}"])
    [error] = [w for w in teaching_order.order_warnings(repo, ["wiki/proba/a-jegyzet.md"]) if w["severity"] == "error"]
    assert "`after: nincs-jegyzet.md` names no lesson" in error["message"]
    lesson_log(repo, "a-jegyzet.md", "proba/a", [f"{{{note}, title: 4. óra, topics: [alap.md], after: b-jegyzet.md}}"])
    lesson_log(repo, "b-jegyzet.md", "proba/b", [f"{{{note}, title: Gyakorlás, topics: [alap.md], after: a-jegyzet.md}}"])
    assert any("closes a circle" in w["message"]
               for w in teaching_order.order_warnings(repo, ["wiki/proba/a-jegyzet.md", "wiki/proba/b-jegyzet.md"]))


def test_a_folder_of_separate_photos_is_no_order_evidence(tmp_path):
    repo = base(tmp_path)
    # the magyar catch-up case: one folder, photo 1 holds an undated lesson, photo 6 a dated 10-05 one
    for name, first, row in (("h-jegyzet.md", "1.jpg", "{date_note: '2026-09-24 után, legkésőbb 2026-10-07', title: Hangulatjelek, topics: [uj.md]}"),
                             ("l-jegyzet.md", "6.jpg", "{date: '2026-10-05', title: Lehetőségek, topics: [uj.md]}")):
        write(repo, f"wiki/proba/{name}", f"---\ntype: lesson-notes\ntitle: x\ndescription: d\nsource_file: proba/potlas/\n"
                                          f"content_sha256: {{{first}: x}}\nlessons:\n  - {row}\n---\n")
    pages = [{"file": f"{n}.jpg", "page": None, "path": f"sources/proba/potlas/{n}.jpg", "content_sha256": "x",
              "original_sha256": "y", "drive_id": "", "duplicate_of": None} for n in (1, 6)]
    write(repo, "sources/proba/potlas/sn-fetch.json", json.dumps({"package": {}, "pages": pages, "written": {}}))
    subject = generate.load_subject(repo, "proba")
    assert subject.notebooks == set()
    hangulat = next(x for x in generate.ordered_lessons(subject) if x.data["title"] == "Hangulatjelek")
    assert hangulat.hi == "2026-10-07" and hangulat.uncertain                 # not cut at 10-05
    # one PDF split into pages is one notebook: its order is evidence
    pages = [{**p, "file": "fuzet.pdf", "page": i} for i, p in enumerate(pages, start=1)]
    write(repo, "sources/proba/potlas/sn-fetch.json", json.dumps({"package": {}, "pages": pages, "written": {}}))
    assert generate.load_subject(repo, "proba").notebooks == {"proba/potlas"}
    write(repo, "sources/proba/regi/p0001.jpg", "x")
    write(repo, "sources/proba/regi/p0002.jpg", "x")
    write(repo, "sources/proba/fotok/01.jpg", "x")
    assert generate.notebook_folders(repo, {"proba/regi", "proba/fotok"}) == {"proba/regi"}


def lesson(data, lo, hi, dated=False):
    return teaching_order.Lesson("x.md", 0, data, lo, hi, dated, "", ())


def test_the_date_item_forms():
    partly = lesson({"date_note": "2026-09-1? (levágva: 2026-09-10 és 2026-09-19 között)"}, "2026-09-10", "2026-09-19")
    assert generate.when(partly, 2026) == (
        '<span class="study-when study-when-unsure" title="Bizonytalan dátum: szept. 10–19.">~szept.</span>')
    assert 'title="Bizonytalan dátum: szept. 28–29."' in generate.when(
        lesson({"date_note": "2026-09-28 vagy 2026-09-29"}, "2026-09-28", "2026-09-29"), 2026)
    undated = lesson({"date_note": "2026-09-22 után, legkésőbb 2026-10-04"}, "2026-09-23", "2026-10-04")
    assert generate.when(undated, 2026) == (
        '<span class="study-when study-when-unsure" title="Dátum nélküli óra: szept. 23. – okt. 4.">~szept. vége</span>')
    nothing = lesson({}, "", teaching_order.NEVER)
    assert generate.when(nothing, 2026) == '<span class="study-when study-when-unsure" title="Dátum nélküli óra: ismeretlen">?</span>'
    noted = lesson({"date": "2026-09-04", "date_note": "a piramis 2026-09-04 és 2026-09-09 között"}, "2026-09-04", "2026-09-04", True)
    assert generate.when(noted, 2026) == '<span class="study-when" title="a piramis szept. 4. és szept. 9. között">szept. 4.</span>'
    old = lesson({"date": "2025-10-04"}, "2025-10-04", "2025-10-04", True)
    assert generate.when(old, 2026) == '<span class="study-when">2025. okt. 4.</span>'


def test_hungarian_range_and_approximate_day():
    assert hu_dates.between("szept. 10.", "szept. 19.") == "szept. 10–19."
    assert hu_dates.between("szept. eleje", "szept. közepe") == "szept. eleje–közepe"
    assert hu_dates.between("szept. 23.", "okt. 4.") == "szept. 23. – okt. 4."
    assert hu_dates.approximate("2026-09-21", "2026-09-29", 2026) == "szept. vége"        # one part
    assert hu_dates.approximate("2026-09-11", "2026-09-25", 2026) == "szept."              # one month
    assert hu_dates.approximate("2026-09-23", "2026-10-04", 2026) == "szept. vége"         # lower bound
    assert hu_dates.approximate("", "2026-09-25", 2026) == "szept. vége"


def test_the_catch_up_list_and_the_legends_use_the_quiet_form(tmp_path):
    from school_notes2.wiki import frontmatter
    repo = base(tmp_path)
    lesson_log(repo, "a-jegyzet.md", "proba/a", ["{date_note: '2026-09-01 után, legkésőbb 2026-09-09', title: A, topics: [alap.md]}"])
    path = repo / "wiki/proba/a-jegyzet.md"
    path.write_text(frontmatter.set_keys(path.read_text(), {"catch_up": "open"}))
    block = markers.read(generate.subject_index(repo, "proba"), "catch-up")
    assert ('Dátum: <span class="study-when study-when-unsure" title="Dátum nélküli óra: szept. 2–9.">~szept. eleje</span>.'
            in block)
    assert "?" not in machine.LESSONS_LEGEND and "`~`" in machine.LESSONS_LEGEND
