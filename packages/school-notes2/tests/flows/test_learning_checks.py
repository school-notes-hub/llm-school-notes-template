"""Legacy pages through MCP check, finish and real local rebase generation (K-1/K-8)."""

import json
from datetime import date
from pathlib import Path

import pytest

from school_notes2 import config
from school_notes2.flows import context, finish, handlers, learning, setup, status, steps
from school_notes2.git import repos, workbranch
from school_notes2.state import phase
from school_notes2.state.errors import NeedsOwner
from school_notes2.wiki import drafts, frontmatter
from tests.conftest import make_origin
from tests.wiki.conftest import INDEX, ROOT, page

NOTE = "wiki/proba/2026-09-01-regi-jegyzet.md"
TOPIC = "wiki/proba/elso.md"
LEGACY = "\n# Átirat\n\nAz eredeti hosszú jegyzet.\n\n# Nyitott kérdések\n\n1. Melyik nap volt?\n"


@pytest.fixture(params=[("benedek", 9), ("barna", 10)], ids=["benedek", "barna"])
def learning_run(tmp_path, local_origin, request):
    learner, grade = request.param
    files = {
        "wiki/index.md": ROOT, "wiki/proba/index.md": INDEX, "wiki/log.md": "# Napló\n",
        TOPIC: page("type: topic\ntitle: Első\ndescription: Az első téma.\nchapter: alapok\norder: 10"),
        NOTE: page("type: lesson-notes\ntitle: Régi óra\ndescription: Az első téma.\nstatus: draft\n"
                   f"grade: {grade}\nlessons:\n"
                   "  - {date: '2026-09-01', title: Bevezetés, topics: [elso.md]}", LEGACY),
        "tools/subjects.json": json.dumps({"subjects": {"proba": {"name": "Próba", "emoji": "🧪"}}}),
        "publication/public.json": json.dumps({"version": 1, "mode": "public", "title": learner,
                                               "base": f"/{learner}/", "assets": []}),
    }
    origin = make_origin(tmp_path, files)
    cfg = config.parse({
        "root": str(tmp_path / "srv"), "secrets_dir": str(tmp_path / "secrets"),
        "email_to": "o@example.com", "git": {"name": "O", "email": "o@example.com"},
        "release_dir": str(Path(__file__).resolve().parents[4]),
        "students": {learner: {"repo": str(origin), "repo_key": "/nonexistent",
                               "site_repo": str(origin), "site_key": "/nonexistent",
                               "drive_root": f"drive-{learner}", "grade": grade}},
        "roles": {"writer": {"harness": "codex", "model": "fake", "effort": "high", "timeout_s": 60},
                  "reviewer": {"harness": "claude-review", "model": "fake", "effort": "high",
                               "timeout_s": 60}},
    })
    ctx = context.make(cfg, learner, console=False)
    setup.setup(ctx)
    task = phase.create(ctx.task_root(), learner, "notes", "interactive", "prepared")
    wt = ctx.worktree("notes")
    base = repos.rev(wt, "refs/remotes/origin/main")
    workbranch.start(wt, task.run_id, base, interactive=True)
    workbranch.reset_workdir(ctx.notes_path)
    task.update(base=base, ranges=[[0, 0]], packages=[], pages=[], learning_date="2026-09-16")
    return ctx, task


@pytest.mark.parametrize("mode", ["cron", "interactive"])
def test_legacy_log_check_finish_and_rebase_regeneration(learning_run, monkeypatch, mode):
    ctx, task = learning_run
    task.data["mode"] = mode
    task.update(skip_writer=True)
    original = (ctx.notes_path / NOTE).read_bytes()
    topic = ctx.notes_path / TOPIC
    topic.write_text(topic.read_text() + "\nÚj magyarázat.\n")
    for _ in range(2):
        answer = handlers.build(ctx, task.dir).check()
        assert answer["ok"], answer
    task.reload()
    assert NOTE not in steps.llm_snapshot(ctx, task)
    assert "📎 Füzet: 2026. 09. 01." in (ctx.notes_path / NOTE).read_text()
    assert drafts.NOTICE in (ctx.notes_path / NOTE).read_text()
    assert steps._llm_hash(NOTE, original) == steps._llm_hash(NOTE, (ctx.notes_path / NOTE).read_bytes())

    # Concurrent local upstream commit forces finish's actual rebase/regenerate path.
    other = ctx.worktree("review")
    upstream_page = "wiki/proba/masik.md"
    (other.work_tree / upstream_page).write_text(page(
        "type: topic\ntitle: Másik\ndescription: Másik téma.\nchapter: alapok\norder: 20\nstatus: draft"))
    other.run("add", "wiki")
    other.run("commit", "-qm", "upstream topic")
    other.run("push", "origin", "HEAD:main")
    regenerated = []
    real_regenerate = steps.regenerate
    def regenerate(ctx_, task_):
        real_regenerate(ctx_, task_)
        regenerated.append(task_.get("base"))
        assert drafts.NOTICE in (ctx_.notes_path / upstream_page).read_text()
        assert NOTE not in steps.llm_snapshot(ctx_, task_)
    monkeypatch.setattr(steps, "regenerate", regenerate)
    monkeypatch.setattr(finish, "_build", lambda c, t, commit: {"commit": commit})
    assert finish.finish(ctx, task, notify_owner_items=lambda _: None) == "done"
    assert len(regenerated) == 1
    assert steps._llm_hash(NOTE, original) == steps._llm_hash(NOTE, (ctx.notes_path / NOTE).read_bytes())
    manifest = json.loads((ctx.notes_path / "publication/public.json").read_text())
    assert manifest["title"] == ctx.name and manifest["base"] == f"/{ctx.name}/"
    assert frontmatter.split((ctx.notes_path / NOTE).read_text()).meta["grade"] == ctx.student.grade
    assert all("decisions" not in entry and "draft_tracking" not in entry for entry in manifest["pages"])


def test_legacy_log_author_edit_still_requires_new_form(learning_run):
    ctx, task = learning_run
    note = ctx.notes_path / NOTE
    note.write_text(note.read_text() + "\nÚj tartalom.\n")
    answer = handlers.check(ctx, task)
    assert not answer["ok"]
    assert any("lesson log needs" in p["message"] for p in answer["problems"])
    with pytest.raises(steps.CheckFailed):
        steps.regenerate(ctx, task)


@pytest.mark.parametrize("invalid", ["yaml", "decisions", "date", "materials", "draft_tracking"])
@pytest.mark.parametrize("entrypoint", [handlers.check, steps.content_steps, steps.regenerate])
@pytest.mark.parametrize("edit_prose", [False, True])
def test_old_metadata_errors_need_owner(learning_run, invalid, entrypoint, edit_prose):
    ctx, task = learning_run
    task.data["mode"] = "cron"
    # Emulate metadata already present in the base, not a writer change.
    wt = ctx.worktree("notes")
    text = (ctx.notes_path / NOTE).read_text()
    if invalid == "yaml":
        text = "---\nprivate: [PRIVATE_VALUE\n---\n"
    elif invalid in ("decisions", "draft_tracking"):
        text = frontmatter.set_keys(text, {invalid: "broken"})
    else:
        lessons = frontmatter.split(text).meta["lessons"]
        lessons[0][invalid] = "broken"
        text = frontmatter.set_keys(text, {"lessons": lessons})
    (ctx.notes_path / NOTE).write_text(text)
    wt.run("add", "wiki")
    wt.run("commit", "-qm", "legacy metadata")
    task.update(base=wt.out("rev-parse", "HEAD").strip())
    if edit_prose:
        (ctx.notes_path / NOTE).write_text(text + "\nÚj magyarázat.\n")
    with pytest.raises(NeedsOwner) as failure:
        entrypoint(ctx, task)
    assert NOTE in str(failure.value)
    assert "PRIVATE_VALUE" not in str(failure.value)
    assert task.data["llm_failures"] == 0


def test_new_metadata_errors_return_to_writer(learning_run):
    ctx, task = learning_run
    new = "wiki/proba/uj.md"
    (ctx.notes_path / new).write_text("---\nprivate: [PRIVATE_VALUE\n---\n")
    answer = handlers.check(ctx, task)
    assert not answer["ok"]
    assert any(p["file"] == new and "YAML" in p["message"] for p in answer["problems"])
    assert "PRIVATE_VALUE" not in str(answer)


def test_draft_warning_date_is_pinned_and_status_is_repo_wide(learning_run, monkeypatch):
    ctx, task = learning_run
    topic = ctx.notes_path / TOPIC
    old = frontmatter.set_keys(topic.read_text(), {"status": "draft"})
    old = drafts.update(old, drafts.lesson_keys(ctx.notes_path)[TOPIC], date(2026, 9, 1))
    topic.write_text(old)
    wt = ctx.worktree("notes")
    wt.run("add", "wiki")
    wt.run("commit", "-qm", "old draft")
    task.update(base=wt.out("rev-parse", "HEAD").strip())
    assert not handlers.check(ctx, task)["problems"]
    topic.write_text(old + "\nBővebb magyarázat.\n")
    class Tomorrow(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 17)
    monkeypatch.setattr(learning, "date", Tomorrow)
    monkeypatch.setattr(status, "date", Tomorrow)
    assert TOPIC in [p["file"] for p in status.summary(ctx)["drafts"]["warnings"]]
    task.update(learning_date="2026-09-15")
    assert not handlers.check(ctx, task)["problems"]  # pinned at exactly 14 days
    task.update(learning_date="2026-09-16")
    found = handlers.check(ctx, task)
    assert [(p["file"], p["severity"]) for p in found["problems"]] == [(TOPIC, "warning")]


def test_new_error_on_previously_invalid_page_returns_to_writer(learning_run):
    ctx, task = learning_run
    note = ctx.notes_path / NOTE
    original = note.read_text()
    lessons = frontmatter.split(original).meta["lessons"]
    lessons[0]["date"] = "broken"
    note.write_text(frontmatter.set_keys(original, {"lessons": lessons}))
    wt = ctx.worktree("notes")
    wt.run("add", "wiki")
    wt.run("commit", "-qm", "legacy invalid date")
    task.update(base=wt.out("rev-parse", "HEAD").strip())
    lessons[0]["date"] = "2026-09-01"
    lessons[0]["materials"] = "broken"
    note.write_text(frontmatter.set_keys(original, {"lessons": lessons}) + "\nÚj magyarázat.\n")
    answer = handlers.check(ctx, task)
    assert not answer["ok"]
    assert any("materials" in p["message"] for p in answer["problems"])


def test_existing_yaml_error_with_interactive_prose_edit_needs_owner(learning_run):
    ctx, task = learning_run
    note = ctx.notes_path / NOTE
    note.write_text("---\nprivate: [PRIVATE_VALUE\n---\n")
    wt = ctx.worktree("notes")
    wt.run("add", "wiki")
    wt.run("commit", "-qm", "legacy invalid YAML")
    task.update(base=wt.out("rev-parse", "HEAD").strip())
    note.write_text(note.read_text() + "\nÚj magyarázat.\n")
    with pytest.raises(NeedsOwner):
        steps.content_steps(ctx, task)
