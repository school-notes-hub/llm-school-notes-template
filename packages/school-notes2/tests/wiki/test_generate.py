from school_notes2.wiki import generate, markers


def test_subject_blocks(repo):
    # plan terv-oldalszerkezet T2: numbered chapters with a jump target and a ✓/◉ mark, 📄 numbered
    # worked lessons with the description apart, the summary last with its fixed note, `◀ itt
    # tartunk` at the latest lesson's pages; the lessons as a list with row targets, never a link
    # to a lesson log; the lesson-log list empty
    text = generate.subject_index(repo, "proba")
    assert markers.read(text, "chapters") == (
        '# <a id="fejezet-alapok"></a>📘 1. fejezet: Alapok ✓\n\n'
        '<span class="study-when study-when-unsure" title="Nem biztos: a vége dátum nélküli óra (szept. 3–10.)">~szept. eleje</span>\n\n'
        '* 📄 1. [Első](elso.md) ◀ itt tartunk <span class="study-desc">Az első téma.</span>\n'
        '* ⚡ [Összefoglaló: Alapok](osszefoglalo-alapok.md) <span class="study-desc">A fejezet röviden, ismétléshez és dolgozat előtt.</span>\n'
        "\n<br />\n\n"
        '# <a id="fejezet-halado"></a>📘 2. fejezet: Haladó ◉ most\n\n'
        '<span class="study-when study-when-unsure" title="Nem biztos: a kezdete dátum nélküli óra (szept. 3–10.)">~szept. eleje óta</span>\n\n'
        '* 📄 1. [Második](masodik.md) ◀ itt tartunk <span class="study-desc">A második téma.</span>\n')
    assert markers.read(text, "lessons") == (
        "# 🗓️ Órák – melyik órán mit vettünk\n\n"
        "A legújabb óra van legfelül. A `~` bizonytalan dátumot jelöl; az időszakot az egér rávitelekor vagy koppintásra látod.\n\n"
        '* <a id="ora-2026-09-10-elso-jegyzet-2"></a><a id="ora-2026-09-10-elso-jegyzet"></a>Folytatás <span class="study-when study-when-unsure" title="Dátum nélküli óra: szept. 3–10.">~szept. eleje</span>'
        "<br />→ [Első](elso.md) · [Második](masodik.md#resz)\n"
        '* <a id="ora-2026-09-10-elso-jegyzet-1"></a>Bevezetés <span class="study-when">szept. 3.</span><br />→ [Első](elso.md)\n')
    assert markers.read(text, "review").startswith("# 🔁 Ismétlés\n\n* [Dolgozatra]")
    assert markers.read(text, "notes") == ""
    # the hand-written heading and legend moved into the block (one-time sweep)
    assert "\n# 🗓️ Órák\n" not in text and text.count("A legújabb óra van legfelül.") == 1


def test_lesson_titles_never_start_markdown_structure():
    assert generate.plain_line("1. óra: atomok") == "1\\. óra: atomok"
    assert generate.plain_line("# cím") == "\\# cím"
    assert generate.plain_line("Hővezetés, 2. rész") == "Hővezetés, 2. rész"
    assert generate.anchor_id("ora-2026-09-29-x-jegyzet-Pdf_15 oldal") == "ora-2026-09-29-x-jegyzet-pdf-15-oldal"


def test_root_block_and_label(repo):
    text = generate.root_index(repo)
    # T12: no template sentence; the chapters, smaller
    assert markers.read(text, "subjects") == ("* 🧪 [Próba](proba/index.md) <span class=\"study-desc\">"
                                              "Fejezetek: Alapok · Haladó</span>\n")
    assert generate.subject_label(repo, "proba") == "🧪 Próba"
    assert generate.subject_sentence("Irodalom") == "Az irodalom tantárgy témakörei és jegyzetei."
    for sentence in ("Az irodalom tantárgy témakörei és jegyzetei.",
                     "A történelem tantárgy témakörei és jegyzetei, évfolyamonként.", "A próba tantárgy témakörei."):
        assert generate.TEMPLATE_SENTENCE.match(sentence)
    assert not generate.TEMPLATE_SENTENCE.match("Kémiai és fizikai anyagtulajdonságok.")


def test_home_page_guide_and_legend_blocks(repo):
    # T4: the hand-written legend section becomes the two blocks, once; the text after it stays
    root = repo / "wiki/index.md"
    root.write_text(root.read_text() + "\n# 🔎 Jelmagyarázat\n\nKézi szöveg.\n\n* 💡 régi\n\n## A projektről\n\nMarad.\n")
    text = generate.root_index(repo)
    assert markers.names(text) == ["subjects", "guide", "legend"]
    assert "Kézi szöveg" not in text and text.endswith("<!-- /school-notes:generated -->\n\n## A projektről\n\nMarad.\n")
    guide = markers.read(text, "guide")
    assert guide.startswith('# <a id="hogyan-hasznald"></a>🧭 Hogyan használd\n\n* 📚 **Tantárgyoldal**')
    assert "🎧" not in guide                       # no Podcast page in this repo
    assert "<br" not in guide                      # an HTML line there would swallow the legend heading
    assert markers.read(text, "legend").startswith("# 🔎 Jelmagyarázat\n\nA jelöletlen szöveg")
    root.write_text(text)
    assert generate.root_index(repo) == text       # idempotent
    # without a hand-written section: right after the subjects block
    fresh = generate.place_home_blocks("# T\n\n" + markers.wrap("subjects", "") + "\n## Vége\n")
    assert fresh == ("# T\n\n" + markers.wrap("subjects", "") + "\n<br />\n\n" + markers.wrap("guide", "")
                     + markers.wrap("legend", "") + "\n## Vége\n")


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


def test_catch_up_is_retired_and_its_block_stays_empty(repo):
    # T1 (owner 2026-10-15): no 📝 Pótolandó list and no 📝/✅ mark; the frontmatter key stays
    from school_notes2.wiki import frontmatter
    path = repo / "wiki/proba/2026-09-10-elso-jegyzet.md"
    path.write_text(frontmatter.set_keys(path.read_text(), {"catch_up": "open", "notebook": "classmate"}))
    index = repo / "wiki/proba/index.md"
    index.write_text(index.read_text().replace("<br />", markers.wrap("catch-up", "# 📝 Pótolandó\n\n* régi\n") + "\n<br />", 1))
    generate.write_indexes(repo)
    text = index.read_text()
    assert markers.read(text, "catch-up") == ""
    assert "Pótolandó" not in text and "📝" not in text and "✅" not in text
    assert "🤒" not in text and "classmate" not in text and "hiányoz" not in text
    assert generate.write_indexes(repo) == []


def test_legacy_catch_up_list_replaced_without_touching_other_sections(repo):
    idx = repo / "wiki/proba/index.md"
    idx.write_text(idx.read_text().replace("<br />", "# 🤒 Pótolandó\n\n* old\n\n<br />", 1))
    first = generate.subject_index(repo, "proba")
    assert "🤒" not in first and "* old" not in first and "Pótolandó" not in first
    assert "catch-up" in markers.names(first) and markers.read(first, "catch-up") == ""
    idx.write_text(first)
    assert generate.subject_index(repo, "proba") == first
