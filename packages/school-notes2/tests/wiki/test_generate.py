from school_notes2.wiki import generate, markers


def test_subject_blocks(repo):
    text = generate.subject_index(repo, "proba")
    chapters = markers.read(text, "chapters")
    assert chapters == (
        "# 📘 9. évfolyam: Alapok\n\n"
        "* ⚡ [Összefoglaló: Alapok](osszefoglalo-alapok.md) - Rövid.\n"
        "* [Első](elso.md) - Az első téma.\n"
        "\n<br />\n\n"
        "# 📘 9. évfolyam: Haladó\n\n* [Második](masodik.md) - A második téma.\n")
    lessons = markers.read(text, "lessons").splitlines()
    assert lessons[0] == "| Dátum | Óra | Jegyzet | Témakörök |"
    assert lessons[2].startswith("| ? (legkésőbb 2026-09-10) | Folytatás |")
    assert "[Második](masodik.md#resz)" in lessons[2]
    assert lessons[3].startswith("| 2026-09-03 | Bevezetés | [jegyzet](2026-09-10-elso-jegyzet.md)")
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


def test_undated_lesson_sorts_by_latest_possible_date(repo):
    subject = generate.load_subject(repo, "proba")
    titles = [lesson["title"] for _, lesson in generate.lessons(subject)]
    assert titles == ["Folytatás", "Bevezetés"]


def test_partly_legible_date_is_kept_as_written():
    from school_notes2.wiki.generate import lesson_date
    assert lesson_date({"date_note": "2026-09-1? (levágva: 2026-09-10 és 2026-09-19 között)"}) == \
        "2026-09-1? (levágva: 2026-09-10 és 2026-09-19 között)"
    assert lesson_date({"date_note": "legkésőbb 2026-09-25"}) == "? (legkésőbb 2026-09-25)"


def test_lesson_anchor_survives_migration_and_generation():
    from school_notes2.wiki.migrate import parse_row
    lesson, file = parse_row("| 2026-09-17 | Hővezetés | [Füzet](2026-09-29-x-jegyzet.md#pdf-13-oldal); "
                             "[Hőterjedés](hoterjedes.md) |")
    assert file == "2026-09-29-x-jegyzet.md" and lesson["anchor"] == "pdf-13-oldal"
    assert lesson["topics"] == ["hoterjedes.md"]


def test_a_full_date_in_the_note_keeps_the_question_mark_form():
    from school_notes2.wiki.generate import lesson_date
    assert lesson_date({"date_note": "2026-09-11 után, legkésőbb 2026-09-25"}) == \
        "? (2026-09-11 után, legkésőbb 2026-09-25)"


def test_equal_undated_lessons_follow_the_notebook():
    from school_notes2.wiki.generate import SubjectPage, lesson_sort_key
    early = SubjectPage("2026-09-26-vetuletek-jegyzet.md", {"source_file": "sources/f/page-10.jpeg"})
    late = SubjectPage("2026-09-26-erorendszer-jegyzet.md", {"source_file": "sources/f/page-15.jpeg"})
    note = {"date_note": "2026-09-15 után, legkésőbb 2026-09-26"}
    keys = sorted([(lesson_sort_key(early, 0, note), "early"), (lesson_sort_key(late, 0, note), "late")],
                  reverse=True)
    assert [k[1] for k in keys] == ["late", "early"]       # newest first: page 15 before page 10


def test_catch_up_list_and_lesson_marks_are_neutral_and_stable(repo):
    from school_notes2.wiki import frontmatter
    path = repo / "wiki/proba/2026-09-10-elso-jegyzet.md"
    path.write_text(frontmatter.set_keys(path.read_text(), {"catch_up": "open", "notebook": "classmate"}))
    generate.write_indexes(repo)
    index = repo / "wiki/proba/index.md"
    text = index.read_text()
    assert markers.read(text, "catch-up") == (
        "# 📝 Pótolandó\n\n* [Első óra](2026-09-10-elso-jegyzet.md)\n")
    assert text.index("../index.md") < text.index("# 📝 Pótolandó") < text.index("# 📘")
    assert "| 📝 2026-09-03 |" in text and "| 📝 ? (legkésőbb" in text
    assert "🤒" not in text and "classmate" not in text
    assert generate.write_indexes(repo) == []
    path.write_text(frontmatter.set_keys(path.read_text(), {"catch_up": "done"}))
    generate.write_indexes(repo)
    text = index.read_text()
    assert markers.read(text, "catch-up") == ""
    assert "| ✅ 2026-09-03 |" in text and "# 📝 Pótolandó" not in text
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
