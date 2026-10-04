"""Legacy cleanup follows the real generation order and survives interrupted migration."""

import hashlib

import pytest

from school_notes2.flows import learning, steps
from school_notes2.reader import notices, units, verdicts
from school_notes2.review import files, relations
from school_notes2.state import phase, safefs
from school_notes2.wiki import frontmatter, generate, lesson_log, markers
from .test_notice_regressions import BANNER, META, legacy_items


def nested(block):
    notice = markers.wrap("pending-section-old", notices.SECTION)
    body = BANNER if block == "figure-banner" else "# 📝 Jegyzetek\n\n* [Egy óra](lesson.md) - Leírás.\n"
    first, rest = body.split("\n", 1)
    return META + markers.wrap(block, first + "\n\n" + notice + "\n" + notice + "\n" + rest) + "\nSzerzői szöveg.\n"


@pytest.mark.parametrize("block", ["notes", "figure-banner"])
@pytest.mark.parametrize("verdict", ["ok", "changes"])
def test_matching_legacy_keys_survive_cleanup_once(setup, block, verdict):
    ctx, task, page = setup
    repo = ctx.notes_path
    safefs.write_text(repo, page, nested(block))
    old = units.page_key(repo, page, legacy_notices=True)
    # Frozen outputs of e3338e9^, independent of the compatibility implementation.
    expected = {"notes": "ab36d702ba3a00525792e9c55327822666f8e5e30743171a5d562aa0cae4cd99",
                "figure-banner": "b78ab84a16221a25c67f1cdf275d5dd8014a2d2b539a63df5e3981f115deb70f"}
    assert old == expected[block]
    assert old != units.page_key(repo, page)
    verdicts.record(repo, [{"file": page, "verdict": verdict}], {page: old}, "model", "old-date")
    learning.migrate(ctx, task)
    before = safefs.read_bytes(repo, verdicts.PATH)
    assert verdicts.valid(repo, page)["verdict"] == verdict
    assert verdicts.valid(repo, page)["at"] == "old-date"
    assert verdicts.PATH in task.get("tool_writes")
    safefs.write_text(repo, page, markers.clean_nested_notices(safefs.read_text(repo, page)))
    learning.migrate(ctx, phase.load(task.dir))
    assert safefs.read_bytes(repo, verdicts.PATH) == before
    assert verdicts.invalidate(repo) == []
    notices.refresh(repo, [page])
    assert notices.PAGE not in safefs.read_text(repo, page)


def test_stale_keys_and_figure_records_are_not_upgraded(setup):
    ctx, task, page = setup
    repo = ctx.notes_path
    safefs.write_text(repo, page, nested("notes"))
    old = units.page_key(repo, page, legacy_notices=True)
    verdicts.record(repo, [{"file": page, "verdict": "ok"}], {page: old}, "model", "date")
    records = safefs.read_json(repo, verdicts.PATH)
    records.append({"role": "figure-review", "file": page, "key": old})
    safefs.write_json(repo, verdicts.PATH, records)
    safefs.write_text(repo, page, safefs.read_text(repo, page) + "Megváltozott tananyag.\n")
    before = safefs.read_bytes(repo, verdicts.PATH)
    learning.migrate(ctx, task)
    assert safefs.read_bytes(repo, verdicts.PATH) == before
    assert verdicts.valid(repo, page) is None


@pytest.mark.parametrize("boundary", ["before", "after"])
@pytest.mark.parametrize("target", [verdicts.PATH, "docs/review/legacy.md"])
def test_migrations_resume_and_preserve_nonliteral_items(setup, monkeypatch, boundary, target):
    ctx, task, page = setup
    repo = ctx.notes_path
    safefs.write_text(repo, page, nested("notes"))
    legacy_items(repo, page, ["Jegyzetek", "Leírás.", "Szerzői szöveg."])
    verdicts.record(repo, [{"file": page, "verdict": "ok"}],
                    {page: units.page_key(repo, page, legacy_notices=True)}, "model", "date")
    write = safefs.write_text
    fired = []
    def crash(root, path, text, **kwargs):
        if path != target or fired:
            return write(root, path, text, **kwargs)
        fired.append(path)
        if boundary == "after":
            write(root, path, text, **kwargs)
        raise RuntimeError("migration interrupted")
    monkeypatch.setattr(safefs, "write_text", crash)
    with pytest.raises(RuntimeError, match="migration interrupted"):
        learning.migrate(ctx, task)
    task = phase.load(task.dir)
    learning.migrate(ctx, task)
    known = relations.inventory(repo)["items"]
    assert [item["status"] for item in known.values()] == ["owner", "open", "open"]
    assert known["docs/review/legacy.md#R1"]["tool_reason"]
    assert len(files.open_items(repo, "cron")) == 2
    before = {rel: safefs.read_bytes(repo, rel) for rel in (verdicts.PATH, "docs/review/legacy.md")}
    learning.migrate(ctx, phase.load(task.dir))
    for rel, data in before.items():
        assert safefs.read_bytes(repo, rel) == data
        assert task.get("tool_writes")[rel] == hashlib.sha256(data).hexdigest()


def test_vm_structure_indexes_then_notices_are_valid_single_and_byte_stable(setup):
    ctx, task, _ = setup
    repo, index = ctx.notes_path, "wiki/m/index.md"
    safefs.write_text(repo, "wiki/m/lesson.md", frontmatter.set_keys("# Óra\n", {
        "type": "lesson-notes", "title": "Egy óra", "description": "Leírás.", "lessons": []}))
    text = nested("notes") + markers.wrap("chapters", "") + markers.wrap("lessons", "")
    safefs.write_text(repo, index, text)
    old = units.page_key(repo, index, legacy_notices=True)
    verdicts.record(repo, [{"file": index, "verdict": "ok"}], {index: old}, "model", "date")
    learning.migrate(ctx, task)
    generate.write_indexes(repo)
    notices.refresh(repo, [index])
    result = safefs.read_text(repo, index)
    markers.check(result)
    assert result.count("* [Egy óra](lesson.md)") == 1
    assert steps._llm_hash(index, text.encode()) == steps._llm_hash(index, result.encode())
    assert verdicts.valid(repo, index) is not None
    assert generate.write_indexes(repo) == []
    assert notices.refresh(repo, [index]) == []
    assert safefs.read_text(repo, index) == result


def test_lesson_and_any_replacement_clean_nested_notices():
    text = nested("figure-banner") + markers.wrap("lesson-sources", "Old\n")
    result = lesson_log.after_header(text, "lesson-sources", "📎 Füzet: dátum nélküli óra\n")
    markers.check(result)
    assert "Old" not in result and notices.SECTION not in result
    assert "📎 Füzet:" in result
    result = markers.replace(text, "lesson-sources", "New")
    markers.check(result)
    assert "New" in result


def test_notice_adjacent_to_outer_marker_keeps_author_key(setup):
    ctx, _, page = setup
    text = META + markers.wrap("notes", markers.wrap("pending", notices.PAGE) + "List\n") + "Author\n"
    safefs.write_text(ctx.notes_path, page, text)
    key = units.page_key(ctx.notes_path, page)
    notices.refresh(ctx.notes_path, [page])
    markers.check(safefs.read_text(ctx.notes_path, page))
    assert units.page_key(ctx.notes_path, page) == key
