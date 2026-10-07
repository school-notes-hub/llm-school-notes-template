"""sn 0.3.7 (rules 1.22.5): the fix round of the 0.3.6 review (Astra A1-A8, Opus O3-O11) on the
teaching order. Each test fails on 1bbf485."""

from school_notes2.wiki import generate, markers, teaching_order
from tests.wiki.test_teaching_order import INDEX, lesson_log, topic
from tests.wiki.conftest import write


def base(tmp_path, chapters=("a", "b")):
    repo = tmp_path / "repo"
    write(repo, "wiki/index.md", "# Jegyzetek\n")
    listed = "".join(f"  - {{id: {c}, title: '9. évfolyam: {c.upper()}'}}\n" for c in chapters)
    write(repo, "wiki/proba/index.md", INDEX.replace(
        "  - {id: elso, title: '9. évfolyam: Első fejezet'}\n  - {id: masodik, title: '9. évfolyam: Második fejezet'}\n",
        listed))
    write(repo, "tools/subjects.json", '{"subjects": {"proba": {"name": "Próba"}}}')
    for c in chapters:
        topic(repo, f"t{c}", c, 10)
    return repo


def now(repo):
    return markers.read(generate.subject_index(repo, "proba"), "now")


def most(repo):
    return next(line for line in now(repo).splitlines() if line.startswith("* **Most:**"))


def chapter_order(repo):
    subject = generate.load_subject(repo, "proba")
    found = generate.ordered_lessons(subject)
    return [c.id for c in teaching_order.by_start(generate.subject_chapters(subject, found))]


def test_a_strict_lower_bound_starts_the_next_day_and_an_undated_start_is_marked(tmp_path):
    # A1/O3/O6: „2026-09-10 után” is 09-11 at the earliest: „szeptember közepe”, never „eleje”
    repo = base(tmp_path)
    lesson_log(repo, "2026-09-04-x-jegyzet.md", "proba/x", ["{date: '2026-09-04', title: Kezd, topics: [ta.md]}"])
    lesson_log(repo, "2026-09-25-y-jegyzet.md", "proba/y", [
        "{date_note: '2026-09-10 után, legkésőbb 2026-09-25', title: Új, topics: [tb.md]}"])
    tag = ('<span class="study-when study-when-unsure" title="Nem biztos: a kezdete dátum nélküli óra '
           '(szept. 11. – 25.)">~szept. közepe óta</span>')
    assert most(repo) == f"* **Most:** B {tag}"
    chapters = markers.read(generate.subject_index(repo, "proba"), "chapters")
    assert tag in chapters


def test_a_revisit_never_changes_the_current_chapter(tmp_path):
    # A2: A and B start in one lesson; a later revisit of A moves nothing
    repo = base(tmp_path)
    lesson_log(repo, "2026-09-01-x-jegyzet.md", "proba/x", [
        "{date: '2026-09-01', title: Közös, topics: [ta.md, tb.md]}"])
    assert chapter_order(repo) == ["a", "b"] and most(repo).startswith("* **Most:** B <span")
    lesson_log(repo, "2026-10-01-y-jegyzet.md", "proba/y", ["{date: '2026-10-01', title: Vissza, topics: [ta.md]}"])
    assert chapter_order(repo) == ["a", "b"] and most(repo).startswith("* **Most:** B <span")
    # two chapters started in one lesson: the order taught in that lesson decides
    lesson_log(repo, "2026-09-01-x-jegyzet.md", "proba/x", [
        "{date: '2026-09-01', title: Közös, topics: [tb.md, ta.md]}"])
    assert chapter_order(repo) == ["b", "a"]


def test_a_later_revisit_never_becomes_the_start_of_an_evidenced_earlier_chapter(tmp_path):
    # A4: A first appears undated (no later than 09-05), B starts 09-10, A is revisited 10-01
    repo = base(tmp_path)
    lesson_log(repo, "2026-09-05-x-jegyzet.md", "proba/x", [
        "{date_note: 'legkésőbb 2026-09-05', title: Korai, topics: [ta.md]}"])
    lesson_log(repo, "2026-09-10-y-jegyzet.md", "proba/y", ["{date: '2026-09-10', title: B kezd, topics: [tb.md]}"])
    lesson_log(repo, "2026-10-01-z-jegyzet.md", "proba/z", ["{date: '2026-10-01', title: Vissza, topics: [ta.md]}"])
    assert chapter_order(repo) == ["a", "b"]
    assert most(repo) == '* **Most:** B <span class="study-when">szept. 10. óta</span>'


def test_chapter_ties_never_use_file_names(tmp_path):
    # A5/O7: two chapters starting the same day in different notebooks: the `chapters` list decides
    repo = base(tmp_path)
    lesson_log(repo, "z-jegyzet.md", "proba/z", ["{date: '2026-09-01', title: A1, topics: [ta.md]}"])
    lesson_log(repo, "a-jegyzet.md", "proba/a", ["{date: '2026-09-01', title: B1, topics: [tb.md]}",
                                                 "{date: '2026-09-30', title: B2, topics: [tb.md]}"])
    assert chapter_order(repo) == ["a", "b"]


def test_inside_one_lesson_log_the_notebook_order_decides(tmp_path):
    # A6/O4: an undated lesson before a dated one of the same day keeps its place
    repo = base(tmp_path)
    lesson_log(repo, "2026-09-10-x-jegyzet.md", "proba/x", [
        "{date_note: '2026-09-10-től, legkésőbb 2026-09-10', title: Előbb, topics: [ta.md]}",
        "{date: '2026-09-10', title: Utána, topics: [ta.md]}"])
    lesson_log(repo, "2026-09-03-y-jegyzet.md", "proba/y", ["{date: '2026-09-03', title: Kezd, topics: [ta.md]}"])
    titles = [lesson["title"] for _, lesson in generate.lessons(generate.load_subject(repo, "proba"))]
    assert titles == ["Utána", "Előbb", "Kezd"]                    # newest first


def test_the_uncertain_mark_comes_only_from_evidence():
    note = {"date_note": "2026-09-01 után, legkésőbb 2026-09-20", "title": "x"}
    def page(name, folder, first, lesson=note):
        return (name, {"source_file": f"{folder}/", "content_sha256": {first: "x"}, "lessons": [dict(lesson)]})
    # A7: the same range at the same page position of one folder: no evidence, both ↕
    same = teaching_order.ordered([page("a-jegyzet.md", "f", "p0001.jpg"), page("b-jegyzet.md", "f", "p0001.jpg")])
    assert [lesson.uncertain for lesson in same] == [True, True]
    # successive pages of one notebook with overlapping ranges: known order, no ↕
    other = {"date_note": "2026-09-05 után, legkésőbb 2026-09-25", "title": "y"}
    pages_ = teaching_order.ordered([page("a-jegyzet.md", "f", "p0001.jpg"), page("b-jegyzet.md", "f", "p0002.jpg", other)])
    assert [lesson.uncertain for lesson in pages_] == [False, False]


def test_every_provable_chapter_inversion_is_reported_with_its_place(tmp_path):
    # A8/O5: A 09-20, B 09-01..09-30 (undated), C 09-10: C certainly before A although not adjacent
    repo = base(tmp_path, ("a", "b", "c"))
    lesson_log(repo, "a-jegyzet.md", "proba/a", ["{date: '2026-09-20', title: A, topics: [ta.md]}"])
    lesson_log(repo, "b-jegyzet.md", "proba/b", [
        "{date_note: '2026-09-01-től, legkésőbb 2026-09-30', title: B, topics: [tb.md]}"])
    lesson_log(repo, "c-jegyzet.md", "proba/c", ["{date: '2026-09-10', title: C, topics: [tc.md]}"])
    [found] = teaching_order.order_warnings(repo, ["wiki/proba/index.md"])
    assert found["message"].startswith("`chapters`: 'c' (9. évfolyam: C) is listed after 'a', but the class started it first")
    assert "it belongs right after 'b' (9. évfolyam: B)" in found["message"]


def test_the_upper_bound_warning_compares_only_the_lessons_own_folder(tmp_path):
    # O10: a dated lesson whose page only also lists the folder is no evidence against the bound
    repo = base(tmp_path)
    lesson_log(repo, "x-jegyzet.md", "proba/potlas", [
        "{date_note: '2026-09-01 után, legkésőbb 2026-10-04', title: Pótolt, topics: [ta.md]}"])
    write(repo, "wiki/proba/y-jegyzet.md", (
        "---\ntype: lesson-notes\ntitle: y\ndescription: d\nsource_file: [proba/2026-10-05/, proba/potlas/]\n"
        "content_sha256: {01.jpg: x}\nlessons:\n  - {date: '2026-10-05', title: Datált, topics: [tb.md]}\n---\n"))
    assert teaching_order.order_warnings(repo, ["wiki/proba/x-jegyzet.md"]) == []


def test_the_now_block_stands_before_the_catch_up_list_on_every_index(tmp_path):
    # O9: one fixed order; an index with the 📍 block after the catch-up list converges
    repo = base(tmp_path)
    lesson_log(repo, "x-jegyzet.md", "proba/x", ["{date: '2026-09-01', title: Kezd, topics: [ta.md]}"])
    from school_notes2.wiki import frontmatter
    path = repo / "wiki/proba/x-jegyzet.md"
    path.write_text(frontmatter.set_keys(path.read_text(), {"catch_up": "open"}))
    text = generate.subject_index(repo, "proba")
    assert text.index("# 📍 Itt tartunk") < text.index("# 📝 Pótolandó") < text.index("# 📘")
    # 0.3.6 put a catch-up list that appeared later above the 📍 block; such a page converges
    old = markers.remove(text, {"now"})
    end = old.index("<!-- /school-notes:generated -->", old.index("# 📝 Pótolandó")) + len("<!-- /school-notes:generated -->\n")
    write(repo, "wiki/proba/index.md", old[:end] + "\n" + markers.wrap("now", "") + old[end:])
    once = generate.subject_index(repo, "proba")
    assert once.index("# 📍 Itt tartunk") < once.index("# 📝 Pótolandó") < once.index("# 📘")
    write(repo, "wiki/proba/index.md", once)
    assert generate.subject_index(repo, "proba") == once
