"""Fixed literals, copied metadata and figure content have different repair owners."""

import pytest

from school_notes2.flows import inspection
from school_notes2.reader import report, verdicts
from school_notes2.review import generated, relations
from school_notes2.state import safefs
from school_notes2.wiki import frontmatter, generate, markers
from .test_phases import finding


@pytest.mark.parametrize("name,body,quote", [
    ("notes", "# 📝 Jegyzetek\n\n* [Cím](p.md) - Leírás.", "Jegyzetek"),
    ("review", "# 🔁 Ismétlés\n", "Ismétlés"),
    ("catch-up", "# 📝 Pótolandó\n", "Pótolandó"),
    ("lessons", generate.TABLE_HEAD + "| 2026-10-04 | Óracím |", generate.TABLE_HEAD),
    ("pending", "⏳ Ezt az oldalt még ellenőrizzük.", "Ezt az oldalt még ellenőrizzük."),
    ("lesson-sources", "📎 Füzet: 2026. 10. 04. · Tanári anyag: Próba (lap)", "📎 Füzet:"),
    ("lesson-sources", "📎 Füzet: 2026. 10. 04. · Tanári anyag: Próba (lap)", "Tanári anyag:"),
])
def test_only_fixed_literal_ranges(name, body, quote):
    text = markers.wrap(name, body)
    assert generated.only_literals(text, quote)
    assert not generated.only_literals(text + quote + "\n", quote)


@pytest.mark.parametrize("name,body,quote", [
    ("notes", "# 📝 Jegyzetek\n\n* [Cím](p.md) - Leírás.", "Leírás."),
    ("chapters", "# 📘 Egy fejezet", "Egy fejezet"),
    ("lessons", generate.TABLE_HEAD + "| 2026-10-04 | Óracím |", "Óracím"),
    ("lesson-sources", "📎 Füzet: 2026. 10. 04. · Tanári anyag: Próba (lap)", "Próba (lap)"),
    ("lesson-sources", "📎 Füzet: 2026. 10. 04.", "2026. 10. 04."),
    ("lesson-sources", "📎 Füzet: 2026. 10. 04.", "📎 Füzet: 2026. 10. 04."),
    ("pending", "Változó szöveg", "Változó szöveg"),
    ("figure-example", "![Felirat](../assets/a.png)", "Felirat"),
])
def test_generated_authored_values_are_not_literals(name, body, quote):
    assert not generated.only_literals(markers.wrap(name, body), quote)


@pytest.mark.parametrize("field", ["title", "description", "lesson-title", "materials"])
@pytest.mark.parametrize("ambiguous", [False, True])
def test_copied_text_routes_only_to_unique_source(setup, field, ambiguous):
    ctx, task, page = setup
    repo, index, quote = ctx.notes_path, "wiki/m/index.md", "A munkafüzet 2-5. oldala."
    meta = {field: quote} if field in ("title", "description") else {
        "lessons": [{"title": quote} if field == "lesson-title" else {"materials": [quote]}]}
    safefs.write_text(repo, page, frontmatter.set_keys(safefs.read_text(repo, page), meta))
    if ambiguous:
        safefs.write_text(repo, "wiki/m/other.md", frontmatter.set_keys("", meta))
    safefs.write_text(repo, index, markers.wrap("notes", "# 📝 Jegyzetek\n\n" + quote))
    original = [{**finding(index), "quote": quote, "origin": "reader"}]
    kept, notes, pages = report.prepare(repo, original, [], [{"file": index, "verdict": "changes"}])
    assert kept[0]["file"] == (index if ambiguous else page)
    assert not notes and pages[0]["verdict"] == "changes"
    path = "docs/review/run.md"
    report.write(repo, path, kept, notes, "model", "base", "2026-10-04")
    item = relations.inventory(repo)["items"][path + "#R1"]
    assert item["status"] == "open" and item["file"] == kept[0]["file"]


def test_unattributable_value_stays_on_index_and_mixed_verdict_stays_changes(setup):
    ctx, _, page = setup
    safefs.write_text(ctx.notes_path, page, markers.wrap("chapters", "# 📘 Fejezetcím\n") +
                      markers.wrap("notes", "# 📝 Jegyzetek\n"))
    source = [{**finding(page), "quote": q} for q in ("Fejezetcím", "Jegyzetek")]
    kept, notes, pages = report.prepare(ctx.notes_path, source, [], [{"file": page, "verdict": "changes"}])
    assert kept == source[:1] and len(notes) == 1 and pages[0]["verdict"] == "changes"


def test_figure_caption_routes_to_binary_asset_without_text_read(setup):
    ctx, task, page = setup
    repo, asset = ctx.notes_path, "wiki/assets/a.png"
    safefs.write_bytes(repo, asset, b"\x89PNG\xff")
    safefs.write_text(repo, page, markers.wrap("figure-example", "![Alt](../assets/a.png)\n\nKépaláírás.\n"))
    saved = {"findings": [{**finding(page), "quote": "Képaláírás.", "origin": "reader"}],
             "notes": [], "pages": [{"file": page, "verdict": "changes", "key": "key", "model": "model"}],
             "receipts": {}}
    inspection._apply(ctx, task, saved)
    item = next(iter(relations.inventory(repo)["items"].values()))
    assert item["file"] == asset and item["status"] == "open"
    assert safefs.read_json(repo, verdicts.PATH)[0]["verdict"] == "changes"
    assert not task.get("reader_owner_notes")


def test_recheck_routed_value_cannot_upgrade_original_page(setup):
    from school_notes2.flows import recheck
    from school_notes2.reader import units
    from school_notes2.review import files
    ctx, task, page = setup
    repo, source, quote = ctx.notes_path, "wiki/m/source.md", "Forrásból másolt cím"
    text = safefs.read_text(repo, page) + markers.wrap("notes", "# 📝 Jegyzetek\n" + quote)
    safefs.write_text(repo, page, text)
    safefs.write_text(repo, source, frontmatter.set_keys("", {"title": quote}))
    path = "docs/review/run.md"
    report.write(repo, path, [{**finding(page), "origin": "reader"}], [], "model", "base", "2026-10-04")
    files.apply_closure(repo, "fix", [{"file": path, "item_id": "R1", "status": "fixed"}], [])
    verdicts.record(repo, [{"file": page, "verdict": "changes"}], {page: units.page_key(repo, page)}, "model", "date")
    hit = {"id": "H1", "file": page, "line": text[:text.index(quote)].count("\n") + 1}
    task.update(inspection_report=path, reader_pages=[{"file": page}])
    saved = {"receipts": {}, "units": [{"status": "reviewed", "model": "model", "hits": [hit],
             "items": [{"key": path + "#R1", "file": page}], "review": {
                 "items": [{"key": path + "#R1", "verdict": "ok", "answer": "Javítva."}],
                 "hits": [{"hit_id": "H1", "verdict": "hiba", "reason": "Címhiba."}], "owner_notes": []}}]}
    recheck._apply(ctx, task, saved)
    assert verdicts.valid(repo, page)["verdict"] == "changes"
    item = relations.inventory(repo)["items"][path + "#R2"]
    assert item["file"] == source and item["status"] == "open"
    assert not task.get("recheck_owner_notes")


def test_adjacent_fixed_source_parts_are_still_literals():
    text = markers.wrap("lesson-sources", "📎 Füzet: dátum nélküli óra\n")
    assert generated.only_literals(text, "📎 Füzet: ")
    assert not generated.only_literals(text, "📎 Füzet: dátum nélküli óra")
    assert not generated.only_literals(text, "dátum nélküli óra")
