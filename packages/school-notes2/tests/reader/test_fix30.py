"""Only actual new-page gaps, material decisions and durable history need work."""

import pytest

from school_notes2.flows import steps
from school_notes2.reader import new_pages, notices, notice_migration, verdicts
from school_notes2.state import safefs, phase
from school_notes2.wiki import markers
from .test_notice_regressions import accept


def test_home_index_info_and_v1_topic_never_get_page_notices(setup):
    ctx, task, page = setup
    pages = [page, "wiki/index.md", "wiki/m/index.md", "wiki/about.md"]
    for path, kind in zip(pages, ["topic", "index", "index", "info"]):
        safefs.write_text(ctx.notes_path, path, f"---\ntype: {kind}\n---\n# Cím\n\nTananyag.\n")
    new_pages.record(ctx, task)  # The fixture's topic already existed in the base.
    assert not safefs.read_json(ctx.notes_path, new_pages.PATH, {})
    notices.refresh(ctx.notes_path, pages)
    notice_migration.refresh(ctx.notes_path)
    assert sum(safefs.read_text(ctx.notes_path, p).count("⏳") for p in pages) == 0
    # Even an erroneous origin entry cannot turn a non-reader page into a reader page.
    safefs.write_json(ctx.notes_path, new_pages.PATH, {p: task.run_id for p in pages[1:]})
    notices.refresh(ctx.notes_path, pages)
    assert sum(safefs.read_text(ctx.notes_path, p).count("⏳") for p in pages) == 0


@pytest.mark.parametrize("boundary", ["before", "after"])
@pytest.mark.parametrize("kind", ["topic", "lesson-notes", "summary", "review"])
def test_new_writer_page_origin_survives_crash_and_review(setup, monkeypatch, boundary, kind):
    ctx, task, _ = setup
    page = "wiki/m/new.md"
    safefs.write_text(ctx.notes_path, page, f"---\ntitle: Új\ntype: {kind}\n---\n# Új\n\nTananyag.\n")
    monkeypatch.setattr(steps, "llm_snapshot", lambda *a: {page: "new"})
    write, fired = safefs.write_text, []
    def crash(root, path, text, *args, **kw):
        if path == new_pages.PATH and not fired:
            fired.append(True)
            if boundary == "after":
                write(root, path, text, *args, **kw)
            raise RuntimeError("crash")
        return write(root, path, text, *args, **kw)
    monkeypatch.setattr(safefs, "write_text", crash)
    with pytest.raises(RuntimeError, match="crash"):
        new_pages.record(ctx, task)
    task = phase.load(task.dir)
    new_pages.record(ctx, task)
    notices.refresh(ctx.notes_path, [page])
    assert notices.PAGE in safefs.read_text(ctx.notes_path, page)
    accept(ctx.notes_path, page)
    notices.refresh(ctx.notes_path, [page])
    assert "⏳" not in safefs.read_text(ctx.notes_path, page)
    safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "\nFrissítés.\n")
    verdicts.invalidate(ctx.notes_path)
    notices.refresh(ctx.notes_path, [page])
    assert "⏳" not in safefs.read_text(ctx.notes_path, page)


def test_migration_never_adds_even_a_new_page_notice(setup):
    ctx, task, page = setup
    safefs.write_json(ctx.notes_path, new_pages.PATH, {page: task.run_id})
    notice_migration.refresh(ctx.notes_path)
    assert "⏳" not in safefs.read_text(ctx.notes_path, page)


def test_missing_key_and_deleted_reader_history_are_tolerated(setup):
    ctx, _, page = setup
    records = [{"role": role, "file": path} for role in ("reader", "reader-history")
               for path in (page, "wiki/m/deleted.md")]
    safefs.write_json(ctx.notes_path, verdicts.PATH, records)
    assert verdicts.valid(ctx.notes_path, page) is None
    verdicts.rekeyed(ctx.notes_path)
    verdicts.invalidate(ctx.notes_path)
    notice_migration.refresh(ctx.notes_path)
    saved = safefs.read_json(ctx.notes_path, verdicts.PATH)
    assert all(r["file"] == page for r in saved)
    assert verdicts.ever_reviewed(ctx.notes_path, page)


def test_migration_does_not_turn_authored_notice_text_into_a_new_block(setup):
    ctx, task, page = setup
    safefs.write_json(ctx.notes_path, new_pages.PATH, {page: task.run_id})
    safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "\n" + notices.PAGE)
    notice_migration.refresh(ctx.notes_path)
    assert not any(markers.is_notice(name) for _, _, name in markers.spans(safefs.read_text(ctx.notes_path, page)))


def test_migration_keeps_a_draft_topic_notice_even_where_the_old_page_notice_stood(setup):
    """A continuing topic is a real gap: its notice survives the remove-only refresh."""
    from school_notes2.wiki import drafts
    ctx, task, page = setup
    old = markers.wrap("pending", notices.PAGE)
    safefs.write_text(ctx.notes_path, page, f"---\ntype: topic\nstatus: draft\n---\n# Cím\n\n{old}\n\nTananyag.\n")
    notice_migration.refresh(ctx.notes_path)
    text = safefs.read_text(ctx.notes_path, page)
    assert drafts.NOTICE in text and notices.PAGE not in text
