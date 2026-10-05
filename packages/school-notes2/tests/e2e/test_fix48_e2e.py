"""Fix-48 end to end: the live 2.5.1 state of a fix run stopped in its third correction
round (Benedek `20261005-212528-7b15`) finishes under 2.6.0 – one full recheck, commit and
push – without applying the first round's closures again and without losing what the
rounds recorded."""

import json

from school_notes2.flows import fetch, handlers, run as run_flow, steps, writer
from school_notes2.reader import report as run_report
from school_notes2.review import files, relations
from school_notes2.state import phase, safefs
from school_notes2.state.files import write_json
from tests.e2e.test_kiss46_e2e import interrupted_run, no_discard
from tests.e2e.test_real_repo_probe import generated, image_stub, probe_world
from tests.e2e.test_run_e2e import show


def test_25x_fix_round_with_applied_closures_finishes_with_one_recheck(tmp_path, monkeypatch, local_origin):
    ctx, origin, drive, package = probe_world(tmp_path, monkeypatch, "benedek", None)
    drive.items[package]["parents"] = ["not-ready"]          # a fix run: no new material
    images = []
    monkeypatch.setattr(handlers.image_generate, "generate",
                        lambda settings, plan_id, note=None, **kw: generated(images, plan_id))
    from school_notes2.flows import finish
    monkeypatch.setattr(finish, "_build", lambda ctx, task, commit: {"commit": commit,
                                                                      "output": str(task.dir / "stub-build")})
    real = writer._call

    def fake(ctx, task, k, *args):
        assigned = fetch.fetch_json(task, k, grade=9, repo=ctx.notes_path)
        result = real(ctx, task, k, *args)
        image_stub(ctx, task, assigned.get("pending_figures", []), images)
        return result
    monkeypatch.setattr(writer, "_call", fake)
    # The writer's calls are done and saved (result-1..n.json); the content steps not yet.
    task = interrupted_run(ctx, monkeypatch, steps, "content_steps")
    assert task.get("mode") == "fix" and task.get("writing_k") == len(task.get("ranges")) + 1
    repo, listed = ctx.notes_path, task.get("open_review_items")
    first = writer.merge(writer.results(task))["review_closure"]
    keys = [c["file"] + "#" + c["item_id"] for c in first]
    assert len(keys) == 2 and {c["status"] for c in first} == {"fixed"}

    # 2.5.1, round 1: the content steps applied the result under `<run>-fix-a1-r1`; P5
    # accepted the first item and reopened the second.
    r1, r2 = task.run_id + "-fix-a1-r1", task.run_id + "-fix-a1-r2"
    written = files.apply_closure(repo, r1, first, listed, automatic=True).written
    written.append(run_report.reopen(repo, keys[1], "A magyarázat hiányos."))
    # Round 2 (receipt saved): the writer worked on the reopened item, P5 reopened it again.
    second = [{"file": first[1]["file"], "item_id": first[1]["item_id"], "status": "fixed"}]
    page = relations.inventory(repo)["items"][keys[1]]["file"]
    safefs.write_text(repo, page, safefs.read_text(repo, page) + "\nA második kör pontosítása.\n")
    written += files.apply_closure(repo, r2, second, [second[0]], automatic=True).written
    written.append(run_report.reopen(repo, keys[1], "Még mindig hiányos."))
    steps.record_tool_files(task, repo, sorted(set(written)))
    folder = task.dir / "attempt-1"
    write_json(folder / "correction-r2" / "receipt.json", {"status": "done", "result": {"status": "done"}})
    # Round 3 (no receipt): the writer edited a page, then asked a question; its child task
    # inherited the parent's tool files (review files, evidence) with older hashes.
    safefs.write_text(repo, page, safefs.read_text(repo, page) + "\nA harmadik kör szerkesztése.\n")
    child = phase.Task(folder / "correction-r3" / "writer", json.loads(json.dumps(task.data)))
    child.data["data"].update(ranges=[[0, 0], [0, 0]], writing_k=1, tool_writes={
        **{rel: "0" * 64 for rel in safefs.glob(repo, "docs/review", "docs/review/**/*.md")},
        "docs/evidence/pages/masik/tema.md": "0" * 64})
    child.dir.mkdir(parents=True)
    child.save()
    write_json(child.dir / "result-1.json", {"status": "question", "questions": [{"text": "Áthelyezhetem?"}]})
    reviews = {rel: safefs.read_text(repo, rel) for rel in sorted({k.rsplit("#", 1)[0] for k in keys})}
    task.set_phase("correcting", correction_round=3, review_complete=False)
    task.record_error("bad_work", "result-2.json is missing")
    assert task.data["needs_owner"] is None

    no_discard(monkeypatch)
    assert run_flow.run(ctx) == 0, ctx.cfg.log_path.read_text()[-3000:]
    done = phase.load(task.dir)
    assert done.phase == "done" and done.get("recheck_all") and done.get("closures_applied")
    assert f"Run-Id: {task.run_id}" in show(origin, "main")
    # Every change of the run was rechecked once against the base (P5).
    assert list((done.dir / "attempt-1" / "recheck").iterdir())
    # Nothing the rounds recorded is lost: both round sections stay, once, and no section of
    # the 2.6.0 run is added; the reopened item kept its two attempts, none came on top.
    for rel, old in reviews.items():
        text = show(origin, f"main:{rel}")
        assert text.count(f"## Végrehajtva ({r1})") == 1 and text.count(f"## Végrehajtva ({r2})") <= 1
        assert f"## Végrehajtva ({task.run_id})" not in text
        assert old.split("\n---\n", 1)[1] in text      # the body as the rounds left it
    items = relations.inventory(repo)["items"]
    assert items[keys[0]]["status"] == "fixed" and items[keys[0]]["repair_runs"] == [r1]
    assert items[keys[1]]["repair_runs"] == [r1, r2] and items[keys[1]]["repair_attempts"] == 2
    # The rounds' page edits (round 2 and the unfinished round 3) are committed.
    published = show(origin, f"main:{page}")
    assert "A második kör pontosítása." in published and "A harmadik kör szerkesztése." in published
    events = [json.loads(line) for line in ctx.cfg.log_path.read_text().splitlines()]
    assert any(e["action"] == "finish.closures_kept" for e in events)
    restored = [p for e in events if e["action"] == "writer.protected_restored" for p in e.get("pages", [])]
    assert not [p for p in restored if p.startswith("docs/")], restored
