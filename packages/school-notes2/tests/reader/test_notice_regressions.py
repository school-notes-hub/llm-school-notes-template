"""2.2.2: VM index corruption, placement, tool feedback and durable replay."""


import pytest

from school_notes2.figures import pending
from school_notes2.reader import new_pages, notices, report, units, verdicts
from school_notes2.review import relations
from school_notes2.state import safefs
from school_notes2.wiki import drafts, frontmatter, lesson_log, markers
from .helpers import finding


DESCRIPTION = "<!-- image-description\nasset: ../assets/banner.png\nobserved: Áttekintés.\n-->\n"
BANNER = "![Fejléc](../assets/banner.png)\n\n" + DESCRIPTION
META = "---\ntitle: Téma\ntype: topic\n---\n"


def legacy_items(repo, page, quotes, *, status="open", unlocated=False):
    items = {f"R{n}": status for n in range(1, len(quotes) + 1)}
    details = {key: {"file": page, "quote": quote, "unlocated": unlocated,
                     "round": 1, "chain": 0, "origin": "reader"}
               for key, quote in zip(items, quotes)}
    safefs.write_text(repo, "docs/review/legacy.md", frontmatter.set_keys("# Review\n", {
        "items": items, "item_details": details, "status": "open"}))


def accept(repo, page):
    verdicts.record(repo, [{"file": page, "verdict": "ok"}],
                    {page: units.page_key(repo, page)}, "model", "today")


def refresh_twice(repo, page):
    notices.refresh(repo, [page, page])
    text = safefs.read_text(repo, page)
    markers.check(text)
    assert notices.refresh(repo, [page]) == []
    assert safefs.read_text(repo, page) == text
    return text


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("reason", ["missing", "unlocated", "draft"])
def test_page_notice_goes_to_the_fixed_place_after_frontmatter(setup, wrapped, reason):
    """I6: the tool's notice is placed after the frontmatter, never by reading the header."""
    ctx, _, page = setup
    safefs.write_json(ctx.notes_path, new_pages.PATH, {page: "v2-run"})
    banner = markers.wrap("figure-banner", BANNER) if wrapped else BANNER
    old = markers.wrap("pending", notices.PAGE)
    text = META + "# Téma\n\n" + old + "\n" + old + "\n" + banner + "\nBevezetés.\n"
    if reason == "draft":
        text = frontmatter.set_keys(text, {"status": "draft"})
    safefs.write_text(ctx.notes_path, page, text)
    if reason != "missing":
        accept(ctx.notes_path, page)
    if reason == "unlocated":
        legacy_items(ctx.notes_path, page, ["nincs ilyen mondat"], unlocated=True)
    result = refresh_twice(ctx.notes_path, page)
    if reason == "unlocated":
        assert "⏳" not in result
        return
    expected = drafts.NOTICE if reason == "draft" else notices.PAGE
    assert result.count(expected) == 1
    assert result.index(markers.OPEN.format(name="pending")) < result.index("# Téma")
    assert result.index(expected) < result.index("Bevezetés.")
    assert markers.read(result, "figure-banner") == BANNER if wrapped else BANNER in result


def test_vm_nested_duplicates_are_removed_and_authored_items_keep_notices(setup):
    ctx, _, page = setup
    safefs.write_json(ctx.notes_path, new_pages.PATH, {page: "v2-run"})
    name = "pending-section-7b79e662bcc8"
    old = markers.wrap(name, notices.SECTION)
    body = ("# Téma\n\n" + markers.wrap("pending", notices.PAGE) + "\n" + BANNER + "\n"
            + markers.wrap("notes", "# 📝 Jegyzetek\n\n" + old + "\n" + old + "\n* Jegyzetlista\n")
            + "\n# 🗓️ Órák\n\n" + markers.wrap("lessons", "Órabevezető\n")
            + "\nAz óra kézzel írt magyarázata.\n\n" + old + "\n"
            + markers.wrap("catch-up", "# 📝 Pótolandó\n\nPótolandó anyagok\n"))
    safefs.write_text(ctx.notes_path, page, META + body)
    legacy_items(ctx.notes_path, page, ["Jegyzetlista", "Jegyzetlista", "Órabevezető",
                                       "Pótolandó anyagok", "Az óra kézzel írt magyarázata."])
    result = refresh_twice(ctx.notes_path, page)
    assert result.count(notices.SECTION) == 0
    assert notices.SECTION not in markers.read(result, "notes")
    assert "* Jegyzetlista" in markers.read(result, "notes")
    assert "Órabevezető" in result
    assert result.index(notices.PAGE) < result.index("# Téma")
    assert "pending-section-7b79e662bcc8" not in result


@pytest.mark.parametrize("status", ["open", "owner"])
@pytest.mark.parametrize("unlocated", [False, True])
def test_legacy_tool_findings_do_not_mark_page_or_section(setup, status, unlocated):
    ctx, _, page = setup
    text = META + BANNER + markers.wrap("notes", "# 📝 Jegyzetek\n")
    safefs.write_text(ctx.notes_path, page, text)
    accept(ctx.notes_path, page)
    legacy_items(ctx.notes_path, page, ["# 📝 Jegyzetek"], status=status, unlocated=unlocated)
    assert refresh_twice(ctx.notes_path, page) == text


def test_generated_heading_gets_one_notice_after_its_block(setup):
    ctx, _, page = setup
    text = META + BANNER + "\n" + markers.wrap("notes", "# 📝 Jegyzetek\n\nLista.\n") + "\nKézi szöveg.\n"
    safefs.write_text(ctx.notes_path, page, text)
    accept(ctx.notes_path, page)
    legacy_items(ctx.notes_path, page, ["Kézi szöveg.", "Kézi szöveg."])
    result = refresh_twice(ctx.notes_path, page)
    assert result.count(notices.SECTION) == 0 and notices.PAGE not in result
    assert markers.read(result, "notes") == markers.read(text, "notes")
    assert verdicts.valid(ctx.notes_path, page) is not None


def test_same_heading_in_distinct_sections_and_authored_quote_not_lost(setup):
    ctx, _, page = setup
    text = (META + BANNER + "\n" + markers.wrap("notes", "# Lista\nIsmételt mondat.\n")
            + "\n# Rész\n\nIsmételt mondat.\n\n# Rész\n\nMásik mondat.\n")
    safefs.write_text(ctx.notes_path, page, text)
    accept(ctx.notes_path, page)
    legacy_items(ctx.notes_path, page, ["Ismételt mondat.", "Másik mondat."])
    result = refresh_twice(ctx.notes_path, page)
    assert result.count(notices.SECTION) == 0
    assert notices.SECTION not in markers.read(result, "notes")
    assert notices.PAGE not in result


def test_priority_and_disappearing_notices_preserve_author_key(setup):
    ctx, _, page = setup
    safefs.write_json(ctx.notes_path, new_pages.PATH, {page: "v2-run"})
    original = frontmatter.set_keys(META + "<!-- image: banner -->\n\n# Rész\n\nMondat.\n", {"status": "draft"})
    safefs.write_text(ctx.notes_path, page, original)
    key = units.page_key(ctx.notes_path, page)
    pending.record(ctx.notes_path, {"id": "banner", "page": page, "kind": "banner", "anchor": "Rész",
                                   "purpose": "Áttekintés", "must_show": [], "avoid_misreading": "Nem tanító ábra.",
                                   "taught_conventions": [], "text_complete_without_figure": True}, "run", [])
    result = refresh_twice(ctx.notes_path, page)
    # The page notice sits at the fixed place, the figure notice at its marker (I6).
    assert result.count("⏳") == 2 and notices.FIGURE in result and notices.PAGE in result
    safefs.write_json(ctx.notes_path, "docs/figure-pending.json", [])
    result = refresh_twice(ctx.notes_path, page)
    assert result.count("⏳") == 1 and notices.PAGE in result
    accept(ctx.notes_path, page)
    result = refresh_twice(ctx.notes_path, page)
    assert result.count("⏳") == 1 and drafts.NOTICE in result
    assert units.page_key(ctx.notes_path, page) == key
    safefs.write_text(ctx.notes_path, page, frontmatter.set_keys(result, {}, remove=("status",)))
    accept(ctx.notes_path, page)
    result = refresh_twice(ctx.notes_path, page)
    assert "⏳" not in result
    assert result == frontmatter.set_keys(original, {}, remove=("status",))


def test_new_tool_block_goes_after_frontmatter_without_nesting():
    text = META + markers.wrap("figure-banner", BANNER) + "\nBevezetés.\n"
    result = lesson_log.after_header(text, "lesson-sources", "Forrásutaló\n")
    markers.check(result)
    assert markers.read(result, "figure-banner") == BANNER
    assert result.index("Forrásutaló") < result.index(BANNER)


def test_notice_write_interruption_resumes_byte_identically(setup, monkeypatch):
    ctx, _, page = setup
    second = "wiki/m/second.md"
    text = META + BANNER + "\n# Rész\n\nSzöveg.\n"
    for path in (page, second):
        safefs.write_text(ctx.notes_path, path, text)
    safefs.write_json(ctx.notes_path, new_pages.PATH, {p: "writer-run" for p in (page, second)})
    original = safefs.write_text
    fired = []
    def crash(repo, path, value):
        original(repo, path, value)
        if not fired:
            fired.append(path)
            raise RuntimeError("after notice")
    monkeypatch.setattr(safefs, "write_text", crash)
    with pytest.raises(RuntimeError, match="after notice"):
        notices.refresh(ctx.notes_path, [page, second])
    written = safefs.read_bytes(ctx.notes_path, fired[0])
    notices.refresh(ctx.notes_path, [page, second])
    assert safefs.read_bytes(ctx.notes_path, fired[0]) == written
    assert notices.refresh(ctx.notes_path, [page, second]) == []
    assert safefs.read_bytes(ctx.notes_path, page) == safefs.read_bytes(ctx.notes_path, second)


def test_heading_directly_before_generated_block_keeps_notice_before_block(setup):
    ctx, _, page = setup
    text = META + BANNER + "\n# Rész\n" + markers.wrap("notes", "Lista.\n") + "\nKézi mondat.\n"
    safefs.write_text(ctx.notes_path, page, text)
    accept(ctx.notes_path, page)
    legacy_items(ctx.notes_path, page, ["Kézi mondat."])
    result = refresh_twice(ctx.notes_path, page)
    assert notices.SECTION not in result
    assert result.index("# Rész") < result.index(markers.OPEN.format(name="notes"))
    assert verdicts.valid(ctx.notes_path, page) is not None
