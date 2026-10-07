from school_notes2.wiki import generate, markers


def test_subject_blocks(repo):
    text = generate.subject_index(repo, "proba")
    chapters = markers.read(text, "chapters")
    assert chapters == (
        "# 📘 9. évfolyam: Alapok\n\n<span class=\"study-when study-when-unsure\" title=\"Nem biztos: a vége dátum nélküli óra (szept. 3–10.)\">~szept. eleje</span>\n\n"
        "* ⚡ [Összefoglaló: Alapok](osszefoglalo-alapok.md) - Rövid.\n"
        "* [Első](elso.md) - Az első téma.\n"
        "\n<br />\n\n"
        "# 📘 9. évfolyam: Haladó\n\n<span class=\"study-when study-when-unsure\" title=\"Nem biztos: a kezdete dátum nélküli óra (szept. 3–10.)\">~szept. eleje óta</span>\n\n"
        "* [Második](masodik.md) - A második téma.\n")
    lessons = markers.read(text, "lessons").splitlines()
    assert lessons[0] == "| Dátum | Óra | Jegyzet | Témakörök |"
    assert lessons[2].startswith("| <span class=\"study-when study-when-unsure\" title=\"Dátum nélküli óra: szept. 3–10.\">~szept. eleje</span> | Folytatás |")
    assert "[Második](masodik.md#resz)" in lessons[2]
    assert lessons[3].startswith("| <span class=\"study-when\">szept. 3.</span> | Bevezetés | [jegyzet](2026-09-10-elso-jegyzet.md)")
    assert markers.read(text, "review").startswith("# 🔁 Ismétlés\n\n* [Dolgozatra]")
    assert markers.read(text, "notes") == "# 📝 Jegyzetek\n\n* [Első óra](2026-09-10-elso-jegyzet.md) - Jegyzet.\n"


def test_root_block_and_label(repo):
    text = generate.root_index(repo)
    assert markers.read(text, "subjects") == "* 🧪 [Próba](proba/index.md) - A próba tantárgy témakörei.\n"
    assert generate.subject_label(repo, "proba") == "🧪 Próba"
    assert generate.subject_sentence("Irodalom") == "Az irodalom tantárgy témakörei és jegyzetei."


def test_write_indexes_is_idempotent(repo):
    assert set(generate.write_indexes(repo)) == {"wiki/proba/index.md", "wiki/index.md"}
    assert generate.write_indexes(repo) == []


def test_an_undated_lesson_follows_the_lesson_before_it_in_the_notebook(repo):
    subject = generate.load_subject(repo, "proba")
    titles = [lesson["title"] for _, lesson in generate.lessons(subject)]
    assert titles == ["Folytatás", "Bevezetés"]


def test_partly_legible_date_is_kept_as_written():
    from school_notes2.wiki.generate import lesson_date
    assert lesson_date({"date_note": "2026-09-1? (levágva: 2026-09-10 és 2026-09-19 között)"}) == \
        "2026-09-1? (levágva: 2026-09-10 és 2026-09-19 között)"
    assert lesson_date({"date_note": "legkésőbb 2026-09-25"}) == "? (legkésőbb 2026-09-25)"


def test_a_full_date_in_the_note_keeps_the_question_mark_form():
    from school_notes2.wiki.generate import lesson_date
    assert lesson_date({"date_note": "2026-09-11 után, legkésőbb 2026-09-25"}) == \
        "? (2026-09-11 után, legkésőbb 2026-09-25)"


def test_equal_undated_lessons_follow_the_notebook():
    from school_notes2.wiki import teaching_order
    note = {"date_note": "2026-09-15 után, legkésőbb 2026-09-26", "title": "x"}
    found = teaching_order.ordered([
        ("2026-09-26-erorendszer-jegyzet.md", {"source_file": "sources/f/page-15.jpeg", "lessons": [note]}),
        ("2026-09-26-vetuletek-jegyzet.md", {"source_file": "sources/f/page-10.jpeg", "lessons": [note]})], {"f"})
    assert [lesson.file for lesson in found] == ["2026-09-26-vetuletek-jegyzet.md", "2026-09-26-erorendszer-jegyzet.md"]
    assert not any(lesson.uncertain for lesson in found)    # one folder: the notebook order is known


def test_catch_up_list_and_lesson_marks_are_neutral_and_stable(repo):
    from school_notes2.wiki import frontmatter
    path = repo / "wiki/proba/2026-09-10-elso-jegyzet.md"
    path.write_text(frontmatter.set_keys(path.read_text(), {"catch_up": "open", "notebook": "classmate"}))
    generate.write_indexes(repo)
    index = repo / "wiki/proba/index.md"
    text = index.read_text()
    # Fix-48: one sentence says what to do; each line gives the lesson dates and topics from
    # the page's own `lessons` fields, exactly as the lessons table shows them.
    assert markers.read(text, "catch-up") == (
        "# 📝 Pótolandó\n\n"
        "Ezeknek az óráknak az anyagát pótolnod kell: írd be a füzetedbe (vagy tanuld meg), és szólj, ha megvan.\n\n"
        "* [Első óra](2026-09-10-elso-jegyzet.md) - Dátum: <span class=\"study-when\">szept. 3.</span>, <span class=\"study-when study-when-unsure\" title=\"Dátum nélküli óra: szept. 3–10.\">~szept. eleje</span>. "
        "Témakörök: [Első](elso.md), [Második](masodik.md#resz).\n")
    assert text.index("../index.md") < text.index("# 📝 Pótolandó") < text.index("# 📘")
    assert markers.read(text, "lessons").startswith(
        "A 📝 jel pótolandó órát mutat: az anyagát írd be a füzetedbe (vagy tanuld meg), és szólj, ha megvan.\n\n"
        "| Dátum | Óra |")
    assert "| 📝 <span class=\"study-when\">szept. 3.</span> |" in text and '| 📝 <span class="study-when study-when-unsure"' in text
    # Neutral by rule (plan 7.13, the learner AGENTS.md): no illness icon, no absence statement.
    assert "🤒" not in text and "classmate" not in text and "hiányoz" not in text
    assert generate.write_indexes(repo) == []
    path.write_text(frontmatter.set_keys(path.read_text(), {"catch_up": "done"}))
    generate.write_indexes(repo)
    text = index.read_text()
    assert markers.read(text, "catch-up") == ""
    assert markers.read(text, "lessons").startswith("A ✅ jel a már pótolt órát mutatja.\n\n| Dátum |")
    assert "| ✅ <span class=\"study-when\">szept. 3.</span> |" in text and "# 📝 Pótolandó" not in text
    assert generate.write_indexes(repo) == []


def test_legacy_catch_up_list_replaced_without_touching_other_sections(repo):
    from school_notes2.wiki import frontmatter
    path = repo / "wiki/proba/2026-09-10-elso-jegyzet.md"
    path.write_text(frontmatter.set_keys(path.read_text(), {"catch_up": "open"}))
    idx = repo / "wiki/proba/index.md"
    idx.write_text(idx.read_text().replace("<br />", "# 🤒 Pótolandó\n\n* old\n\n<br />", 1))
    first = generate.subject_index(repo, "proba")
    assert "🤒" not in first and "* old" not in first
    assert first.count("# 📝 Pótolandó") == 1
    idx.write_text(first)
    assert generate.subject_index(repo, "proba") == first


def test_catch_up_order_is_total_and_independent_of_input_order():
    from school_notes2.wiki import catch_up
    pages = [generate.SubjectPage(name, {"catch_up": "open", "title": name})
             for name in ("2026-09-10-b.md", "2026-09-20-c.md", "2026-09-10-a.md")]
    text = "# Tárgy\n\n[⬅️ Vissza](../index.md)\n\n# 📌 Házi feladat\n\nMarad.\n"
    result = catch_up.update(text, generate.by_date_desc(pages))
    assert result == catch_up.update(text, generate.by_date_desc(list(reversed(pages))))
    assert result.index("2026-09-20-c") < result.index("2026-09-10-a") < result.index("2026-09-10-b")
    assert result.endswith("# 📌 Házi feladat\n\nMarad.\n")
