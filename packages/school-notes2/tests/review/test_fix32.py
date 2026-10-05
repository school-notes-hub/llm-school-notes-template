"""Owner 2026-10-05: three automatic repairs, durable across resume and migration."""

from types import SimpleNamespace

import pytest

from school_notes2.flows import correction, journal, learning
from school_notes2.reader import report
from school_notes2.review import files, relations, repair_migration, topic_result
from school_notes2.state import phase, safefs
from school_notes2.wiki import frontmatter

PAGE = "wiki/a/topic.md"


def finding(**extra):
    return {"id": "R1", "file": PAGE, "problem": "Hiba.", "quote": "Állítás.",
            "origin": "reader", "category": "tárgyi", "relates_to": None, "chain": 1, **extra}


def setup(repo):
    repo.mkdir(parents=True, exist_ok=True)
    safefs.write_text(repo, PAGE, "# Téma\n\nÁllítás.\n")
    path = files.write_review(repo, "2026-10-05", {"verdict": "changes", "findings": [finding()]}, "r", "a", "b")
    return path.relative_to(repo).as_posix()


def item(repo, rel):
    return relations.inventory(repo)["items"][rel + "#R1"]


@pytest.mark.parametrize("reader", [True, False])
@pytest.mark.parametrize("learner", ["benedek", "barna"])
def test_third_failed_repair_and_each_checkpoint_replay(tmp_path, reader, learner):
    repo = tmp_path / learner
    rel = setup(repo)
    for n in range(1, 4):
        listed = files.open_items(repo, "cron")
        assert listed[0]["chain"] == 1
        closure = {"file": rel, "item_id": "R1", "status": "fixed"}
        files.apply_closure(repo, f"fix-{n}", [closure], listed, automatic=True)
        before = safefs.read_bytes(repo, rel)
        files.apply_closure(repo, f"fix-{n}", [closure], listed, automatic=True)
        assert safefs.read_bytes(repo, rel) == before
        assert item(repo, rel)["status"] == "fixed"  # The third success is not an owner item.
        answer = {"key": rel + "#R1", "verdict": "not-ok", "answer": "Még hibás."}
        def reopen():
            if reader:
                report.reopen(repo, answer["key"], answer["answer"])
            else:
                topic_result.apply_item(repo, {"status": "fixed", "fix_commit": True}, answer)
        reopen()
        before = safefs.read_bytes(repo, rel)
        reopen()
        assert safefs.read_bytes(repo, rel) == before
        detail = item(repo, rel)
        assert detail["repair_attempts"] == n
        assert detail["repair_runs"] == [f"fix-{i}" for i in range(1, n + 1)]
        assert detail["status"] == ("owner" if n == 3 else "open")
    assert files.open_items(repo, "cron") == []


def test_only_assigned_items_count_and_related_findings_inherit(tmp_path):
    rel = setup(tmp_path)
    report.append(tmp_path, rel, [finding(problem="Másik hiba.")], [], "extra")
    listed = [{"file": rel, "item_id": "R1"}]
    for n in range(3):
        files.apply_closure(tmp_path, f"fix-{n}", [], listed, automatic=True)
    assert item(tmp_path, rel)["status"] == "owner"
    assert "repair_attempts" not in relations.details(safefs.read_text(tmp_path, rel), "R2")
    # A falsely closed item reappearing under a new ID retains its consumed budget.
    text = safefs.read_text(tmp_path, rel)
    safefs.write_text(tmp_path, rel, frontmatter.set_keys(text, {"items": {"R1": "fixed", "R2": "open"}}))
    new = files.write_review(tmp_path, "2026-10-06", {"verdict": "changes", "findings": [
        finding(relates_to=rel + "#R1")]}, "r", "b", "c").relative_to(tmp_path).as_posix()
    assert item(tmp_path, new)["status"] == "owner"
    assert item(tmp_path, new)["repair_attempts"] == 3


def test_decision_routes_immediately_but_question_reference_stays_pending(tmp_path):
    rel = setup(tmp_path)
    known = {"pages": {PAGE: {"decisions": ["d"], "questions": ["q"]}}, "items": {}}
    assert relations.route(finding(relates_to="d"), known) == ("owner", False)
    assert relations.route(finding(category="forrásellentmondás"), known) == ("owner", False)
    assert relations.route(finding(relates_to="q"), known) == ("pending", False)
    assert relations.route(finding(relates_to="unknown"), known) == ("open", True)
    assert item(tmp_path, rel)["status"] == "open"


def legacy(repo):
    rel = setup(repo)
    details = {f"R{n}": finding(id=f"R{n}", origin="figure", figure_id=f"fig-{n}") for n in range(1, 16)}
    details.update(R16=finding(), R17=finding(category="forrásellentmondás"),
                   R18=finding(origin="figure", figure_id="exhausted"),
                   R19=finding(repair_attempts=3, repair_runs=["a", "b", "c"]))
    text = frontmatter.set_keys(safefs.read_text(repo, rel), {
        "items": {key: "owner" for key in details}, "item_details": details, "repair_policy": 0})
    safefs.write_text(repo, rel, text)
    safefs.write_json(repo, "docs/figure-pending-migrations.json", {"version": "generated-headers-22"})
    safefs.write_json(repo, "docs/figure-pending.json", [
        {"commission": {"id": f"fig-{n}"}, "owner_required": False} for n in range(1, 16)])
    return rel


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("after_write", [False, True])
def test_migration_interrupted_write_resumes_once(tmp_path, monkeypatch, learner, after_write):
    repo = tmp_path / learner
    rel = legacy(repo)
    task = phase.create(tmp_path / "state", learner, "notes", "cron", "moved")
    ctx = SimpleNamespace(notes_path=repo)
    original = journal.safefs.write_text
    def crash(root, path, text):
        if after_write:
            original(root, path, text)
        raise KeyboardInterrupt()
    monkeypatch.setattr(journal.safefs, "write_text", crash)
    with pytest.raises(KeyboardInterrupt):
        learning.migrate(ctx, task)
    monkeypatch.setattr(journal.safefs, "write_text", original)
    learning.migrate(ctx, phase.load(task.dir))
    first = safefs.read_bytes(repo, rel)
    learning.migrate(ctx, phase.load(task.dir))
    assert safefs.read_bytes(repo, rel) == first
    assert not list(repair_migration.updates(repo))
    page = frontmatter.split(first.decode())
    for n in range(1, 16):
        assert page.meta["items"][f"R{n}"] == "settled"
        assert page.meta["item_details"][f"R{n}"]["migration_note"] == repair_migration.REASON
    assert page.meta["items"]["R16"] == "open"
    assert page.meta["item_details"]["R16"]["repair_attempts"] == 0
    assert all(page.meta["items"][k] == "owner" for k in ("R17", "R19"))
    assert page.meta["items"]["R18"] == "open"


def test_rollback_counts_once_after_restore_and_escalates(tmp_path):
    rel = setup(tmp_path)
    ctx = SimpleNamespace(notes_path=tmp_path)
    task = phase.create(tmp_path / "state", "one", "notes", "cron", "correcting")
    task.update(correction_items=files.open_items(tmp_path, "cron"))
    for n in range(3):
        task.update(attempt=n + 1)
        root = task.dir / str(n)
        correction.snapshot(tmp_path, root)
        saved = {"status": "rollback", "reason": "bad work"}
        correction.apply(ctx, task, root, saved)
        before = safefs.read_bytes(tmp_path, rel)
        correction.apply(ctx, phase.load(task.dir), root, saved)
        assert safefs.read_bytes(tmp_path, rel) == before
    assert item(tmp_path, rel)["repair_attempts"] == 3
    assert item(tmp_path, rel)["status"] == "owner"


def test_migration_alone_does_not_schedule_a_nightly_topic(tmp_path, repos):
    from school_notes2.review import topics
    from tests.review.conftest import sh
    rel = legacy(repos.laptop)
    base = repos.commit({rel: safefs.read_text(repos.laptop, rel)})
    changes = dict(repair_migration.updates(repos.laptop))
    head = repos.commit(changes, "review policy migration")
    sh("git", "fetch", "-q", "origin", cwd=repos.wt_path)
    sh("git", "switch", "--detach", head, cwd=repos.wt_path)
    assert topics.affected(repos.repo, repos.wt_path, base, head) == []
    assert topics.plan(repos.repo, repos.wt_path, base, head, {}) == ([], [])


@pytest.mark.parametrize("nightly", [True, False])
def test_third_unsuccessful_disagreement_is_owner(tmp_path, nightly):
    rel = setup(tmp_path)
    for n in range(2):
        files.apply_closure(tmp_path, f"fix-{n}", [], files.open_items(tmp_path, "cron"), automatic=True)
    closure = {"file": rel, "item_id": "R1", "status": "disagree", "note": "Szakmai indok."}
    files.apply_closure(tmp_path, "third", [closure], files.open_items(tmp_path, "cron"), automatic=True)
    if nightly:
        topic_result.apply_item(tmp_path, {"status": "disagree"},
                                {"key": rel + "#R1", "verdict": "keep", "answer": "Fenntartom."})
    else:
        relations.reply(tmp_path, rel + "#R1", "keep", "Fenntartom.")
    assert item(tmp_path, rel)["status"] == "owner"
    assert item(tmp_path, rel)["round"] == 2


def test_migrated_zero_attempts_ignore_old_d77_history(tmp_path):
    rel = setup(tmp_path)
    for n in range(5):
        files.apply_closure(tmp_path, f"legacy-{n}", [], files.open_items(tmp_path, "cron"))
    text = safefs.read_text(tmp_path, rel)
    safefs.write_text(tmp_path, rel, frontmatter.set_keys(text, {"repair_policy": 0}))
    for path, text in repair_migration.updates(tmp_path):
        safefs.write_text(tmp_path, path, text)
    files.apply_closure(tmp_path, "new", [], files.open_items(tmp_path, "cron"), automatic=True)
    assert item(tmp_path, rel)["status"] == "open"
    assert item(tmp_path, rel)["repair_attempts"] == 1


@pytest.mark.parametrize("role", ["reader-1", "reviewer", "recheck"])
def test_reviewer_contract_names_real_source_conflict_category(role):
    from importlib.resources import files as resources
    text = resources("school_notes2").joinpath(f"llm/prompts/{role}.txt").read_text()
    assert "Valódi tulajdonosi döntést igénylő forrásellentmondást `forrásellentmondás` kategóriával jelezz" in text
    assert "szakmailag egyértelműen javítható hibát" in text
