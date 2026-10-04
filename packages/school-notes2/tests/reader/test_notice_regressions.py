"""2.2.2: VM index corruption, placement, tool feedback and durable replay."""

from types import SimpleNamespace

import pytest

from school_notes2.flows import correction, inspection
from school_notes2.figures import pending
from school_notes2.reader import calls, notices, report, units, verdicts
from school_notes2.review import generated, relations
from school_notes2.state import phase, safefs
from school_notes2.wiki import drafts, frontmatter, lesson_log, markers
from .test_phases import finding
from .test_reader import pass1


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
def test_page_notice_moves_after_banner_and_description(setup, wrapped, reason):
    ctx, _, page = setup
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
    expected = drafts.NOTICE if reason == "draft" else notices.PAGE
    assert result.count(expected) == 1
    assert result.index(markers.OPEN.format(name="pending")) > result.index(DESCRIPTION)
    assert result.index(expected) < result.index("Bevezetés.")
    assert markers.read(result, "figure-banner") == BANNER if wrapped else BANNER in result


def test_vm_nested_duplicates_are_removed_and_authored_items_keep_notices(setup):
    ctx, _, page = setup
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
    assert result.count(notices.SECTION) == 1
    assert notices.SECTION not in markers.read(result, "notes")
    assert "* Jegyzetlista" in markers.read(result, "notes")
    assert result.index("# 🗓️ Órák") < result.index(notices.SECTION) < result.index("Órabevezető")
    assert result.index(notices.PAGE) > result.index(DESCRIPTION)
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
    assert result.count(notices.SECTION) == 1 and notices.PAGE not in result
    assert markers.read(result, "notes") == markers.read(text, "notes")
    assert result.index(notices.SECTION) > result.index(markers.CLOSE)
    assert verdicts.valid(ctx.notes_path, page) is not None


def test_same_heading_in_distinct_sections_and_authored_quote_not_lost(setup):
    ctx, _, page = setup
    text = (META + BANNER + "\n" + markers.wrap("notes", "# Lista\nIsmételt mondat.\n")
            + "\n# Rész\n\nIsmételt mondat.\n\n# Rész\n\nMásik mondat.\n")
    safefs.write_text(ctx.notes_path, page, text)
    accept(ctx.notes_path, page)
    legacy_items(ctx.notes_path, page, ["Ismételt mondat.", "Másik mondat."])
    result = refresh_twice(ctx.notes_path, page)
    assert result.count(notices.SECTION) == 2
    assert notices.SECTION not in markers.read(result, "notes")
    assert notices.PAGE not in result


def test_priority_and_disappearing_notices_preserve_author_key(setup):
    ctx, _, page = setup
    original = frontmatter.set_keys(META + "<!-- image: banner -->\n\n# Rész\n\nMondat.\n", {"status": "draft"})
    safefs.write_text(ctx.notes_path, page, original)
    key = units.page_key(ctx.notes_path, page)
    pending.record(ctx.notes_path, {"id": "banner", "page": page, "kind": "banner", "anchor": "Rész",
                                   "purpose": "Áttekintés", "must_show": [], "avoid_misreading": "Nem tanító ábra.",
                                   "taught_conventions": [], "text_complete_without_figure": True}, "run", [])
    result = refresh_twice(ctx.notes_path, page)
    assert result.count("⏳") == 1 and notices.FIGURE in result
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


@pytest.mark.parametrize("quote, expected", [("# 📝 Jegyzetek", True), ("# 📝\n Jegyzetek", True),
                                               ("Kézi mondat.", False), ("nincs", False), ("", False),
                                               ("# 📝 Jegyzetek\n<!-- /school-notes:generated -->\nKézi", False)])
def test_generated_quote_must_be_fully_contained(quote, expected):
    text = markers.wrap("notes", "# 📝 Jegyzetek\n") + "Kézi mondat.\n"
    assert generated.only_literals(text, quote) is expected


def test_new_header_blocks_follow_description_without_nesting():
    text = META + markers.wrap("figure-banner", BANNER) + "\nBevezetés.\n"
    result = lesson_log.after_header(text, "lesson-sources", "Forrásutaló\n")
    markers.check(result)
    assert markers.read(result, "figure-banner") == BANNER
    assert result.index("Forrásutaló") > result.index(DESCRIPTION)


@pytest.mark.parametrize("mixed", [False, True])
@pytest.mark.parametrize("boundary", ["report", "verdicts"])
def test_tool_feedback_and_page_verdict_resume_without_duplicate_or_writer_work(setup, monkeypatch, mixed, boundary):
    ctx, task, page = setup
    text = safefs.read_text(ctx.notes_path, page) + "\n" + markers.wrap("notes", "# 📝 Jegyzetek\n")
    safefs.write_text(ctx.notes_path, page, text)
    tool = {**finding(page), "quote": "# 📝 Jegyzetek", "problem": "Sablonhiba."}
    findings = [tool, {**tool, "id": "F-2"}]
    if mixed:
        findings.append({**finding(page), "id": "F-3"})
    invoked = []
    def invoke(*args, **kwargs):
        invoked.append(1)
        return SimpleNamespace(output=pass1(page, findings))
    monkeypatch.setattr(calls.launch, "run_headless", invoke)
    inspection.prepare(ctx, task)
    method = "write_text" if boundary == "report" else "write_json"
    original = getattr(safefs, method)
    fired = []
    def crash(repo, path, *args, **kwargs):
        result = original(repo, path, *args, **kwargs)
        target = str(path).endswith("-run.md") if boundary == "report" else path == verdicts.PATH
        if target and not fired:
            fired.append(1)
            raise RuntimeError("after write")
        return result
    monkeypatch.setattr(safefs, method, crash)
    with pytest.raises(RuntimeError, match="after write"):
        inspection.inspect(ctx, task)
    task = phase.load(task.dir)
    inspection.inspect(ctx, task)
    path = task.get("inspection_report")
    result = safefs.read_text(ctx.notes_path, path)
    assert invoked == [1]
    assert result.count("Tool-sablon") == 1 and "Sablonhiba." in result
    assert len(task.get("reader_owner_notes")) == 1
    assert len(correction.assigned(ctx, task)) == int(mixed)
    assert verdicts.valid(ctx.notes_path, page)["verdict"] == ("changes" if mixed else "ok")
    notices_text = refresh_twice(ctx.notes_path, page)
    assert notices.PAGE not in notices_text
    assert notices_text.count(notices.SECTION) == int(mixed)
    assert "Sablonhiba" not in notices_text
    before = safefs.read_bytes(ctx.notes_path, path)
    inspection.inspect(ctx, phase.load(task.dir))
    assert safefs.read_bytes(ctx.notes_path, path) == before


def test_supplement_routes_tool_findings_to_owner_notes_and_replays(setup):
    ctx, _, page = setup
    safefs.write_text(ctx.notes_path, page, META + BANNER + markers.wrap("notes", "# 📝 Jegyzetek\n"))
    path = "docs/review/run.md"
    tool = {**finding(page), "quote": "# 📝 Jegyzetek", "origin": "list"}
    kept, notes, _ = report.prepare(ctx.notes_path, [tool], [])
    report.write(ctx.notes_path, path, kept, notes, "model", "base", "2026-10-04")
    assert not relations.inventory(ctx.notes_path)["items"]
    report.append(ctx.notes_path, path, kept, notes, "recheck")
    assert not relations.inventory(ctx.notes_path)["items"]
    before = safefs.read_bytes(ctx.notes_path, path)
    assert "Tool-sablon" in before.decode()
    report.append(ctx.notes_path, path, kept, notes, "recheck")
    assert safefs.read_bytes(ctx.notes_path, path) == before


def test_notice_write_interruption_resumes_byte_identically(setup, monkeypatch):
    ctx, _, page = setup
    second = "wiki/m/second.md"
    text = META + BANNER + "\n# Rész\n\nSzöveg.\n"
    for path in (page, second):
        safefs.write_text(ctx.notes_path, path, text)
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


def test_recheck_tool_hit_does_not_spoil_repaired_page_verdict(setup):
    from school_notes2.flows import recheck
    from school_notes2.review import files
    ctx, task, page = setup
    text = safefs.read_text(ctx.notes_path, page) + "\n" + markers.wrap("notes", "# 📝 Jegyzetek\n")
    safefs.write_text(ctx.notes_path, page, text)
    path = "docs/review/run.md"
    report.write(ctx.notes_path, path, [{**finding(page), "origin": "reader"}], [], "model", "base", "2026-10-04")
    files.apply_closure(ctx.notes_path, "fix", [{"file": path, "item_id": "R1", "status": "fixed"}], [])
    key = path + "#R1"
    hit = {"id": "H1", "file": page, "line": text[:text.index("# 📝 Jegyzetek")].count("\n") + 1}
    task.update(inspection_report=path, reader_pages=[{"file": page}])
    saved = {"receipts": {}, "units": [{"status": "reviewed", "model": "model", "hits": [hit],
             "items": [{"key": key, "file": page}], "review": {
                 "items": [{"key": key, "verdict": "ok", "answer": "Javítva."}],
                 "hits": [{"hit_id": "H1", "verdict": "hiba", "reason": "Sablonhiba."}], "owner_notes": []}}]}
    recheck._apply(ctx, task, saved)
    assert verdicts.valid(ctx.notes_path, page)["verdict"] == "ok"
    assert len(relations.inventory(ctx.notes_path)["items"]) == 1
    assert len(task.get("recheck_owner_notes")) == 1
    assert "Tool-sablon" in safefs.read_text(ctx.notes_path, path)
    before = safefs.read_bytes(ctx.notes_path, path)
    recheck._apply(ctx, phase.load(task.dir), saved)
    assert safefs.read_bytes(ctx.notes_path, path) == before


def test_heading_directly_before_generated_block_keeps_notice_before_block(setup):
    ctx, _, page = setup
    text = META + BANNER + "\n# Rész\n" + markers.wrap("notes", "Lista.\n") + "\nKézi mondat.\n"
    safefs.write_text(ctx.notes_path, page, text)
    accept(ctx.notes_path, page)
    legacy_items(ctx.notes_path, page, ["Kézi mondat."])
    result = refresh_twice(ctx.notes_path, page)
    assert result.index("# Rész") < result.index(notices.SECTION) < result.index(markers.OPEN.format(name="notes"))
    assert verdicts.valid(ctx.notes_path, page) is not None
