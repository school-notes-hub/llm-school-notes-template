"""Fix-51: a generated image reopened with the owner's paid approval (one new frame of paid
attempts), the owner's own closure of an item, and both commands without the VM lock."""

import json
import threading

from school_notes2.flows import fix_progress, operation, owner_close, reopen, status_text
from school_notes2.images import generate, plans
from school_notes2.review import files
from school_notes2.state import phase, safefs
from school_notes2.state.files import read_json, write_json
from tests.flows.test_fix49 import REVIEW, Bare, _seed, origin, world  # noqa: F401
from tests.operations.test_round import cfg  # noqa: F401

FID = "hellasz-terkep"
PARKED = "2999-01-01T00:00:00+00:00"


def ledger(ctx, states=("rejected", "rejected", "rejected")):
    settings = ctx.image_settings()
    attempts = [{"number": n, "state": s, "cost_usd": "0.03", "started_at": "2026-10-05T10:00:00+02:00"}
                for n, s in enumerate(states, 1)]
    write_json(settings.state_dir / "ledger.json",
               {"request_id": settings.request_id, "jobs": {plans.job_id(ctx.name, FID): {"attempts": attempts}}})
    return settings


def banner(ctx):
    """origin/main and the worktree: a generated banner, exhausted, its item with the owner."""
    table = origin(kind="banner")
    table[REVIEW] = table[REVIEW].replace("owner_question: Mi legyen?", f"owner_question: Mi legyen?, figure_id: {FID}")
    repo = ctx.notes_path
    repo.mkdir(parents=True, exist_ok=True)
    for rel, text in table.items():
        safefs.write_text(repo, rel, text)
    from school_notes2.figures import migration_gate
    safefs.write_json(repo, migration_gate.MARK, {"pending_format": "attempted-runs"})
    ctx.bare = lambda: Bare(table)


def test_a_generated_image_reopens_only_with_paid_and_only_when_used_up(world):
    ctx, _ = world
    banner(ctx)
    answer = reopen.request(ctx, [f"figure:{FID}"])
    assert answer.startswith("Nem rögzítettem") and "--paid" in answer
    ledger(ctx, ("rejected", "rejected"))
    assert "not used up" in reopen.request(ctx, [f"figure:{FID}"], paid=True)
    ctx.bare = lambda: Bare(origin())                       # a drawn figure costs nothing
    assert "without --paid" in reopen.request(ctx, [f"figure:{FID}"], paid=True)
    assert "needs a generated image" in reopen.request(ctx, [f"{REVIEW}#R38"], paid=True)
    assert reopen.load(ctx) == []


def test_paid_reopen_unparks_opens_one_new_frame_and_writes_a_line(world):
    """Owner, 2026-10-06 ("1 ok"): Barna's two exhausted banners are tried once more."""
    from school_notes2.figures import pending, rechecks
    ctx, _ = world
    banner(ctx)
    settings = ledger(ctx)
    assert generate.exhausted(settings.ledger()["jobs"][plans.job_id(ctx.name, FID)], settings.max_attempts)
    write_json(fix_progress.path(ctx), {f"figure:{FID}": PARKED, "other": PARKED})
    write_json(rechecks.path(ctx), {FID: ["r1", "r2"], "masik": ["r1"]})
    answer = reopen.request(ctx, [f"{REVIEW}#R38", f"figure:{FID}"], paid=True)
    assert "1 tétel, 1 ábra; 1 képnek új fizetős keret (3 próba)" in answer
    [value] = reopen.load(ctx)
    assert value["paid"] == [FID] and value["figures"] == [FID]
    assert list(read_json(fix_progress.path(ctx), {})) == ["other"]            # unparked
    assert "grants" not in settings.ledger()["jobs"][plans.job_id(ctx.name, FID)]   # the run grants
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "moved")
    written, figures = reopen.apply(ctx, task)
    assert figures == [FID] and sorted(written) == ["docs/figure-pending.json", REVIEW]
    job = settings.ledger()["jobs"][plans.job_id(ctx.name, FID)]
    assert [a["number"] for a in job["attempts"]] == [1, 2, 3]                   # the old attempts stay
    assert [(g["request"], g["first_attempt"], g["attempts"]) for g in job["grants"]] == [(value["id"], 4, 3)]
    assert generate.attempts_used(job) == 0 and not generate.exhausted(job, settings.max_attempts)
    assert read_json(rechecks.path(ctx), {}) == {"masik": ["r1"]}
    body = files.read_report(ctx.notes_path, ctx.notes_path / REVIEW).body
    assert f"* figure:{FID} – új fizetős keret: legfeljebb 3 próba, a tulajdonos jóváhagyásával" in body
    [entry] = pending.load(ctx.notes_path)
    assert not entry["owner_required"] and entry["runs"] == 0
    reopen.apply(ctx, task)                                  # a repeated preparation grants nothing
    assert len(settings.ledger()["jobs"][plans.job_id(ctx.name, FID)]["grants"]) == 1
    assert "owner.paid_frame" in ctx.log.main.read_text()
    job["attempts"] += [{"number": n, "state": "rejected"} for n in (4, 5, 6)]
    assert generate.exhausted(job, settings.max_attempts)    # the new frame is bounded again


def test_the_owner_closes_an_item_with_a_note(world):
    from school_notes2.review import nightly
    ctx, _ = world
    _seed(ctx)
    assert "--note is required" in owner_close.close(ctx, [f"{REVIEW}#R38"], "  ")
    assert "not waiting for the owner (fixed)" in owner_close.close(ctx, [f"{REVIEW}#R37"], "x")
    assert reopen.load(ctx) == []
    answer = owner_close.close(ctx, [f"{REVIEW}#R38"], "javítva a  toolban\n(2.6.0)")
    assert "1 tétel, javítva" in answer
    [value] = reopen.load(ctx)
    assert value["close"] == [f"{REVIEW}#R38"] and value["note"] == "javítva a toolban (2.6.0)"
    assert value["id"].startswith("close-")
    assert f"{REVIEW}#R38 (lezárás)" in status_text._reopen(ctx)
    assert reopen.pending(ctx)                               # a pending request starts a fix run
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "moved")
    written, figures = reopen.apply(ctx, task)
    assert written == [REVIEW] and figures == []
    page = files.read_report(ctx.notes_path, ctx.notes_path / REVIEW)
    assert page.meta["items"] == {"R37": "fixed", "R38": "fixed"} and page.meta["status"] == "closed"
    detail = page.meta["item_details"]["R38"]
    assert detail["owner_closed"] == {"request": value["id"], "note": "javítva a toolban (2.6.0)"}
    assert "owner_question" not in detail
    assert f"## Tulajdonosi lezárás ({value['id']})" in page.body
    assert "* R38 – javítva (tulajdonosi döntés): javítva a toolban (2.6.0)" in page.body
    before = safefs.read_text(ctx.notes_path, REVIEW)
    reopen.apply(ctx, task)
    assert safefs.read_text(ctx.notes_path, REVIEW) == before
    assert [c["key"] for c in nightly.open_closures(ctx.notes_path)] == [f"{REVIEW}#R37"]
    assert "owner.close_requested" in ctx.log.main.read_text() and "owner.closed" in ctx.log.main.read_text()


def test_the_commands_need_no_vm_lock_and_wait_for_the_learner_lock(world):
    """A round with continuous work holds the VM lock for hours: the owner's command still
    gets in, between two runs, through the learner lock alone."""
    ctx, _ = world
    _seed(ctx)
    vm = operation.vm_lock(ctx.cfg)
    assert vm.try_acquire("round")
    learner = ctx.lock()
    assert learner.try_acquire("run")
    released = threading.Timer(0.3, learner.release)
    released.start()
    try:
        assert "1 tétel, 0 ábra" in reopen.request(ctx, [f"{REVIEW}#R38"])
        assert "1 tétel, javítva" in owner_close.close(ctx, [f"{REVIEW}#R38"], "javítva a toolban")
    finally:
        released.join()
        vm.release()
    assert [v["id"].split("-")[0] for v in reopen.load(ctx)] == ["reopen", "close"]
    assert ctx.lock().probe()                                # released again
