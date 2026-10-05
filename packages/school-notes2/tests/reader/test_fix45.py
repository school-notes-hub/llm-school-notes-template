"""Writer freedom, exact protection and durable continuation (fix-45/T-095)."""

import pytest

from school_notes2.flows import (call_scope, correction, correction_calls, correction_round,
                                 fix_scope, inspection, protected, recheck, run, steps, writer)
from school_notes2.reader import calls
from school_notes2.review import files, relations
from school_notes2.state import phase, safefs
from school_notes2.wiki import anchors, check, markers
from .test_phases import finding, install_reader


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("mode", ["fix", "repair", "run", "interactive"])
def test_lesson_can_add_missing_topic_section_and_p5_judges_it(setup, monkeypatch, learner, mode):
    ctx, task, topic = setup
    ctx.name = learner
    lesson = "wiki/m/2026-10-05-ora-jegyzet.md"
    safefs.write_text(ctx.notes_path, lesson, "---\ntype: lesson-notes\nlessons: []\n---\n# Óra\n")
    path = files.write_review(ctx.notes_path, "2026-10-05", {"verdict": "changes", "findings": [
        {**finding(lesson), "id": "R1"}]}, "fake", "a", "b").relative_to(ctx.notes_path).as_posix()
    root = task.dir / "fix-before"
    correction.snapshot(ctx.notes_path, root)
    task.update(mode=mode, correction_before=str(root / "before"),
                correction_result={"status": "done", "review_closure": [
                    {"file": path, "item_id": "R1", "status": "fixed"}]})
    if mode == "interactive":
        task.data["mode"] = mode
    text = safefs.read_text(ctx.notes_path, topic) + "\n## Új rész\n\nTanító magyarázat.\n"
    safefs.write_text(ctx.notes_path, topic, text)
    safefs.write_text(ctx.notes_path, lesson, safefs.read_text(ctx.notes_path, lesson) +
                      "\n# Mit tanultunk ezen az órán\n\n- [Új rész](topic.md#új-rész)\n")
    fix_scope.recover(ctx, task)
    assert safefs.read_text(ctx.notes_path, topic) == text
    assert not check.check_links(ctx.notes_path, lesson, safefs.read_text(ctx.notes_path, lesson))
    assert "új-rész" in anchors.collect(ctx.notes_path, [topic])[topic]
    monkeypatch.setattr(steps, "llm_snapshot", lambda *a: {topic: "changed", lesson: "changed"})
    # The P5 test is about routing; metadata prerequisites have their own tests.
    from school_notes2.flows import learning
    monkeypatch.setattr(learning, "validate", lambda *a: None)
    seen = []
    def review(repo, view, folder, stage, assigned, role, **kw):
        pages = safefs.read_json(folder, "in/pages.json")
        seen.extend(p["file"] for p in pages)
        if pages[0]["file"] == topic:
            assert "Új rész" in str(pages[0]["changed_lines"])
            assert assigned["items"] == []
        return {"status": "not_checked"}
    monkeypatch.setattr(calls, "run", review)
    recheck.run(ctx, task)
    assert seen == sorted([lesson, topic])
    recheck.run(ctx, phase.load(task.dir))
    assert seen == sorted([lesson, topic])


@pytest.mark.parametrize("boundary", ["write", "resume"])
def test_protected_parts_restore_without_touching_author_text(setup, monkeypatch, boundary):
    ctx, task, page = setup
    report = "docs/review/protected.md"
    safefs.write_text(ctx.notes_path, report, "Original review.\n")
    source = "sources/m/original.txt"
    safefs.write_text(ctx.notes_path, source, "Original source.\n")
    before = safefs.read_text(ctx.notes_path, page) + markers.wrap("topics", "Tool-owned.\n")
    safefs.write_text(ctx.notes_path, page, before)
    steps.record_tool_files(task, ctx.notes_path, [page, report, source])
    author = before.replace("Tool-owned.", "Bad tool edit.") + "\nSzerzői javítás.\n"
    safefs.write_text(ctx.notes_path, page, author)
    safefs.write_text(ctx.notes_path, report, "Bad review edit.\n")
    safefs.write_text(ctx.notes_path, source, "Bad source edit.\n")
    original = safefs.write_bytes
    stopped = []
    def crash(root, rel, data):
        original(root, rel, data)
        if root == ctx.notes_path and not stopped:
            stopped.append(True)
            raise KeyboardInterrupt
    if boundary == "write":
        monkeypatch.setattr(safefs, "write_bytes", crash)
        with pytest.raises(KeyboardInterrupt):
            protected.restore(ctx, task)
        monkeypatch.setattr(safefs, "write_bytes", original)
    protected.restore(ctx, phase.load(task.dir))
    assert safefs.read_text(ctx.notes_path, page) == before + "\nSzerzői javítás.\n"
    assert safefs.read_text(ctx.notes_path, report) == "Original review.\n"
    assert safefs.read_text(ctx.notes_path, source) == "Original source.\n"
    assert protected.restore(ctx, task) == []


@pytest.mark.parametrize("skip_writer", [False, True])
@pytest.mark.parametrize("persistent", [False, True, "tool-file"])
def test_late_p4_check_stays_in_child_through_run_advance(setup, monkeypatch, skip_writer, persistent):
    ctx, task, page = setup
    files.write_review(ctx.notes_path, "2026-10-05", {"verdict": "changes", "findings": [
        {**finding(page), "id": "R1"}]}, "fake", "a", "b")
    task.set_phase("correcting", mode="fix", skip_writer=skip_writer)
    safefs.write_json(task.dir, "result-1.json", {"status": "done"})
    monkeypatch.setattr(writer, "write_inputs", lambda *a: None)
    monkeypatch.setattr(writer, "_check_call", lambda *a: None)
    monkeypatch.setattr(steps, "guard_step", lambda *a: None)
    from school_notes2.wiki import check_result
    monkeypatch.setattr(check_result, "check_result", lambda *a, **kw: [])  # Result bookkeeping has own tests.
    invoked, checked = [], []
    def invoke(ctx, child, k, *args):
        assert child.run_id != task.run_id
        invoked.append(child.run_id)
        safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "Megmarad.\n")
        return {"status": "done", "review_closure": [
            {"file": i["file"], "item_id": i["item_id"], "status": "fixed"}
            for i in child.get("open_review_items")]}
    monkeypatch.setattr(writer, "_invoke", invoke)
    def check_changed(ctx, child, **kw):
        checked.append(1)
        if persistent == "tool-file":  # No writer call owns it: no SnError, no continuation.
            raise steps.CheckFailed([check.item(".school-notes/figures/f1/figure.json", None, "bad candidate")])
        if persistent or len(checked) == 1:
            raise steps.CheckFailed([check.item(page, 1, "Late link error")])
    monkeypatch.setattr(steps, "check_changed", check_changed)
    from school_notes2.flows import finish
    monkeypatch.setattr(finish, "finish", lambda ctx, parent, **kw: correction.run(ctx, parent))
    run.advance(ctx, task)
    assert task.phase == "correcting" and task.get("attempt") == 1
    assert safefs.read_json(task.dir, "result-1.json") == {"status": "done"}
    assert len(invoked) == (1 if persistent == "tool-file" else 2)
    assert safefs.read_text(ctx.notes_path, page).count("Megmarad.") == len(invoked)
    if persistent == "tool-file":
        assert task.get("machine_problems")[0]["file"].startswith(".school-notes/figures/")
    elif persistent:
        assert any(i.get("origin") == "check" for i in relations.inventory(ctx.notes_path)["items"].values())
    assert not task.get("correction_rolled_back")


def test_unassigned_recheck_error_gets_chain_and_next_assignment(setup, monkeypatch):
    ctx, task, page = setup
    other = "wiki/n/extra.md"
    safefs.write_text(ctx.notes_path, other, "# Új rész\n\nHibás állítás.\n")
    path = files.write_review(ctx.notes_path, "2026-10-05", {"verdict": "changes", "findings": [
        {**finding(page), "id": "R1", "chain": 2}]}, "fake", "a", "b").relative_to(ctx.notes_path).as_posix()
    closure = {"file": path, "item_id": "R1", "status": "fixed"}
    task.update(correction_result={"status": "done", "review_closure": [closure]}, inspection_report=path)
    files.apply_closure(ctx.notes_path, task.run_id, [closure], [{"file": path, "item_id": "R1"}])
    monkeypatch.setattr(steps, "llm_snapshot", lambda *a: {page: "changed", other: "changed"})
    def review(repo, view, folder, stage, assigned, role, **kw):
        judged = safefs.read_json(folder, "in/pages.json")[0]["file"]
        findings = [{"id": "F-1", "severity": "hiba", "file": other, "quote": "Hibás állítás.",
                     "problem": "Hibás.", "category": "pontosság", "suggestion": "Javítsd.",
                     "relates_to": None, "item_key": None}] if judged == other else []
        return {"status": "reviewed", "model": "fake/high", "review": {"items": [
            {"key": i["key"], "severity": "javaslat", "verdict": "ok", "answer": "Jó."}
            for i in assigned["items"]], "hits": [], "findings": findings, "owner_notes": []}}
    monkeypatch.setattr(calls, "run", review)
    recheck.run(ctx, task)
    extra = [i for i in relations.inventory(ctx.notes_path)["items"].values() if i.get("file") == other]
    assert len(extra) == 1 and extra[0]["origin"] == "recheck" and extra[0]["chain"] == 3
    known = relations.inventory(ctx.notes_path)["items"]
    assert any(known[v["key"]].get("file") == other for v in correction.assigned(ctx, task))
    recheck.run(ctx, phase.load(task.dir))
    assert len([i for i in relations.inventory(ctx.notes_path)["items"].values() if i.get("file") == other]) == 1


def test_check_does_not_rewrite_author_bytes(tmp_path):
    path = "wiki/a.md"
    data = b"# Title\r\n\r\n[Link](topic.md#anchor)"
    safefs.write_bytes(tmp_path, path, data)
    check.check_files(tmp_path, [path])
    assert safefs.read_bytes(tmp_path, path) == data


def test_package_reader_and_nightly_material_include_extended_old_page(setup, monkeypatch):
    from school_notes2.flows import finish
    import json
    ctx, task, page = setup
    previous, backlog = "wiki/n/old.md", "wiki/o/backlog.md"
    for path in (previous, backlog):
        safefs.write_text(ctx.notes_path, path, "---\ntype: topic\ntitle: Téma\n---\n# Téma\n")
    monkeypatch.setattr(steps, "llm_snapshot", lambda *a: {page: "new", previous: "extended"})
    inspection.prepare(ctx, task)
    assert {p for u in task.get("inspection_units") for p in u["pages"]} == {page, previous}
    # P4's unrelated backlog edits do not widen the package's material trailer.
    monkeypatch.setattr(steps, "llm_snapshot", lambda *a: {page: "new", previous: "extended", backlog: "p4"})
    monkeypatch.setattr(finish, "_log_title", lambda *a: "Új anyag")
    line = next(s for s in finish.message(ctx, task).splitlines() if s.startswith("School-Notes-Material: "))
    assert json.loads(line.split(": ", 1)[1]) == [page, previous]


@pytest.mark.parametrize("boundary", ["journal", "continue"])
def test_machine_failure_continuation_keeps_work_after_crash(setup, monkeypatch, boundary):
    ctx, task, page = setup
    task.set_phase("writing", mode="run", calls=[], writing_k=1)
    monkeypatch.setattr(writer, "write_inputs", lambda *a: None)
    invoked = []
    def invoke(ctx, task, k, *args):
        invoked.append(1)
        if len(invoked) == 2:
            assert "Első munka." in safefs.read_text(ctx.notes_path, page)
            assert safefs.read_json(ctx.notes_path, ".school-notes/check.json")[0]["message"] == "Gépi hiba"
        safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "Első munka.\n")
        return {"status": "done"}
    monkeypatch.setattr(writer, "_invoke", invoke)
    def check_call(*args):
        if len(invoked) == 1:
            raise steps.CheckFailed([check.item(page, 1, "Gépi hiba")])
    monkeypatch.setattr(writer, "_check_call", check_call)
    original = safefs.write_json
    stopped = []
    def crash(root, rel, value):
        original(root, rel, value)
        if rel == "failure.json" and not stopped and bool(value.get("restored")) == (boundary == "continue"):
            stopped.append(1)
            raise KeyboardInterrupt
    monkeypatch.setattr(safefs, "write_json", crash)
    with pytest.raises(KeyboardInterrupt):
        writer.run_ranges(ctx, task, {})
    writer.run_ranges(ctx, phase.load(task.dir), {})
    assert len(invoked) == 2
    assert safefs.read_text(ctx.notes_path, page).count("Első munka.") == 2


@pytest.mark.parametrize("invalid", ["json", "secret"])
def test_only_unusable_call_rolls_back_and_log_names_it(setup, monkeypatch, invalid):
    from school_notes2.state.errors import BadWork
    import json
    ctx, task, page = setup
    task.set_phase("writing", mode="run", calls=[], writing_k=1)
    before = safefs.read_text(ctx.notes_path, page)
    monkeypatch.setattr(writer, "write_inputs", lambda *a: None)
    invoked = []
    def invoke(ctx, task, k, *args):
        invoked.append(1)
        assert safefs.read_text(ctx.notes_path, page) == before
        safefs.write_text(ctx.notes_path, page, before + "Unusable output.\n")
        if invalid == "json":
            safefs.write_text(ctx.notes_path, ".school-notes/result.json", "{broken")
            raise BadWork("invalid result.json")
        return {"status": "done"}
    monkeypatch.setattr(writer, "_invoke", invoke)
    def reject(*args):
        raise steps.CheckFailed([check.item(page, 1, f"{check.SECRET_MESSAGE} 'client_secret'")])
    monkeypatch.setattr(writer, "_check_call", reject)
    assert writer.run_ranges(ctx, task, {}) == "done"
    assert len(invoked) == 2 and safefs.read_text(ctx.notes_path, page) == before
    events = [json.loads(line) for line in ctx.log.main.read_text().splitlines()]
    assert any(e["action"] == "writer.unusable_rollback" for e in events)


def test_secret_and_machine_path_messages_differ():
    assert check.check_secrets("wiki/a.md", "client_secret\n")[0]["message"].startswith(check.SECRET_MESSAGE + " ")
    assert not check.check_secrets("wiki/a.md", "/home/x\n")[0]["message"].startswith(check.SECRET_MESSAGE + " ")


@pytest.mark.parametrize("failure", ["machine-path", "exit", "error"])
def test_usable_failed_call_keeps_work_and_run_continues(setup, monkeypatch, failure):
    """A valid result.json never rolls back or stops the run: the call's items stay open."""
    from school_notes2.state.errors import BadWork
    from school_notes2.flows import policy
    ctx, task, page = setup
    task.set_phase("writing", mode="fix", calls=[{"subject": "m", "open_review_items": [
        {"file": "docs/review/x.md", "item_id": "R1"}]}], writing_k=1)
    before = safefs.read_text(ctx.notes_path, page)
    monkeypatch.setattr(writer, "write_inputs", lambda *a: None)
    invoked = []
    def invoke(ctx, task, k, *args):
        invoked.append(1)
        safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "Kész munka.\n")
        safefs.write_json(ctx.notes_path, ".school-notes/result.json", {"status": "done"})
        if failure == "exit":
            raise BadWork("the LLM exited with 1 after changing files")
        if failure == "error":
            raise ValueError("unexpected")
        return {"status": "done"}
    monkeypatch.setattr(writer, "_invoke", invoke)
    def reject(*args):
        raise steps.CheckFailed([check.item(page, 1, "forbidden secret or machine-path pattern '/home/'")])
    monkeypatch.setattr(writer, "_check_call", reject)
    assert writer.run_ranges(ctx, task, {}) == "done"
    assert len(invoked) == 2
    assert safefs.read_text(ctx.notes_path, page) == before + "Kész munka.\n" * 2
    result = safefs.read_json(task.dir, "result-1.json")
    if failure == "machine-path":  # The checked candidate is kept; its errors become items.
        assert result == {"status": "done"}
        assert any(i.get("origin") == "check" for i in relations.inventory(ctx.notes_path)["items"].values())
    else:
        assert [c["status"] for c in result["review_closure"]] == ["open"]
    assert task.data["llm_failures"] == 0 and not task.data["needs_owner"]
    policy.on_success(task)


@pytest.mark.parametrize("case", ["continue", "not-wiki", "cap", "interactive"])
def test_remaining_machine_errors_continue_next_run_without_discard(setup, monkeypatch, case):
    """After the in-run rounds: no publication, no rollback, no owner stop while a writer
    round can still fix the wiki; the next cron run continues the same task."""
    from school_notes2.flows import review_phases
    from school_notes2.state.errors import NeedsOwner
    ctx, task, page = setup
    work = safefs.read_text(ctx.notes_path, page) + "Kész munka.\n"
    safefs.write_text(ctx.notes_path, page, work)
    target = page if case != "not-wiki" else ".school-notes/result.json"
    task.set_phase("review_ready", correction_round=review_phases.MAX_ROUNDS if case == "cap" else 3,
                   machine_problems=[check.item(target, 2, "Gépi hiba")])
    if case == "interactive":
        task.data["mode"] = "interactive"
    monkeypatch.setattr(steps, "guard_step", lambda *a: None)
    def still_failing(*a, **kw):
        raise steps.CheckFailed([check.item(target, 2, "Gépi hiba")])
    monkeypatch.setattr(steps, "check_changed", still_failing)
    finalized = []
    monkeypatch.setattr(review_phases, "finalize", lambda *a, **kw: finalized.append(1))
    if case == "continue":
        assert review_phases.advance(ctx, task, lambda _: None) == {"state": "machine_errors", "round": 4}
        assert task.phase == "correcting" and task.get("correction_round") == 4
        assert not task.data["needs_owner"]
        known = relations.inventory(ctx.notes_path)["items"]
        keys = {k for k, i in known.items() if i.get("origin") == "check"}
        assert len(keys) == 1 and known[next(iter(keys))]["file"] == page
        assert keys <= {i["key"] for i in correction.assigned(ctx, task)}
        # The same error at another line is the same item (no item growth across runs).
        task.set_phase("review_ready", correction_round=4)
        def moved(*a, **kw):
            raise steps.CheckFailed([check.item(page, 5, "Gépi hiba")])
        monkeypatch.setattr(steps, "check_changed", moved)
        review_phases.advance(ctx, task, lambda _: None)
        assert len([i for i in relations.inventory(ctx.notes_path)["items"].values()
                    if i.get("origin") == "check"]) == 1
    elif case == "interactive":
        with pytest.raises(steps.CheckFailed):
            review_phases.advance(ctx, task, lambda _: None)
    else:
        with pytest.raises(NeedsOwner):
            review_phases.advance(ctx, task, lambda _: None)
    assert safefs.read_text(ctx.notes_path, page) == work and not finalized


def test_removed_block_is_not_replaced_by_the_tool_and_guard_names_it(setup, tmp_path):
    from school_notes2.wiki import guard
    ctx, task, page = setup
    block = markers.wrap("topics", "Tool-owned.\n")
    base = "# Téma\n\n" + block + "\n## Rész\n\nSzöveg.\n"
    current = "# Téma\n\n## Rész\n\nSzerzői szöveg.\n"
    # The tool never guesses a position for a removed block.
    assert protected.restore_parts(current.encode(), base.encode()) == current.encode()
    # A kept block gets its bytes back in the writer's position, author text untouched.
    moved = "# Téma\n\n## Rész\n\nSzerzői szöveg.\n\n" + block.replace("Tool-owned.", "Edited.")
    assert protected.restore_parts(moved.encode(), base.encode()) == (
        "# Téma\n\n## Rész\n\nSzerzői szöveg.\n\n" + block).encode()
    g = guard.GuardInput(tmp_path, [], lambda rel: base.encode())
    found = guard.check_parts(page, current.encode(), g)
    assert len(found) == 1 and not found[0].owner
    assert "'topics' was removed" in found[0].message and block.rstrip("\n") in found[0].message


def test_machine_error_incident_says_work_is_kept():
    from school_notes2.notify import incidents
    text = incidents.wording("tester", "bad_work", "machine-errors")
    assert "a munka megmaradt" in text and "nincs teendőd" in text


def test_infographic_decision_on_unassigned_topic_is_accepted(setup):
    from school_notes2.figures import infographics
    ctx, task, page = setup
    fetch = {"mode": "fix", "open_review_items": [], "pending_figures": []}
    ok = {"status": "done", "infographic_decisions": [{"page": page, "reason": "A szöveg elég."}]}
    assert infographics.check(ctx.notes_path, ok, fetch) == []
    bad = {"status": "done", "infographic_decisions": [{"page": "wiki/index.md", "reason": "x"}]}
    assert [i["message"] for i in infographics.check(ctx.notes_path, bad, fetch)] == [
        "infographic_decisions: wiki/index.md is not a topic page"]
