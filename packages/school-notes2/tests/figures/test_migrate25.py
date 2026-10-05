"""Read-only operator preview and actionable recovery instructions."""

import pytest

from school_notes2.figures import migrate_operation as operation, migrate_pending as migration, pending
from school_notes2.git import repos
from school_notes2.state import safefs
from school_notes2.state.files import write_json
from tests.figures.test_migrate_operation24 import ctx, tree


@pytest.mark.parametrize("kind", ["tracked", "staged", "untracked"])
def test_dirty_preview_lists_paths_without_writes(ctx, tmp_path, capsys, kind):
    name = "wiki/index.md" if kind != "untracked" else "untracked file.txt"
    safefs.write_text(ctx.notes_path, name, "Changed\n")
    if kind == "staged":
        ctx.worktree("notes").run("add", name)
    before = tree(tmp_path)
    assert operation.run(ctx, dry_run=True) == 2
    error = capsys.readouterr().err
    assert "not clean" in error and name in error
    assert tree(tmp_path) == before


def test_main_moved_names_both_receipts_and_rerun(ctx):
    wt = ctx.worktree("notes")
    base = repos.rev(wt, "origin/main")
    commit = wt.out("commit-tree", wt.out("rev-parse", "HEAD^{tree}").strip(), "-p", base,
                    "-m", "Saved migration").strip()
    with pytest.raises(ValueError) as caught:
        operation.publish(ctx, wt, {"base": "0" * 40, "commit": commit}, base, True)
    message = str(caught.value)
    state = (ctx.cfg.state_dir / ctx.name).resolve()
    assert str(state / migration.RECEIPT) in message
    assert str(state / operation.JOURNAL) in message
    assert "remove" in message and "rerun the migration command" in message


def test_main_moved_before_commit_uses_common_recovery(ctx):
    state = ctx.cfg.state_dir / ctx.name
    write_json(state / operation.JOURNAL, {"base": "0" * 40})
    with pytest.raises(ValueError) as caught:
        operation.execute(ctx, False)
    assert str(caught.value) == f"migration input changed: origin/main; {migration.recovery(state)}"


@pytest.mark.parametrize("stage", ["check", "apply"])
def test_input_changed_names_receipt_directory(ctx, stage):
    state = ctx.cfg.state_dir / ctx.name
    saved = {"files": {"wiki/index.md": {"before": "old", "after": "new"}}}
    with pytest.raises(ValueError) as caught:
        if stage == "check":
            migration.check_current(ctx.notes_path, saved, state)
        else:
            migration.apply(ctx.notes_path, {}, saved, state)
    assert str(state.resolve() / migration.RECEIPT) in str(caught.value)
    assert str(state.resolve() / operation.JOURNAL) in str(caught.value)


def test_ledger_preview_uses_exact_ids_and_never_writes(ctx, tmp_path, capsys):
    from school_notes2.figures.migrate_ledger import preview
    import json
    page = "wiki/m/topic.md"
    entries = []
    for fid, kind in [("napoleon-fejlec", "banner"), ("szechenyi-banner", "banner"),
                      ("unreviewed", "infographic"), ("drawing", "figure")]:
        brief = {"id": fid, "page": page, "kind": kind, "anchor": "Topic", "purpose": "Topic",
            "must_show": [], "avoid_misreading": "Topic", "taught_conventions": [], "text_complete_without_figure": True}
        entries.append({"commission": brief, "status": "pending", "runs": 2,
                        "run_ids": ["a", "b"], "owner_required": False, "defects": []})
    safefs.write_json(ctx.notes_path, pending.PATH, entries)
    settings = ctx.image_settings()
    jobs = {"learner-napoleon-banner": 2, "learner-szechenyi-banner": 3, "learner-unreviewed": 3}
    write_json(settings.state_dir / "ledger.json", {"jobs": {
        key: {"attempts": [{"state": "generated" if key.endswith("unreviewed") else "rejected"} for _ in range(n)]}
        for key, n in jobs.items()}})
    before = tree(tmp_path)
    from dataclasses import replace
    from school_notes2.log import Log
    rows = preview(ctx, replace(ctx.worktree("notes"), log=Log(None, console=False)))
    assert tree(tmp_path) == before
    assert rows == sorted(rows, key=lambda r: r["id"])
    indexed = {r["id"]: r for r in rows}
    napoleon = indexed["napoleon-fejlec"]
    assert napoleon["job_id"] == "learner-napoleon-fejlec" and napoleon["paid_attempts_used"] == 0
    assert napoleon["assignable_after_migration"]
    assert indexed["szechenyi-banner"]["paid_attempts_used"] == 3
    assert indexed["szechenyi-banner"]["owner_required"]
    assert not indexed["szechenyi-banner"]["assignable_after_migration"]
    assert indexed["unreviewed"]["free_recheck"] and indexed["unreviewed"]["assignable_after_migration"]
    assert indexed["drawing"]["job_id"] is None
    # The public dry-run returns the same rows from a clean committed snapshot.
    wt = ctx.worktree("notes")
    wt.run("add", pending.PATH)
    wt.run("commit", "-m", "Pending queue")
    before = tree(tmp_path)
    assert operation.run(ctx, dry_run=True) == 0
    assert json.loads(capsys.readouterr().out)["ledger"] == rows
    assert tree(tmp_path) == before
