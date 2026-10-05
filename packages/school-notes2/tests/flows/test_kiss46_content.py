"""Fix-46 content rules on a real Git worktree: what still protects the learner (Maradjon),
what became a warning, and what the tool restores mechanically instead of failing."""

import pytest

from school_notes2.flows import handlers, protected, steps
from school_notes2.review import files, relations
from school_notes2.state.errors import NeedsOwner
from school_notes2.state.files import write_json
from school_notes2.wiki import check, frontmatter, markers
from tests.flows.test_learning_checks import NOTE, TOPIC, learning_run  # noqa: F401


def commit(ctx, task, message="base"):
    wt = ctx.worktree("notes")
    wt.run("add", "-A")
    wt.run("commit", "-qm", message)
    task.update(base=wt.out("rev-parse", "HEAD").strip())


def cron(task):
    task.data["mode"] = "cron"
    task.save()


def errors(ctx, task):
    return [i for i in steps.check_items(ctx, task) if i.get("severity", "error") == "error"]


def append(ctx, rel, text):
    path = ctx.notes_path / rel
    path.write_text(path.read_text() + text)


@pytest.mark.parametrize("text,blocking", [
    ("\nKulcs: ghp_" + "a" * 36 + "\n", True),               # secret
    ("\n<<<<<<< HEAD\n", True),                               # conflict marker
    ("\n<!-- school-notes:generated notes -->\n", True),     # broken tool block markers
    ("\n$$ x^2\n", False),                                    # math that cannot render
    ("\n[Hiányzó](nincs-ilyen.md)\n", False),                 # broken link
])
def test_what_still_protects_the_learner_is_an_error(learning_run, text, blocking):
    """Maradjon: secrets, conflicts, tool markers, math and broken links stay errors."""
    ctx, task = learning_run
    cron(task)
    append(ctx, TOPIC, text)
    found = errors(ctx, task)
    assert found and bool(check.blocking(found)) is blocking


@pytest.mark.parametrize("text", [
    "\n„Magyar idézet” – gondolatjel.\n",                       # #5 typography
    "\nEgy útvonal: https://example.test/home/x és /srv/adat\n",  # #15 machine paths: output gate only
    "\n# Nyitott kérdések\n\n* Kérdés horgony nélkül?\n",       # Fable 13 question form
    "\n📎 Kézzel írt forrásutaló.\n",                            # tool-rendered line
    "\n" + "Hosszú mondat. " * 3000 + "\n",                    # #5 40 KB
])
def test_rules_that_do_not_block_learning_are_never_errors(learning_run, text):
    ctx, task = learning_run
    cron(task)
    append(ctx, TOPIC, text)
    assert not errors(ctx, task)


def test_banner_and_infographic_and_order_need_nothing_on_a_text_edit(learning_run):
    """#6, Fable 4, #12: an edit on an existing page never requires a banner, an infographic
    decision or the old order."""
    ctx, task = learning_run
    cron(task)
    text = (ctx.notes_path / TOPIC).read_text().replace("![Fejléc](../assets/proba/header.webp)\n\n", "")
    (ctx.notes_path / TOPIC).write_text(frontmatter.set_keys(text, {"order": 99}) + "\nJavított mondat.\n")
    assert not errors(ctx, task)
    from school_notes2.wiki.check_result import check_result
    fetch = {"mode": "fix", "packages": [], "pages": [], "range": {"from": 0, "to": 0}}
    assert not check.errors(check_result(ctx.notes_path, {"status": "done"}, fetch, set()))


def test_old_error_never_blocks_and_never_becomes_an_item(learning_run):
    """#3, #14, A1: an error already in the base is a warning, also on an edited page."""
    ctx, task = learning_run
    cron(task)
    append(ctx, TOPIC, "\n[Régi](regi-hianyzo.md)\n")
    commit(ctx, task)
    append(ctx, TOPIC, "\nÚj, helyes mondat.\n")
    found = steps.check_items(ctx, task)
    old = [i for i in found if "regi-hianyzo" in i["message"]]
    assert old and all(i["severity"] == "warning" and i["kind"] == "inherited-check" for i in old)
    task.update(skip_writer=True)
    steps.content_steps(ctx, task)
    assert not relations.inventory(ctx.notes_path)["items"]


def test_remaining_error_becomes_an_item_and_the_work_is_applied(learning_run):
    """Point 1: after the writer's calls, a remaining error is an item; nothing is undone."""
    ctx, task = learning_run
    cron(task)
    task.update(skip_writer=True)
    append(ctx, TOPIC, "\nÚj tananyag.\n[Hiányzó](nincs-ilyen.md)\n")
    steps.content_steps(ctx, task)
    assert "Új tananyag." in (ctx.notes_path / TOPIC).read_text()
    items = relations.inventory(ctx.notes_path)["items"]
    assert [i["file"] for i in items.values()] == [TOPIC]
    assert task.get("content_problems")


def test_blocking_content_at_finish_stops_with_the_work_kept(learning_run):
    ctx, task = learning_run
    cron(task)
    task.update(skip_writer=True)
    append(ctx, TOPIC, "\nKulcs: ghp_" + "a" * 36 + "\n")
    with pytest.raises(NeedsOwner, match="work is kept"):
        steps.content_steps(ctx, task)
    assert "ghp_" in (ctx.notes_path / TOPIC).read_text()


def test_fixed_closure_without_a_text_change_stays_open(learning_run):
    """R6: a `fixed` closure is accepted only with a change on its page."""
    ctx, task = learning_run
    cron(task)
    report = files.write_review(ctx.notes_path, "2026-10-05", {"verdict": "changes", "findings": [
        {"severity": "hiba", "id": "R1", "file": TOPIC, "problem": "Hiba.", "relates_to": None},
        {"severity": "hiba", "id": "R2", "file": NOTE, "problem": "Hiba.", "relates_to": None}]}, "r", "a", "b")
    rel = report.relative_to(ctx.notes_path).as_posix()
    commit(ctx, task)
    listed = files.open_items(ctx.notes_path, "cron")
    task.update(mode="fix", open_review_items=listed, ranges=[[0, 0]])
    write_json(task.dir / "result-1.json", {"status": "done", "review_closure": [
        {"file": rel, "item_id": "R1", "status": "fixed"}, {"file": rel, "item_id": "R2", "status": "fixed"}]})
    append(ctx, TOPIC, "\nJavított mondat.\n")
    steps.content_steps(ctx, task)
    items = files.read_items(ctx.notes_path, ctx.notes_path / rel)
    assert items == {"R1": "fixed", "R2": "open"}
    assert any("without a text change" in d for d in task.get("dropped_result"))


def test_tool_bytes_are_restored_mechanically_never_an_error(learning_run):
    """Fable 16, 6b: edited machine keys and blocks come back from the tool's data, the
    cron writer's change of `decisions` is put back, a removed block is allowed, and a
    writer edit outside wiki/ is undone. The author's prose is never touched."""
    ctx, task = learning_run
    cron(task)
    decisions = [{"id": "nev", "claim": "Név", "answer": "Válasz", "by": "owner", "on": "2026-10-04"}]
    text = frontmatter.set_keys((ctx.notes_path / NOTE).read_text(), {"decisions": decisions})
    text = markers.at_fixed_place(text, "lesson-sources", "📎 Füzet: 2026. 09. 01.\n")
    (ctx.notes_path / NOTE).write_text(text)
    commit(ctx, task)
    edited = frontmatter.set_keys(text, {"decisions": [], "grade": 1})
    edited = edited.replace("📎 Füzet: 2026. 09. 01.", "📎 Átírva") + "\nSzerzői mondat.\n"
    (ctx.notes_path / NOTE).write_text(edited)
    review = ctx.notes_path / "docs/review/x.md"
    review.parent.mkdir(parents=True, exist_ok=True)
    review.write_text("Az író nem írhat ide.\n")
    restored = protected.restore(ctx, task)
    result = (ctx.notes_path / NOTE).read_text()
    assert frontmatter.split(result).meta["decisions"] == decisions
    assert "📎 Füzet: 2026. 09. 01." in result and "Szerzői mondat." in result
    assert NOTE in restored and not review.exists()
    steps.guard_step(ctx, task)  # nothing left for the writer
    (ctx.notes_path / NOTE).write_text(markers.remove(result, {"lesson-sources"}))
    steps.guard_step(ctx, task)  # a removed tool block is the writer's choice


def test_deleted_page_is_allowed_and_its_links_are_checked(learning_run):
    """#13: the writer may delete or rename; a link left to the old page is an error."""
    ctx, task = learning_run
    cron(task)
    append(ctx, NOTE, "\n[Tovább](elso.md)\n")
    commit(ctx, task)
    (ctx.notes_path / TOPIC).unlink()
    steps.guard_step(ctx, task)
    found = errors(ctx, task)
    assert any(i["file"] == NOTE and "elso.md" in i["message"] for i in found)


def test_mcp_check_has_no_decision_duty(learning_run):
    ctx, task = learning_run
    append(ctx, TOPIC, "\n„Idézet”.\n")
    answer = handlers.build(ctx, task.dir).check()
    assert answer["ok"]
    assert not any("decision" in p["message"] for p in answer["problems"])


def test_review_requests_travel_unchanged_in_the_commit(learning_run):
    """Point 5: the writer may ask for a targeted nightly check; the tool passes it on."""
    from school_notes2.flows import finish
    ctx, task = learning_run
    request = [{"page": TOPIC, "reason": "Új levezetés, kérlek nézd át."}]
    task.update(ranges=[[0, 0]])
    write_json(task.dir / "result-1.json", {"status": "done", "review_requests": request})
    message = finish.message(ctx, task)
    import json
    line = next(l for l in message.splitlines() if l.startswith("School-Notes-Review-Request: "))
    assert json.loads(line.split(": ", 1)[1]) == request


def test_path_guard_still_protects_a_dotfile_is_never_committed(learning_run):
    """Maradjon: a writer's dotfile under wiki/ is unusable output; cron stops before commit."""
    ctx, task = learning_run
    cron(task)
    task.update(skip_writer=True)
    (ctx.notes_path / "wiki/.gitattributes").write_text("* merge=union\n")
    with pytest.raises(steps.CheckFailed) as failed:
        steps.guard_step(ctx, task)
    assert check.blocking(failed.value.items)
    with pytest.raises(NeedsOwner):
        steps.content_steps(ctx, task)
