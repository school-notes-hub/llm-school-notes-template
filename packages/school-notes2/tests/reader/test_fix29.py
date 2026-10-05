"""Only real gaps are visible, including after interrupted whole-wiki migration."""

import json
from types import SimpleNamespace

import pytest

from school_notes2.flows import review_phases
from school_notes2.reader import notice_migration, notices, units, verdicts
from school_notes2.state import phase, safefs
from school_notes2.wiki import author, frontmatter, markers
from .test_notice_regressions import accept, legacy_items


@pytest.mark.parametrize("status", ["open", "owner"])
@pytest.mark.parametrize("origin", ["reader", "nightly", "recheck", "list", "figure"])
@pytest.mark.parametrize("quote", ["A test lefelé gyorsul.", "hiányzó idézet", "Téma"])
def test_review_items_never_create_notices(setup, status, origin, quote):
    ctx, _, page = setup
    repo = ctx.notes_path
    accept(repo, page)
    legacy_items(repo, page, [quote], status=status, unlocated=True)
    path = "docs/review/legacy.md"
    text = safefs.read_text(repo, path)
    meta = frontmatter.split(text).meta
    meta["item_details"]["R1"].update(origin=origin, round=2)
    safefs.write_text(repo, path, frontmatter.set_keys(text, meta))
    notices.refresh(repo, [page])
    assert "⏳" not in safefs.read_text(repo, page)


@pytest.mark.parametrize("boundary", ["before", "after"])
@pytest.mark.parametrize("target", ["wiki/m/old.md", notice_migration.PATH, verdicts.PATH])
def test_whole_wiki_refresh_resumes_and_runs_once(setup, monkeypatch, boundary, target):
    ctx, task, page = setup
    repo = ctx.notes_path
    old, draft = "wiki/m/old.md", "wiki/m/draft.md"
    original = safefs.read_text(repo, page)
    for path in (old, draft):
        safefs.write_text(repo, path, original)
    safefs.write_text(repo, draft, frontmatter.set_keys(original, {"status": "draft"}))
    accept(repo, draft)
    history = [{"role": "reader", "file": old, "key": "old-content", "verdict": "changes"}]
    git = SimpleNamespace(out=lambda *a: "abc\n", run=lambda *a, **kw:
                          SimpleNamespace(returncode=0, stdout=json.dumps(history).encode()))
    # Simulate a legacy verdict already deleted by not-ok finalization.
    safefs.write_text(repo, ".git", "gitdir: unused\n")
    ctx.worktree = lambda _: git
    for path in (page, old, draft):
        safefs.write_text(repo, path, safefs.read_text(repo, path) + "\n" +
                          markers.wrap("pending-section-old", notices.SECTION) + "\n")
    keys = {p: units.page_key(repo, p) for p in (page, old, draft)}
    parts = {p: author.part(safefs.read_text(repo, p)) for p in keys}
    write, fired = safefs.write_text, []
    def crash(root, path, text, **kwargs):
        if path == target and not fired:
            fired.append(path)
            if boundary == "after":
                write(root, path, text, **kwargs)
            raise RuntimeError("crash")
        return write(root, path, text, **kwargs)
    monkeypatch.setattr(safefs, "write_text", crash)
    with pytest.raises(RuntimeError, match="crash"):
        review_phases.refresh_notices(ctx, task, [])
    task = phase.load(task.dir)
    review_phases.refresh_notices(ctx, task, [])
    assert "⏳" not in safefs.read_text(repo, page)
    assert "⏳" not in safefs.read_text(repo, old)
    # A continuing topic is a real gap (owner, 2026-10-05): only its own notice stays.
    from school_notes2.wiki import drafts
    assert safefs.read_text(repo, draft).count("⏳") == 1
    assert drafts.NOTICE in safefs.read_text(repo, draft)
    assert verdicts.valid(repo, old) is None
    assert verdicts.valid(repo, draft) is not None
    for path in keys:
        assert units.page_key(repo, path) == keys[path]
        assert author.part(safefs.read_text(repo, path)) == parts[path]
        assert notices.SECTION not in safefs.read_text(repo, path)
    before = {p: safefs.read_bytes(repo, p) for p in safefs.walk_files(repo, "wiki")}
    git.out = lambda *a: pytest.fail("history must only be read once")
    assert review_phases.refresh_notices(ctx, task, []) == []
    assert before == {p: safefs.read_bytes(repo, p) for p in before}
    assert notice_migration.PATH in task.get("tool_writes")
