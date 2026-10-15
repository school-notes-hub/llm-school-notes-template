"""Regression cases from the independent review of the learner-page structure."""
import pytest

from school_notes2.wiki import date_spans, generate, markers, teaching_order


def test_each_lesson_has_a_date_target(repo):
    subject = generate.load_subject(repo, "proba")
    rows = generate.lesson_rows(subject)
    links = generate.lesson_links(subject)["2026-09-10-elso-jegyzet.md"]
    assert all(ids for _, ids in rows)
    assert links["@szept. 3."] in rows[1][1]
    assert links["@~szept. eleje"] in rows[0][1]
    assert links["@szept. 3."] != links[""]
    assert generate.lesson_links(subject) == generate.lesson_links(subject)
    # A source anchor that happens to be a row number must not steal another row's ID.
    log = subject.by_type("lesson-notes")[0]
    log.meta["lessons"][0]["anchor"] = "2"
    links = generate.lesson_links(subject)[log.file]
    rows = generate.lesson_rows(subject)
    assert links["2"] in rows[1][1]
    ids = [i for _, targets in rows for i in targets]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("entries,label", [
    ([{"date_note": "2026-10-01 után, legkésőbb 2026-10-31", "topics": ["elso.md#resz"]},
      {"date_note": "2026-10-01 után, legkésőbb 2026-10-31", "topics": ["masodik.md"]}], "~okt."),
    ([{"date": "2026-09-03", "topics": ["elso.md"]},
      {"date": "2026-09-04", "topics": ["elso.md", "masodik.md"]},
      {"date": "2026-09-09", "topics": ["masodik.md"]}], "szept. 3–4."),
])
def test_ambiguous_or_combined_dates_choose_the_first_covering_lesson(repo, entries, label):
    subject = generate.load_subject(repo, "proba")
    log = subject.by_type("lesson-notes")[0]
    log.meta["lessons"] = entries
    rows = generate.lesson_rows(subject)
    links = generate.lesson_links(subject)[log.file]
    resolve = lambda text, page: next(links[k] for k in
        (f"@{text}|{page}", f"@{text}", f"|{page}", "") if k in links)
    first = next(ids for item, ids in rows if item.index == 0)
    assert resolve(label, "elso.md") in first
    # Ambiguous or missing dates fall back to a covering row.
    for page in {t for item, _ in rows for t in item.topics}:
        for text in (label, "ismeretlen"):
            target = resolve(text, page)
            assert any(target in ids and page in item.topics for item, ids in rows)
    if label == "~okt.":
        assert links["@~okt.|elso.md"] in first
        assert "@~okt." not in links
    else:
        second = next(ids for item, ids in rows if item.index == 1)
        assert links["@szept. 4.|elso.md"] in second
    ids = [i for _, targets in rows for i in targets]
    assert len(ids) == len(set(ids))
    assert generate.lesson_links(subject)[log.file] == links


def test_exact_unique_span_preserves_a_lesson_not_listing_the_linking_page(repo):
    subject = generate.load_subject(repo, "proba")
    log = subject.by_type("lesson-notes")[0]
    log.meta["lessons"] = [
        {"date": "2026-09-29", "topics": ["elso.md"], "anchor": "polis"},
        {"date_note": "2026-09-28 után, legkésőbb 2026-10-06", "topics": ["masodik.md"]},
    ]
    found = generate.ordered_lessons(subject)
    exact = generate.when(next(x for x in found if x.index == 1), 2026)
    text = f'<sub>🗓️ Óra: [{exact}]({log.file})</sub>\n'
    assert date_spans.page_changes(text, "elso.md", found) == []
    # An explicit anchor still wins over even a byte-identical span of another lesson.
    anchored = text.replace(f"]({log.file})", f"]({log.file}#polis)")
    [change] = date_spans.page_changes(anchored, "elso.md", found)
    assert change[3] == generate.when(next(x for x in found if x.index == 0), 2026)
    # Identical spans on two lessons are not unique: use the covered lesson instead.
    log.meta["lessons"].append(dict(log.meta["lessons"][1]))
    [change] = date_spans.page_changes(text, "elso.md", generate.ordered_lessons(subject))
    assert change[3] == generate.when(next(x for x in found if x.index == 0), 2026)


@pytest.mark.parametrize("title,label", [
    (' title="Dátum nélküli óra: szept. 20. – okt. 9."', "~szept. vége"),
    ("", "~szept. vége"),
    (' title="Régi súgó"', "~szept. v&#233;ge"),
])
def test_unique_visible_date_preserves_noncovering_lesson_with_stale_tooltip(title, label):
    entries = [
        {"date": "2026-09-29", "topics": ["elso.md"]},
        {"date_note": "2026-09-28 után, legkésőbb 2026-10-06", "topics": ["masodik.md"]},
    ]
    found = teaching_order.ordered([("ora.md", {"lessons": entries})], set())
    exact = generate.when(next(x for x in found if x.index == 1), 2026)
    assert ">~szept. vége</span>" in exact
    stale = f'<span class="study-when study-when-unsure"{title}>{label}</span>'
    text = f'<sub>🗓️ Óra: [{stale}](ora.md)</sub>\n'
    [(start, end, old, new)] = date_spans.page_changes(text, "elso.md", found)
    assert old == stale
    assert new == exact
    assert date_spans.page_changes(text[:start] + new + text[end:], "elso.md", found) == []
    # A repeated visible date does not identify a lesson: retain the coverage fallback.
    entries.append(dict(entries[1]))
    duplicate = teaching_order.ordered([("ora.md", {"lessons": entries})], set())
    [change] = date_spans.page_changes(text, "elso.md", duplicate)
    assert change[3] == generate.when(next(x for x in duplicate if x.index == 0), 2026)


@pytest.mark.parametrize("day,old_label", [("2026-09-04", "~szept. eleje"), ("2026-09-29", "~szept. közepe")])
def test_date_sweep_uses_topic_coverage_before_datedness(day, old_label):
    found = teaching_order.ordered([("ora.md", {"lessons": [
        {"date": day, "topics": ["elso.md#resz"]},
        {"date_note": "2026-09-01 után, legkésőbb 2026-09-30", "topics": ["masodik.md"]},
    ]})], set())
    # This fallback applies only after both exact and visible-date matching fail.
    assert all(old_label not in generate.when(x, 2026) for x in found)
    old = f'<span class="study-when study-when-unsure" title="Régi időszak">{old_label}</span>'
    text = f'<sub>🗓️ Óra: [{old}](ora.md) · 🔖 Tankönyv: 2. lecke</sub>\n'
    [change] = date_spans.page_changes(text, "elso.md", found)
    start, end, previous, new = change
    assert previous == old
    assert new == generate.when(next(x for x in found if x.dated), 2026)
    updated = text[:start] + new + text[end:]
    assert updated.endswith(' · 🔖 Tankönyv: 2. lecke</sub>\n')
    assert date_spans.page_changes(updated, "elso.md", found) == []
    # Two dated covering lessons do not justify choosing one visible date for the sweep.
    ambiguous = teaching_order.ordered([("ora.md", {"lessons": [
        {"date": "2026-09-03", "topics": ["elso.md"]},
        {"date": "2026-09-04", "topics": ["elso.md"]},
    ]})], set())
    assert date_spans.page_changes(text, "elso.md", ambiguous) == []


def test_a_missing_home_legend_does_not_duplicate_the_guide():
    text = markers.wrap("subjects", "") + markers.wrap("guide", "Keep this.\n")
    new = generate.place_home_blocks(text)
    assert markers.names(new) == ["subjects", "guide", "legend"]
    assert markers.read(new, "guide") == "Keep this.\n"
    markers.check(new)
    assert generate.place_home_blocks(new) == new


@pytest.mark.parametrize("extra", ["A saját mondatom.\n", "| A | B |\n|---|---|\n| 1 | 2 |\n"])
def test_lesson_heading_sweep_keeps_unknown_text(extra):
    text = "# 🗓️ Órák\n\nA legújabb óra van legfelül.\n\n" + extra + markers.wrap("lessons", "")
    assert generate.move_lessons_head(text) == text
    for legend in generate.LEGACY_LESSONS_LEGENDS:
        block = markers.wrap("lessons", "Keep the generated block.\n")
        old = "# 🗓️ Órák\n\n" + legend + "\n\n" + block
        assert generate.move_lessons_head(old) == block
        assert generate.move_lessons_head(block) == block


def test_guide_distinguishes_earlier_chapters(repo):
    assert "✓ a korábban kezdett" in generate.guide_block(repo)


def test_legend_describes_link_tooltips_truthfully():
    legend = generate.legend_block()
    assert "link nélküli címkén koppintásra is" in legend
    assert "link nélküli dátumon koppintásra is" in legend


def test_now_uses_summary_icon_and_own_callout(repo):
    subject = generate.load_subject(repo, "proba")
    subject.by_type("lesson-notes")[0].meta["lessons"][-1]["topics"] = ["osszefoglalo-alapok.md", "elso.md"]
    text = generate.now_block(subject)
    assert text.startswith("> [!PROGRESS]\n")
    assert "> **Most:** ⚡ [Összefoglaló: Alapok]" in text
    assert " · 📄 [Első]" in text
