from types import SimpleNamespace

import pytest

from school_notes2.flows import operation, policy, writer, writer_identity
from school_notes2.notify import incidents
from school_notes2.state import phase, safefs
from school_notes2.state.errors import BadWork
from tests.conftest import recording_mailer


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("crash", [False, True])
def test_same_output_counts_once_across_resume(tmp_path, log, monkeypatch, learner, crash):
    repo = tmp_path / "repo"
    repo.mkdir()
    sent = []
    ctx = SimpleNamespace(name=learner, notes_path=repo, log=log,
                          cfg=SimpleNamespace(state_dir=tmp_path / "state"))
    ctx.mailer = recording_mailer(tmp_path, log, monkeypatch, sent)
    task = phase.create(tmp_path, learner, "notes", "cron", "writing")
    safefs.write_text(repo, "wiki/s/a.md", "# Hibás\n")
    result = {"status": "done"}
    safefs.write_json(task.dir, "result-1.json", result)
    writer_identity.remember(ctx, task, 1, result)
    def fail(t):
        with operation.scope(ctx):
            policy.on_error(BadWork("invalid output"), task=t, student=learner,
                            step="run", log=log, mailer=ctx.mailer)
    original = task.save
    def stop():
        original()
        if task.data["llm_failures"] == 1:
            raise KeyboardInterrupt()
    if crash:
        monkeypatch.setattr(task, "save", stop)
        with pytest.raises(KeyboardInterrupt):
            fail(task)
    else:
        fail(task)
    for _ in range(2):
        task = phase.load(task.dir)
        writer_identity.remember(ctx, task, 1, result)
        fail(task)
        assert task.data["llm_failures"] == 1 and task.data["needs_owner"] is None
    assert not incidents.active(ctx) and not sent
    # A genuinely changed writer tree counts as another output, with one incident.
    safefs.write_text(repo, "wiki/s/a.md", "# Másik hibás kimenet\n")
    writer_identity.remember(ctx, task, 1, result)
    fail(task)
    assert task.data["llm_failures"] == 2 and task.data["needs_owner"]
    fail(phase.load(task.dir))
    assert len(incidents.active(ctx)) == len(sent) == 1


@pytest.mark.parametrize("writing_k", [1, 2])
def test_cached_legacy_result_gets_identity_without_new_writer(tmp_path, log, monkeypatch, writing_k):
    ctx = SimpleNamespace(notes_path=tmp_path, log=log,
                          cfg=SimpleNamespace(role=lambda _: (None, None), limits=SimpleNamespace(max_agents=3)))
    task = phase.create(tmp_path, "barna", "notes", "cron", "writing")
    task.update(ranges=[[0, 0]], writing_k=writing_k)
    safefs.write_json(task.dir, "result-1.json", {"status": "done"})
    monkeypatch.setattr(writer, "_call", lambda *a: pytest.fail("new LLM call"))
    keys = []
    for _ in range(2):
        task = phase.load(task.dir)
        writer.run_ranges(ctx, task, None)
        keys.append(task.get("writer_output_key"))
        policy.on_error(BadWork("scope"), task=task, student="barna", step="run", log=log, mailer=None)
    assert keys[0] and keys[0] == keys[1]
    assert task.data["llm_failures"] == 1 and task.data["needs_owner"] is None


def test_result_content_is_part_of_identity(tmp_path):
    ctx = SimpleNamespace(notes_path=tmp_path)
    task = phase.create(tmp_path, "barna", "notes", "cron", "writing")
    writer_identity.remember(ctx, task, 1, {"status": "done"})
    first = task.get("writer_output_key")
    writer_identity.remember(ctx, task, 1, {"status": "done", "owner_notes": ["Másik kimenet."]})
    assert first != task.get("writer_output_key")


@pytest.mark.parametrize("crash", [False, True])
def test_preupgrade_counted_result_is_not_counted_again(tmp_path, log, monkeypatch, crash):
    ctx = SimpleNamespace(notes_path=tmp_path)
    task = phase.create(tmp_path, "barna", "notes", "cron", "writing")
    task.update(ranges=[[0, 0]], writing_k=2)
    safefs.write_json(task.dir, "result-1.json", {"status": "done"})
    task.data["llm_failures"] = 1
    task.record_error("bad_work", "fix changed an unassigned page")
    task = phase.load(task.dir)
    if crash:
        original = task.save
        def stop():
            original()
            raise KeyboardInterrupt()
        monkeypatch.setattr(task, "save", stop)
        with pytest.raises(KeyboardInterrupt):
            writer_identity.ensure(ctx, task)
    else:
        writer_identity.ensure(ctx, task)
    task = phase.load(task.dir)
    writer_identity.ensure(ctx, task)
    policy.on_error(BadWork("old result"), task=task, student="barna", step="run", log=log, mailer=None)
    assert task.data["llm_failures"] == 1 and task.data["needs_owner"] is None


def test_known_bad_fix_output_gets_a_new_bounded_invocation(tmp_path, log, monkeypatch):
    ctx = SimpleNamespace(notes_path=tmp_path, log=log,
                          cfg=SimpleNamespace(role=lambda _: (None, None), limits=SimpleNamespace(max_agents=3)))
    task = phase.create(tmp_path, "barna", "notes", "cron", "writing")
    task.update(ranges=[[0, 0]], mode="fix")
    called = []
    monkeypatch.setattr(writer, "write_inputs", lambda *a: None)
    def bad(*args):
        called.append(1)
        safefs.write_json(tmp_path, ".school-notes/result.json", {"status": "done"})
        raise BadWork("invalid result")
    monkeypatch.setattr(writer, "_call", bad)
    for _ in range(2):
        task = phase.load(task.dir)
        with pytest.raises(BadWork):
            writer.run_ranges(ctx, task, None)
        policy.on_error(BadWork("invalid result"), task=task, student="barna", step="run", log=log, mailer=None)
    assert called == [1, 1]
    assert task.data["llm_failures"] == 2 and task.data["needs_owner"]
