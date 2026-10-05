"""Repair uses the real content/commit chain; the model and all remotes are local fakes."""

from school_notes2.flows import chat, repair, run, writer
from school_notes2.repair import queue
from school_notes2.state import phase, safefs
from tests.e2e.test_run_e2e import world, show


def pending_banner(ctx, page):
    from school_notes2.wiki import frontmatter
    text = safefs.read_text(ctx.notes_path, page)
    parsed = frontmatter.split(text)
    cut = len(text) - len(parsed.body)
    safefs.write_text(ctx.notes_path, page, text[:cut] + "\n<!-- image: header -->\n" + text[cut:])
    brief = {"id": "header", "page": page, "anchor": "Cím", "kind": "banner", "purpose": "Bevezetés",
             "must_show": [], "avoid_misreading": "Jól olvasható cím.", "taught_conventions": [],
             "text_complete_without_figure": True}
    safefs.write_json(ctx.notes_path, ".school-notes/figures/header.json", brief)
    safefs.write_json(ctx.notes_path, ".school-notes/figures/header/figure.json",
                      {"state": "failed", "reason": "Repair has no paid generation"})
    return [{k: brief[k] for k in ("id", "page", "kind")}]


def test_repair_trial_commits_only_locally_then_finish_resumes(world, monkeypatch):
    ctx, origin, drive, package = world
    before = show(origin, "main:wiki/proba/elso.md")
    parent = drive.items[package]["parents"][:]
    calls = []
    def write(ctx, task, k, *args):
        calls.append(k)
        fetch = safefs.read_json(ctx.notes_path, ".school-notes/fetch.json")
        assert fetch["mode"] == "repair" and fetch["pages"] == fetch["packages"] == []
        assert fetch["repair_targets"][0]["page"] == "wiki/proba/elso.md"
        safefs.write_text(ctx.notes_path, "wiki/proba/elso.md", before + "\nTovábbi tárgyi magyarázat.\n")
        safefs.write_text(ctx.notes_path, "wiki/log.md", "# Napló\n\n* **Update**: Javítás.\n")
        return {"status": "done", "owner_notes": ["Kihagyott lépés, indok, javaslat."],
                "figures": pending_banner(ctx, "wiki/proba/elso.md")}
    monkeypatch.setattr(writer, "_call", write)
    assert repair.repair(ctx, topic="wiki/proba/elso.md", no_push=True) == 0, ctx.cfg.log_path.read_text()[-3000:]
    task = phase.open_task(ctx.task_root(), ctx.name, "notes")
    assert task.phase == "committed" and task.get("mode") == "repair"
    assert show(origin, "main:wiki/proba/elso.md") == before
    assert drive.items[package]["parents"] == parent
    assert repair.repair(ctx, topic="wiki/proba/elso.md", no_push=True) == 0
    assert calls == [1]
    assert run.run(ctx) == 0  # Held trial cannot accidentally run new Drive work.
    assert drive.items[package]["parents"] == parent
    result = chat.session_finish(ctx)
    assert result["state"] == "done", result
    assert result["owner_notes"] == ["Kihagyott lépés, indok, javaslat."]
    assert "További tárgyi magyarázat." in show(origin, "main:wiki/proba/elso.md")
    assert calls == [1]


def test_queue_command_is_tool_only_and_persists_owner_priority_edits(world, monkeypatch):
    ctx, origin, _, _ = world
    def no_model(*args):
        raise AssertionError("queue building must not launch a model")
    monkeypatch.setattr(writer, "_call", no_model)
    assert repair.repair(ctx, build_queue=True) == 0, ctx.cfg.log_path.read_text()[-3000:]
    data = queue.load(ctx.notes_path)
    assert [i["page"] for i in data["items"]] == ["wiki/proba/elso.md"]
    data["items"][0]["status"] = "done"
    safefs.write_json(ctx.notes_path, queue.PATH, data)
    assert repair.repair(ctx, build_queue=True) == 1  # Only the tool may complete pages.
    assert phase.open_task(ctx.task_root(), ctx.name, "notes") is None
    data["items"][0]["status"] = "pending"
    data["items"][0]["priority"] = 1
    data["items"][0]["urgent"] = True
    safefs.write_json(ctx.notes_path, queue.PATH, data)
    assert repair.repair(ctx, build_queue=True) == 0, ctx.cfg.log_path.read_text()[-3000:]
    assert '"priority": 1' in show(origin, f"main:{queue.PATH}")
    assert '"urgent": true' in show(origin, f"main:{queue.PATH}")


def test_queue_no_push_finishes_real_commit_chain(world):
    ctx, origin, _, _ = world
    assert repair.repair(ctx, build_queue=True, no_push=True) == 0
    task = phase.open_task(ctx.task_root(), ctx.name, "notes")
    assert task.phase == "committed" and not show(origin, f"main:{queue.PATH}")
    assert chat.session_finish(ctx)["state"] == "done"
    assert show(origin, f"main:{queue.PATH}")


def test_direct_failed_no_push_handoff_finishes_without_queue(world, monkeypatch):
    from school_notes2.state.errors import BadWork
    ctx, origin, _, _ = world
    def bad(*args):
        raise BadWork("invalid repair")
    monkeypatch.setattr(writer, "_call", bad)
    for _ in range(2):
        assert repair.repair(ctx, topic="wiki/proba/elso.md", no_push=True) == 1
    assert repair.repair(ctx, topic="wiki/proba/elso.md", no_push=True) == 0
    task = phase.open_task(ctx.task_root(), ctx.name, "notes")
    assert task.phase == "committed" and task.get("skip_writer")
    assert not safefs.is_file(ctx.notes_path, queue.PATH)
    assert chat.session_finish(ctx)["state"] == "done"
    assert not show(origin, f"main:{queue.PATH}")
    assert "R1" in show(origin, f"main:{task.get('repair_owner_item')}")


def test_new_packages_precede_queue_and_next_run_repairs_one_item(world, monkeypatch):
    ctx, origin, _, _ = world
    assert repair.repair(ctx, build_queue=True) == 0
    original = writer._call
    invoked = []
    def write(ctx, task, k, *args):
        invoked.append(task.get("mode", task.mode))
        if task.get("mode") != "repair":
            return original(ctx, task, k, *args)
        rel = task.get("repair_topic")
        safefs.write_text(ctx.notes_path, rel, safefs.read_text(ctx.notes_path, rel) + "\nÚj magyarázat.\n")
        return {"status": "done", "figures": pending_banner(ctx, rel)}
    monkeypatch.setattr(writer, "_call", write)
    assert run.run(ctx) == 0, ctx.cfg.log_path.read_text()[-3000:]
    assert invoked == ["cron"]
    assert run.run(ctx) == 0, ctx.cfg.log_path.read_text()[-3000:]
    assert invoked == ["cron", "repair"]
    assert queue.load(ctx.notes_path)["items"][0]["status"] == "done"


def test_two_failed_repairs_archive_bad_work_and_commit_owner_handoff(world, monkeypatch):
    from school_notes2.state.errors import BadWork
    ctx, origin, _, _ = world
    assert repair.repair(ctx, build_queue=True) == 0
    original = show(origin, "main:wiki/proba/elso.md")
    def bad(ctx, task, k, *args):
        safefs.write_text(ctx.notes_path, "wiki/proba/elso.md", "# Elrontott tartalom\n")
        raise BadWork("invalid repair")
    monkeypatch.setattr(writer, "_call", bad)
    for _ in range(2):
        assert repair.repair(ctx, topic="wiki/proba/elso.md") == 1
    task = phase.open_task(ctx.task_root(), ctx.name, "notes")
    assert task.get("repair_failed") and task.phase == "moved"
    assert repair.repair(ctx, topic="wiki/proba/elso.md") == 0, ctx.cfg.log_path.read_text()[-3000:]
    assert phase.open_task(ctx.task_root(), ctx.name, "notes") is None
    assert show(origin, "main:wiki/proba/elso.md") == original
    assert queue.load(ctx.notes_path)["items"][0]["status"] == "owner"
    assert (ctx.cfg.root / "archive" / ctx.name / f"{task.run_id}.bundle").is_file()
