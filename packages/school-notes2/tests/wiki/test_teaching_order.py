"""sn 0.3.6 (rules 1.22.4): the teaching order on the subject index – undated lessons by the
lower bound of their range, the ↕ mark where the order is not known, the chapters' start and
taught span, the 📍 Itt tartunk block, and the order warnings of `sn check`. Each test fails on
4c1e22c."""

from school_notes2.wiki import check, generate, markers, teaching_order
from tests.wiki.conftest import page, write

INDEX = """---
description: A próba tantárgy témakörei.
chapters:
  - {id: elso, title: '9. évfolyam: Első fejezet'}
  - {id: masodik, title: '9. évfolyam: Második fejezet'}
---

# Próba

![Próba banner](../assets/banner.webp)

[⬅️ Vissza a kezdőlapra](../index.md)

<br />

""" + markers.wrap("chapters", "") + "\n<br />\n\n# 🗓️ Órák\n\n" + markers.wrap("lessons", "")


def lesson_log(repo, name, folder, lessons):
    rows = "\n".join(f"  - {row}" for row in lessons)
    write(repo, f"wiki/proba/{name}", page(
        f"type: lesson-notes\ntitle: {name}\ndescription: d\nsource_file: {folder}/\n"
        f"content_sha256: {{01.jpg: x}}\nlessons:\n{rows}"))


def topic(repo, name, chapter, order):
    write(repo, f"wiki/proba/{name}.md", page(
        f"type: topic\ntitle: {name.capitalize()}\ndescription: d\nchapter: {chapter}\norder: {order}"))


def subject_repo(tmp_path):
    repo = tmp_path / "repo"
    write(repo, "wiki/index.md", "# Jegyzetek\n")
    write(repo, "wiki/proba/index.md", INDEX)
    write(repo, "tools/subjects.json", '{"subjects": {"proba": {"name": "Próba"}}}')
    topic(repo, "alap", "elso", 10)
    topic(repo, "tovabb", "elso", 20)
    topic(repo, "uj", "masodik", 10)
    lesson_log(repo, "2026-09-10-a-jegyzet.md", "proba/2026-09-10", [
        "{date: '2026-09-03', title: Kezdés, topics: [alap.md]}",
        "{date: '2026-09-10', title: Folytatás, topics: [tovabb.md]}"])
    # a catch-up lesson whose range starts early: it must not float above the dated 09-22 lesson
    lesson_log(repo, "2026-10-04-b-jegyzet.md", "proba/2026-10-04-potlas", [
        "{date_note: '2026-09-10 után, legkésőbb 2026-10-04', title: Pótolt óra, topics: [tovabb.md]}"])
    lesson_log(repo, "2026-09-22-c-jegyzet.md", "proba/2026-09-22", [
        "{date: '2026-09-22', title: Új fejezet, topics: [uj.md]}"])
    return repo


def titles(repo):
    return [lesson["title"] for _, lesson in generate.lessons(generate.load_subject(repo, "proba"))]


def test_bounds_of_every_date_note_form():
    assert teaching_order.bounds({"date": "2026-09-22"}) == ("2026-09-22", "2026-09-22", True)
    # strictly after X: the earliest day is X+1 (0.3.7, Astra A1)
    assert teaching_order.bounds({"date_note": "2026-09-22 után, legkésőbb 2026-10-04"}) == \
        ("2026-09-23", "2026-10-04", False)
    assert teaching_order.bounds({"date_note": "2026-09-14-től, legkésőbb 2026-10-03"}) == \
        ("2026-09-14", "2026-10-03", False)
    assert teaching_order.bounds({"date_note": "2026-09-1? (levágva: 2026-09-10 és 2026-09-19 között)"}) == \
        ("2026-09-10", "2026-09-19", False)
    assert teaching_order.bounds({"date_note": "legkésőbb 2026-09-25"}) == ("", "2026-09-25", False)
    assert teaching_order.bounds({"date_note": "2026-09-28 vagy 2026-09-29"})[:2] == ("2026-09-28", "2026-09-29")


def test_an_undated_lesson_sorts_by_its_lower_bound(tmp_path):
    repo = subject_repo(tmp_path)
    assert titles(repo) == ["Új fejezet", "Pótolt óra", "Folytatás", "Kezdés"]
    table = markers.read(generate.subject_index(repo, "proba"), "lessons")
    assert "| ? (2026-09-10 után, legkésőbb 2026-10-04) ↕ | Pótolt óra |" in table
    assert "A ↕ jel: dátum nélküli óra, ezért a helye a sorban (vagy egy fejezet kezdete) nem biztos" in table


def test_inside_one_lesson_log_the_notebook_order_tightens_the_range(tmp_path):
    repo = subject_repo(tmp_path)
    lesson_log(repo, "2026-09-28-d-jegyzet.md", "proba/2026-09-28", [
        "{date: '2026-09-28', title: Kréta, topics: [uj.md]}",
        "{date_note: '2026-09-27 után, legkésőbb 2026-10-06', title: Mükéné, topics: [uj.md]}"])
    lesson_log(repo, "2026-09-29-e-jegyzet.md", "proba/2026-09-29", [
        "{date: '2026-09-29', title: Polisz, topics: [uj.md]}"])
    assert titles(repo)[:3] == ["Polisz", "Mükéné", "Kréta"]


def test_one_folder_keeps_its_notebook_order_and_a_lesson_without_lower_bound_marks_only_itself():
    pages = [(f"2026-10-03-{n}-jegyzet.md", {"source_file": "t/2026-10-03/", "content_sha256": {f"p000{i}.jpg": "x"},
                                            "lessons": [{"date_note": "2026-09-14 után, legkésőbb 2026-10-03",
                                                         "title": n}]})
             for i, n in ((5, "szechenyi"), (3, "rendi"), (7, "vita"))]
    pages.append(("2026-10-03-forras-jegyzet.md", {"source_file": "t/2026-10-02/", "content_sha256": {"p0001.jpg": "x"},
                                                   "lessons": [{"date_note": "legkésőbb 2026-10-03", "title": "forras"}]}))
    found = teaching_order.ordered(pages)
    assert [lesson.data["title"] for lesson in found] == ["forras", "rendi", "szechenyi", "vita"]
    assert [lesson.uncertain for lesson in found] == [True, False, False, False]
    # the first page of the same folder is certainly the first lesson (0.3.7): no ↕ at all
    pages[-1][1]["source_file"] = "t/2026-10-03/"
    assert not any(lesson.uncertain for lesson in teaching_order.ordered(pages))


def test_the_now_block_names_the_chapter_the_latest_lesson_and_the_ones_before(tmp_path):
    repo = subject_repo(tmp_path)
    text = generate.subject_index(repo, "proba")
    assert markers.read(text, "now") == (
        "# 📍 Itt tartunk\n\n"
        "* **Most:** Második fejezet (szeptember 22. óta, még tart)\n"
        "* **Legutóbb:** [Új fejezet](2026-09-22-c-jegyzet.md) – 2026-09-22 · [Uj](uj.md)\n"
        "* **Előtte:** Első fejezet (szeptember eleje – október eleje ↕)\n\n"
        "Eddig ebben a sorrendben vettük, a legújabb elöl:\n\n"
        "* dátum nélkül, 2026-09-10 után, legkésőbb 2026-10-04 ↕ – [Pótolt óra](2026-10-04-b-jegyzet.md)\n"
        "* 2026-09-10 – [Folytatás](2026-09-10-a-jegyzet.md)\n"
        "* 2026-09-03 – [Kezdés](2026-09-10-a-jegyzet.md)\n\n"
        "A ↕ jel: dátum nélküli óra, ezért a helye a sorban (vagy egy fejezet kezdete) nem biztos, mert az "
        "időszaka átfed más órákéval.\n")
    # its fixed place: after the back link, above the chapter lists; a refresh changes nothing
    assert text.index("../index.md)") < text.index("# 📍 Itt tartunk") < text.index("# 📘")
    write(repo, "wiki/proba/index.md", text)
    assert generate.subject_index(repo, "proba") == text


def test_each_chapter_shows_when_it_was_taught(tmp_path):
    repo = subject_repo(tmp_path)
    chapters = markers.read(generate.subject_index(repo, "proba"), "chapters")
    # the undated catch-up lesson may come after the 09-22 start: the end is not cut as if certain
    assert "# 📘 9. évfolyam: Első fejezet\n\n🗓️ szeptember eleje – október eleje ↕\n\n" in chapters
    assert "# 📘 9. évfolyam: Második fejezet\n\n🗓️ szeptember 22. óta, még tart\n\n" in chapters
    two = teaching_order.Chapter("x", "X", 0, [
        teaching_order.Lesson("a.md", 0, {}, "2026-09-03", "2026-09-03", True, "f", ()),
        teaching_order.Lesson("a.md", 1, {}, "2026-09-10", "2026-09-10", True, "f", ())])
    later = teaching_order.Lesson("b.md", 0, {}, "2026-10-01", "2026-10-01", True, "f", ())
    assert teaching_order.span(two, later) == "szeptember 3. – szeptember 10."


def test_a_revisit_is_the_latest_lesson_but_moves_no_chapter(tmp_path):
    repo = subject_repo(tmp_path)
    before = markers.read(generate.subject_index(repo, "proba"), "chapters")
    lesson_log(repo, "2026-10-06-f-jegyzet.md", "proba/2026-10-06", [
        "{date: '2026-10-06', title: Visszatérés, topics: [alap.md]}"])
    text = generate.subject_index(repo, "proba")
    now = markers.read(text, "now")
    assert "* **Legutóbb:** [Visszatérés](2026-10-06-f-jegyzet.md) – 2026-10-06 · [Alap](alap.md)\n" in now
    assert "* **Most:** Második fejezet (" in now                       # the chapter started last
    assert markers.read(text, "chapters") == before                   # order and spans unchanged
    assert not [w for w in check.order_warnings(repo, ["wiki/proba/index.md"])]


def test_sn_check_warns_on_a_chapters_list_against_the_teaching_order(tmp_path):
    repo = subject_repo(tmp_path)
    index = "wiki/proba/index.md"
    assert check.order_warnings(repo, [index]) == []
    text = (repo / index).read_text().replace(
        "  - {id: elso, title: '9. évfolyam: Első fejezet'}\n  - {id: masodik, title: '9. évfolyam: Második fejezet'}\n",
        "  - {id: masodik, title: '9. évfolyam: Második fejezet'}\n  - {id: elso, title: '9. évfolyam: Első fejezet'}\n")
    write(repo, index, text)
    [found] = check.order_warnings(repo, [index])
    assert found["severity"] == "warning" and found["file"] == index
    assert found["message"].startswith("`chapters`: 'elso' (9. évfolyam: Első fejezet) is listed after 'masodik'")
    # undecidable (overlapping undated starts): no warning
    for name in ("2026-09-10-a-jegyzet.md", "2026-09-22-c-jegyzet.md"):
        (repo / "wiki/proba" / name).unlink()
    lesson_log(repo, "2026-09-25-g-jegyzet.md", "proba/2026-09-25", [
        "{date_note: '2026-09-01 után, legkésőbb 2026-09-25', title: A, topics: [alap.md]}"])
    lesson_log(repo, "2026-09-25-h-jegyzet.md", "proba/2026-09-26", [
        "{date_note: '2026-09-01 után, legkésőbb 2026-09-25', title: B, topics: [uj.md]}"])
    assert check.order_warnings(repo, [index]) == []


def test_sn_check_warns_on_an_unnamed_topic_and_on_weak_date_notes(tmp_path):
    repo = subject_repo(tmp_path)
    topic(repo, "senki", "elso", 30)
    lesson_log(repo, "2026-10-05-k-jegyzet.md", "proba/2026-10-04-potlas", [
        "{date: '2026-10-05', title: Datált pótlás, topics: [uj.md]}"])
    lesson_log(repo, "2026-09-25-m-jegyzet.md", "proba/2026-09-25", [
        "{date_note: 'legkésőbb 2026-09-25', title: Feladatlap, topics: [alap.md]}",
        "{date_note: '2026-09-28 vagy 2026-09-29', title: Részben olvasható, topics: [alap.md]}"])
    paths = [f"wiki/proba/{p.name}" for p in (repo / "wiki/proba").glob("*.md")]
    found = {(w["file"].rsplit("/", 1)[1], w["message"][:60]) for w in check.order_warnings(repo, paths)}
    assert found == {
        ("senki.md", "no lesson's `topics` names this topic page, so it has no pla"),
        ("2026-09-25-m-jegyzet.md", "lessons[0] (Feladatlap): `date_note` has no lower bound; wri"),
        ("2026-10-04-b-jegyzet.md", "lessons[0] (Pótolt óra): the `date_note` upper bound 2026-10"),
    }
    # the page-check items carry them as warnings, never as errors
    items = check.check_files(repo, ["wiki/proba/senki.md"], fix=False)
    assert [i["severity"] for i in items if "topics" in i["message"]] == ["warning"]
