"""A stopped notes run preserves the timed-out role and its one incident."""

from types import SimpleNamespace

import pytest

from school_notes2.llm import timeouts
from school_notes2.notify import incidents, pending
from school_notes2.state import phase
from school_notes2.state.files import read_json, write_json
from tests.notify.test_fix33 import world  # noqa: F401


@pytest.mark.parametrize("role", ["reader-1", "figure", "figure-review"])
@pytest.mark.parametrize("crash_before_notice", [False, True])
def test_notes_timeout_one_notice_with_correct_role(world, monkeypatch, role, crash_before_notice):
    ctx, sent = world
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "writing")
    call = SimpleNamespace(role_name=role, run_id=task.run_id, label="unit", role=SimpleNamespace(timeout_s=1))
    timeouts.record(ctx, call)
    if crash_before_notice:
        with monkeypatch.context() as patch:
            def crash(*args):
                raise KeyboardInterrupt()
            patch.setattr(timeouts, "stopped", crash)
            with pytest.raises(KeyboardInterrupt):
                timeouts.record(ctx, call)
    else:
        timeouts.record(ctx, call)
    task.mark_needs_owner("timeout", "continue", "timeout")
    for _ in range(2):
        incidents.task_error(ctx, phase.load(task.dir))
        pending.retry(ctx)
    assert len(sent) == 1
    name = timeouts.role_name(role)
    assert f"időtúllépés ({incidents.ROLES[name]})" in sent[0].get_content()
    assert f"school-notes status --clear {ctx.name} {name} --continue" in sent[0].get_content()
    assert [i["scope"] for i in incidents.active(ctx)] == ["timeout:" + name]


def test_existing_timeout_even_without_suspended_state_is_reused(world):
    ctx, sent = world
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "writing")
    incidents.record(ctx, "timeout", "reader", role="reader", scope="timeout:reader", run_id=task.run_id)
    task.mark_needs_owner("timeout", "continue", "timeout")
    incidents.task_error(ctx, task)
    assert len(sent) == 1
    assert [i["scope"] for i in incidents.active(ctx)] == ["timeout:reader"]


def test_first_nightly_success_retires_legacy_scopes_only(world):
    ctx, sent = world
    for label in ("a", "b"):
        incidents.record(ctx, "timeout", "reviewer", role="reviewer",
                         scope="timeout:reviewer:" + label, run_id="old-night")
    incidents.record(ctx, "timeout", "reviewer", role="reviewer", scope="timeout:reviewer", run_id="night")
    write_json(timeouts.path(ctx), {"reviewer_units": {"blocked": {"suspended": True, "count": 2}}})
    call = SimpleNamespace(role_name="reviewer", label="success")
    timeouts.success(ctx, call)
    timeouts.success(ctx, call)
    assert [i["scope"] for i in incidents.active(ctx)] == ["timeout:reviewer"]
    assert all(v.get("resolved_at") for v in read_json(incidents.path(ctx)).values()
               if v["scope"].startswith("timeout:reviewer:"))
    assert len(sent) == 3  # Recovery itself sends no mail.
