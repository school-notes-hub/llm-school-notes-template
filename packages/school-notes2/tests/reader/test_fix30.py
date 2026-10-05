"""Only actual new-page gaps, material decisions and durable history need work."""

import pytest

from school_notes2.figures import infographics
from school_notes2.flows import fetch, steps, correction
from school_notes2.reader import new_pages, notices, notice_migration, verdicts
from school_notes2.state import safefs, phase
from school_notes2.wiki import frontmatter, markers
from .test_infographics29 import assignment
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


@pytest.mark.parametrize("added,required", [(29, False), (30, True)])
def test_material_decision_threshold_and_same_run_exemption(setup, added, required):
    ctx, task, page = setup
    text = frontmatter.set_keys("# Téma\n\n## Rész\n\n" + " ".join(f"s{n}" for n in range(96)), {"type": "topic"})
    safefs.write_text(ctx.notes_path, page, text)
    decision = {"infographic_decisions": [{"page": page, "reason": "Elég a szöveg."}]}
    infographics.record(ctx, task, decision)
    # Exactly 100 tokens including the two headings; replace 29 or 30 tokens.
    newer = text
    for n in range(added):
        newer = newer.replace(f"s{n} ", f"új{n} ")
    safefs.write_text(ctx.notes_path, page, newer)
    assert bool(infographics.needed(ctx.notes_path, [page], "next-run")) == required
    assert infographics.needed(ctx.notes_path, [page], task.run_id) == []
    safefs.write_text(ctx.notes_path, page, text.replace("## Rész", "## Másik"))
    assert infographics.needed(ctx.notes_path, [page], "next-run") == [page]


def test_package_decision_is_recorded_and_p4_does_not_ask_again(setup):
    ctx, task, page = setup
    supplied = assignment(ctx.notes_path, page)
    task.update(packages=[{"subject": "m"}])
    assert infographics.assigned(ctx.notes_path, {"mode": "cron", "packages": [{"subject": "m"}]}) == [page]
    infographics.record(ctx, task, {"infographic_decisions": [{"page": page, "reason": "Elég a szöveg."}]})
    task.update(correction_figures=[])
    root = task.dir / "correction"
    correction.snapshot(ctx.notes_path, root)
    child = correction.child_task(ctx, task, root, supplied["open_review_items"])
    safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "\n## Új szakasz\nMagyarázat.\n")
    assert fetch.fetch_json(child, 1, grade=9, repo=ctx.notes_path)["infographic_pages"] == []


def test_old_run_does_not_acquire_decision_requirement_on_retry(setup):
    ctx, task, page = setup
    supplied = assignment(ctx.notes_path, page)
    task.data["data"].pop("infographic_policy")
    task.update(mode="fix", open_review_items=supplied["open_review_items"])
    task = phase.load(task.dir)
    value = fetch.fetch_json(task, 1, grade=9, repo=ctx.notes_path)
    assert "infographic_pages" not in value
    assert not infographics.check(ctx.notes_path, {"status": "done"}, value)
    assert task.data["needs_owner"] is None


def test_migration_does_not_turn_authored_notice_text_into_a_new_block(setup):
    ctx, task, page = setup
    safefs.write_json(ctx.notes_path, new_pages.PATH, {page: task.run_id})
    safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "\n" + notices.PAGE)
    notice_migration.refresh(ctx.notes_path)
    assert not any(markers.is_notice(name) for _, _, name in markers.spans(safefs.read_text(ctx.notes_path, page)))


def test_malformed_topic_can_be_repaired_before_its_decision(setup):
    ctx, task, page = setup
    supplied = assignment(ctx.notes_path, page)
    task.update(mode="fix", open_review_items=supplied["open_review_items"])
    safefs.write_text(ctx.notes_path, page, "---\nbroken: [\n---\nTananyag.\n")
    assert fetch.fetch_json(task, 1, grade=9, repo=ctx.notes_path)["infographic_pages"] == []
    assert not infographics.check(ctx.notes_path, {"status": "done"}, supplied)


def test_migration_keeps_a_draft_topic_notice_even_where_the_old_page_notice_stood(setup):
    """A continuing topic is a real gap: its notice survives the remove-only refresh."""
    from school_notes2.wiki import drafts
    ctx, task, page = setup
    old = markers.wrap("pending", notices.PAGE)
    safefs.write_text(ctx.notes_path, page, f"---\ntype: topic\nstatus: draft\n---\n# Cím\n\n{old}\n\nTananyag.\n")
    notice_migration.refresh(ctx.notes_path)
    text = safefs.read_text(ctx.notes_path, page)
    assert drafts.NOTICE in text and notices.PAGE not in text
