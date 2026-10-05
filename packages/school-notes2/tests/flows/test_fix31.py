from types import SimpleNamespace

import pytest

from school_notes2.flows import inspection_runtime, recheck
from school_notes2.state import phase, safefs
from school_notes2.wiki import lesson_log


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
    task = phase.create(tmp_path, "barna", "notes", "cron", "inspecting")
    task.update(mode="fix")
    page = "wiki/m/a.md"
    before = "---\ntype: topic\ngenerated: {at: yesterday}\n---\n# Téma\n\nÁllítás.\n"
    after = before.replace("yesterday", "today") + ("Másik állítás.\n" if author_change else "")
    safefs.write_text(repo, page, after)
    ctx = SimpleNamespace(notes_path=repo, log=None, name="barna", cfg=SimpleNamespace(state_dir=tmp_path / "state"))
    monkeypatch.setattr(recheck.steps, "base_reader", lambda *a: lambda p: before.encode())
    monkeypatch.setattr(recheck.inputs, "prepare", lambda *a, **kw: a[3].mkdir(parents=True))
    monkeypatch.setattr(inspection_runtime, "role", lambda *a: None)
    called = []
    monkeypatch.setattr(recheck.calls, "run", lambda *a, **kw: called.append(1) or {"status": "not_checked"})
    entry = recheck.check_page(ctx, task, view, page, [])
    assert len(called) == int(author_change)
    # Nothing to check is its own status; a failed call is `not_checked` (it holds the release).
    assert entry["status"] == ("not_checked" if author_change else "unchanged")
