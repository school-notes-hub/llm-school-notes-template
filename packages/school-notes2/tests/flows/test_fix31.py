from types import SimpleNamespace

import pytest

from school_notes2.flows import inspection_runtime, recheck
from school_notes2.repair import check
from school_notes2.state import phase, safefs
from school_notes2.wiki import frontmatter, lesson_log, markers
from tests.flows.test_repair import context


@pytest.mark.parametrize("count, plural, valid", [(1, False, True), (1, True, False), (2, True, True), (2, False, True)])
def test_lesson_log_title_agrees_with_lesson_count(tmp_path, count, plural, valid):
    safefs.write_text(tmp_path, "wiki/m/a.md", "---\ntype: topic\n---\n# A\n")
    title = lesson_log.PLURAL_TITLE if plural else lesson_log.TITLE
    meta = {"lessons": [{"topics": ["a.md"]}] * count}
    body = f"# {title}\n\n" + "* [Tárgy](a.md#szakasz)\n" * 3
    assert (not lesson_log.form_problems(tmp_path, "wiki/m/log.md", body, meta)) == valid


@pytest.mark.parametrize("author_change", [False, True])
def test_empty_recheck_skips_machine_metadata_only(tmp_path, monkeypatch, author_change):
    repo, view = tmp_path / "repo", tmp_path / "view"
    repo.mkdir()
    task = phase.create(tmp_path, "barna", "notes", "cron", "rechecking")
    task.update(mode="fix")
    page = "wiki/m/a.md"
    before = "---\ntype: topic\ngenerated: {at: yesterday}\n---\n# Téma\n\nÁllítás.\n"
    after = before.replace("yesterday", "today") + ("Másik állítás.\n" if author_change else "")
    (task.dir / "fix-before").mkdir()
    safefs.write_text(task.dir / "fix-before", "before/" + page, before)
    safefs.write_text(repo, page, after)
    ctx = SimpleNamespace(notes_path=repo, log=None)
    monkeypatch.setattr(recheck.inputs, "prepare", lambda *a, **kw: a[3].mkdir(parents=True))
    monkeypatch.setattr(inspection_runtime, "role", lambda *a: None)
    called = []
    monkeypatch.setattr(recheck.calls, "run", lambda *a, **kw: called.append(1) or {"status": "not_checked"})
    recheck.check_unit(ctx, task, view, {"topic": page, "pages": [page]}, [])
    assert len(called) == int(author_change)


def test_repair_rebased_notices_separators_do_not_become_author_edits(tmp_path, log, monkeypatch):
    ctx, topic, _ = context(tmp_path, log, monkeypatch)
    rel = "wiki/m/log.md"
    old = "---\ntype: lesson-notes\nlessons: [{topics: [a.md]}]\n---\n# Óra\n\nTárgy [A](a.md#old).\n"
    upstream = old.replace("Tárgy", markers.wrap("pending", "⏳ Ellenőrzés\n") + "\nTárgy")
    # A concurrent night changed only a generated block and its insertion spacing.
    rebased = old.replace("#old", "#new").replace("\n\nTárgy", "\n\n\nTárgy")
    calls = []
    def git(*args, **kw):
        calls.append(args[1])
        return SimpleNamespace(returncode=0, stdout=upstream.encode())
    ctx.worktree = lambda _: SimpleNamespace(run=git)
    safefs.write_text(ctx.notes_path, rel, rebased)
    task = phase.create(tmp_path, "barna", "notes", "cron", "committed")
    task.update(mode="repair", base="new-upstream", preparation_base="old-upstream",
                repair_targets=[{"page": topic, "kind": "topic", "related": [rel]}])
    assert not check.problems(ctx, task, [rel])
    assert calls == ["new-upstream:" + rel]
    # Restart after rebase uses the same baseline and still detects real prose edits.
    assert not check.problems(ctx, phase.load(task.dir), [rel])
    safefs.write_text(ctx.notes_path, rel, rebased.replace("Tárgy", "Átírt tárgy"))
    assert any("only link" in i["message"] for i in check.problems(ctx, task, [rel]))


def test_notice_normalization_never_allows_other_paragraph_or_code_edits():
    before = "# Óra\n\n" + markers.wrap("pending", "⏳ Készül\n") + "\nElső.\n\nMásodik.\n"
    good = "# Óra\n\n\nElső.\n\nMásodik.\n"
    assert check._related_equal(before, good)
    assert not check._related_equal(before, good.replace("Első.\n\nMásodik.", "Első.\nMásodik."))
    code = "\n```python\na = '''első\n\nmásodik'''\n```\n"
    assert not check._related_equal(before + code, good + code.replace("\n\nmásodik", "\nmásodik"))
