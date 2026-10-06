"""Fix-52: the fix-51 review's findings on the paid reopen and the owner's closure, and a
figure that is only parked: `--reopen figure:<id>` lifts the parking without any paid frame
(owner, 2026-10-06: a paid request was refused whole because `tortenelem-banner` was only
parked)."""

import json

import pytest

from school_notes2.figures import pending, rechecks
from school_notes2.flows import fix_progress, owner_close, reopen, reopen_targets, status_text
from school_notes2.images import generate, plans
from school_notes2.review import files
from school_notes2.state import phase, safefs
from school_notes2.state.files import read_json, write_json
from tests.flows.test_fix49 import REVIEW, Bare, _seed, origin, pending_entry, world  # noqa: F401
from tests.flows.test_fix51 import FID, PARKED, banner, ledger
from tests.operations.test_round import cfg  # noqa: F401

OTHER = "tortenelem-banner"


def two_banners(ctx, other_owner=False):
    """origin/main: the exhausted owner banner and a second banner, not with the owner."""
    banner(ctx)
    table = ctx.bare().table
    second = pending_entry(owner=other_owner, kind="banner")
    second["commission"] = {**second["commission"], "id": OTHER}
    table["docs/figure-pending.json"] = json.dumps(json.loads(table["docs/figure-pending.json"]) + [second])
    safefs.write_text(ctx.notes_path, "docs/figure-pending.json", table["docs/figure-pending.json"])
    return table


def test_a_parked_figure_is_freed_without_a_request_or_a_paid_frame(world):
    ctx, _ = world
    two_banners(ctx)
    ledger(ctx, ("rejected",))                               # the ledger has only FID; OTHER is fresh
    write_json(fix_progress.path(ctx), {f"figure:{OTHER}": PARKED, "other": PARKED})
    answer = reopen.request(ctx, [f"figure:{OTHER}"])
    assert answer.startswith("parkolás feloldva (fizetős keret nélkül): figure:tortenelem-banner")
    assert list(read_json(fix_progress.path(ctx), {})) == ["other"]
    assert reopen.load(ctx) == [] and "owner.unparked" in ctx.log.main.read_text()
    answer = reopen.request(ctx, [f"figure:{OTHER}"])          # neither waiting nor parked now
    assert "not waiting for the owner and not parked" in answer and answer.startswith("Nem rögzítettem")


def test_the_owners_paid_request_takes_a_parked_banner_along_and_names_each_refusal(world):
    ctx, _ = world
    two_banners(ctx)
    ledger(ctx)                                              # FID: three rejected attempts
    write_json(fix_progress.path(ctx), {f"figure:{OTHER}": PARKED})
    answer = reopen.request(ctx, [f"figure:{FID}", f"figure:{OTHER}"], paid=True)
    assert "0 tétel, 1 ábra; 1 képnek új fizetős keret (3 próba)" in answer
    assert "parkolás feloldva (fizetős keret nélkül): figure:tortenelem-banner" in answer
    [value] = reopen.load(ctx)
    assert value["paid"] == [FID] and value["figures"] == [FID]           # no frame for the parked one
    assert read_json(fix_progress.path(ctx), {}) == {}
    write_json(fix_progress.path(ctx), {f"figure:{OTHER}": PARKED})
    answer = reopen.request(ctx, [f"figure:{OTHER}"], paid=True)
    assert "--paid needs a generated image waiting for the owner" in answer and "without --paid" in answer
    refused = reopen.request(ctx, [f"figure:{FID}", "figure:nincs"], paid=True)
    assert "figure:nincs: no pending figure with this id on origin/main" in refused
    assert len(reopen.load(ctx)) == 1


def test_a_parked_figure_with_its_attempts_used_up_is_not_freed(world):
    settings_ctx, _ = world
    ctx = settings_ctx
    two_banners(ctx)
    settings = ctx.image_settings()
    attempts = [{"number": n, "state": "rejected"} for n in (1, 2, 3)]
    write_json(settings.state_dir / "ledger.json", {"request_id": settings.request_id, "jobs": {
        plans.job_id(ctx.name, OTHER): {"attempts": attempts}}})
    write_json(fix_progress.path(ctx), {f"figure:{OTHER}": PARKED})
    answer = reopen.request(ctx, [f"figure:{OTHER}"])
    assert "parked until 2999-01-01 00:00, and its attempts are used up" in answer and "then --paid" in answer
    assert list(read_json(fix_progress.path(ctx), {})) == [f"figure:{OTHER}"]


def test_a_figure_stopped_by_unjudged_runs_names_its_own_command(world):
    from school_notes2.flows import unjudged
    ctx, _ = world
    ctx.bare = lambda: Bare(origin(owner=False))
    write_json(unjudged.path(ctx), {"hellasz-terkep": {"run_ids": ["a", "b", "c"], "at": "x"}})
    answer = reopen.request(ctx, ["figure:hellasz-terkep"])
    assert f"school-notes status --clear {ctx.name} unjudged --continue" in answer


def test_used_up_means_exhausted_and_the_status_offers_paid_only_then(world):
    ctx, _ = world
    banner(ctx)
    ledger(ctx, ("rejected", "rejected", "generated"))       # the last candidate waits for its verdict
    assert not reopen_targets.paid_used_up(ctx, FID)
    assert "not used up" in reopen.request(ctx, [f"figure:{FID}"], paid=True)
    assert f"figure:{FID} (--paid)" not in status_text.collect(ctx)["reopenable"]
    ledger(ctx)
    assert reopen_targets.paid_used_up(ctx, FID)
    assert f"figure:{FID} (--paid)" in status_text.collect(ctx)["reopenable"]


def test_recheck_assignments_are_dropped_before_the_grant_is_written(world, monkeypatch):
    """An interrupted preparation must not keep the old frame's free review assignments."""
    ctx, _ = world
    banner(ctx)
    settings = ledger(ctx)
    write_json(rechecks.path(ctx), {FID: ["r1", "r2"]})
    reopen.request(ctx, [f"figure:{FID}"], paid=True)
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "moved")
    real = generate.grant
    monkeypatch.setattr(generate, "grant", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        reopen.apply(ctx, task)
    assert read_json(rechecks.path(ctx), {}) == {}                       # dropped before the grant
    monkeypatch.setattr(generate, "grant", real)
    reopen.apply(ctx, task)
    job = settings.ledger()["jobs"][plans.job_id(ctx.name, FID)]
    assert len(job["grants"]) == 1
    write_json(rechecks.path(ctx), {FID: ["n1"]})                        # the new frame's own
    reopen.apply(ctx, task)                                              # a repeated preparation
    assert read_json(rechecks.path(ctx), {}) == {FID: ["n1"]}


def test_without_a_ledger_entry_the_paid_image_stays_with_the_owner(world):
    ctx, _ = world
    banner(ctx)
    ledger(ctx)
    reopen.request(ctx, [f"{REVIEW}#R38", f"figure:{FID}"], paid=True)
    settings = ctx.image_settings()
    write_json(settings.state_dir / "ledger.json", {"request_id": settings.request_id, "jobs": {}})  # a new year
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "moved")
    written, figures = reopen.apply(ctx, task)
    assert figures == [] and written == [REVIEW]                          # the item reopens, the image not
    [entry] = pending.load(ctx.notes_path)
    assert entry["owner_required"]
    body = files.read_report(ctx.notes_path, ctx.notes_path / REVIEW).body
    assert "új fizetős keret" not in body
    log = ctx.log.main.read_text()
    assert "no_ledger_entry" in log and "the image stays with the owner" in log


def test_a_closure_that_closes_nothing_is_a_warning(world):
    ctx, _ = world
    _seed(ctx)
    owner_close.close(ctx, [f"{REVIEW}#R38"], "javítva a toolban")
    text = safefs.read_text(ctx.notes_path, REVIEW).replace("R38: owner", "R38: open")
    safefs.write_text(ctx.notes_path, REVIEW, text)                       # reopened meanwhile
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "moved")
    written, _ = reopen.apply(ctx, task)
    assert written == []
    events = [json.loads(line) for line in ctx.log.main.read_text().splitlines()]
    skipped = [e for e in events if e["action"] == "owner.close_skipped"]
    assert skipped and skipped[0]["level"] == "warning"
    assert not [e for e in events if e["action"] == "owner.closed"]


def test_the_learner_lock_wait_is_bounded(world, monkeypatch):
    ctx, _ = world
    _seed(ctx)
    monkeypatch.setattr(reopen, "WAIT_S", 0.3)
    holder = ctx.lock()
    assert holder.try_acquire("run")
    try:
        for answer in (reopen.request(ctx, [f"{REVIEW}#R38"]),
                       owner_close.close(ctx, [f"{REVIEW}#R38"], "x")):
            assert answer.startswith("Nem rögzítettem semmit: a tanulói zárat run tartja")
            assert "próbáld később" in answer
    finally:
        holder.release()
    assert reopen.load(ctx) == []


@pytest.mark.parametrize("argv,message", [
    (["status", "--note", "x"], "--note belongs to --close"),
    (["status", "--reopen", "barna", "figure:a", "--close", "barna", "docs/review/a.md#R1", "--note", "x"],
     "separate commands"),
])
def test_the_cli_refuses_a_note_without_close_and_reopen_with_close(argv, message):
    from school_notes2 import cli
    with pytest.raises(SystemExit, match=message):
        cli._status(None, cli._parser().parse_args(argv), None)


TOPIC = "wiki/tortenelem/athen.md"
EMPTY = "<sub>🔖 Tankönyv: a kapcsolódó kötet és lecke még nincs azonosítva.</sub>"
GOOD = "<sub>🗓️ Óra: 2026-09-11 · 🔖 Tankönyv: 1. lecke, 12-13. oldal.</sub>"


def test_the_check_warns_about_a_textbook_line_without_a_number_only():
    from school_notes2.wiki import check
    text = f"---\ntitle: A\n---\n# A\n\n{EMPTY}\n\n{GOOD}\n\n```\n🔖 Tankönyv: példa\n```\n"
    assert check.textbook_lines(TOPIC, text) == [6]
    assert check.textbook_lines("wiki/index.md", "* 🔖 **Tankönyv**: a lecke és az oldal\n") == []   # the legend
    assert check.textbook_lines("wiki/tortenelem/index.md", EMPTY) == []
    # Only a digit is looked for, never the words: a stated grade passes.
    assert check.textbook_lines(TOPIC, "🔖 Tankönyv: a 9. évfolyamos tankönyv nem tárgyalja.") == []
    assert check.textbook_lines(TOPIC, "🔖 Tankönyv: lecke · 🗓️ Óra: 2026-09-11") == [1]


def test_check_files_reports_it_as_a_warning(tmp_path):
    from school_notes2.wiki import check
    page = tmp_path / TOPIC
    page.parent.mkdir(parents=True)
    page.write_text(f"---\ntype: topic\ntitle: A\ndescription: d\nchapter: c\norder: 10\n---\n# A\n\n{EMPTY}\n",
                    encoding="utf-8")
    found = [i for i in check.check_files(tmp_path, [TOPIC]) if i["message"] == check.TEXTBOOK_MESSAGE]
    assert found == [{"file": TOPIC, "line": 10, "message": check.TEXTBOOK_MESSAGE, "severity": "warning"}]


def test_an_empty_textbook_line_becomes_one_machine_item_per_page(world):
    from school_notes2.flows import textbook_lines, work_pending
    from school_notes2.review import relations
    ctx, _ = world
    _seed(ctx)
    safefs.write_text(ctx.notes_path, TOPIC, f"---\ntitle: A\ntype: topic\ndescription: d\n---\n# A\n\n{EMPTY}\n\n"
                      f"## B\n\n{EMPTY}\n")
    assert textbook_lines.new(ctx.notes_path) == [{"page": TOPIC, "line": 8, "quote": EMPTY}]
    assert work_pending.ready(ctx)
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "moved")
    task.update(mode="fix", base="b")
    for _ in range(2):                                       # a resumed preparation adds no second item
        textbook_lines.record(ctx, task)
    items = [i for i in files.open_items(ctx.notes_path, "cron") if i["file"] == task.get("inspection_report")]
    assert len(items) == 1
    detail = relations.inventory(ctx.notes_path)["items"][items[0]["key"]]
    assert detail["file"] == TOPIC and detail["hit_id"] == f"textbook-line:{TOPIC}" and detail["quote"] == EMPTY
    assert "csak azonosított leckével és oldalszámmal áll" in (ctx.notes_path / items[0]["file"]).read_text()
    assert textbook_lines.new(ctx.notes_path) == []
    rel = items[0]["file"]                                   # a closed item never brings the page back
    safefs.write_text(ctx.notes_path, rel, safefs.read_text(ctx.notes_path, rel).replace(
        f"{items[0]['item_id']}: open", f"{items[0]['item_id']}: disagree"))
    assert textbook_lines.new(ctx.notes_path) == []


@pytest.mark.parametrize("role", ["writer", "fix"])
def test_the_writer_prompts_and_rules_leave_an_unidentified_textbook_line_out(role):
    from pathlib import Path
    from school_notes2.llm import argv
    assert "A `🔖 Tankönyv:` sor csak azonosított leckével és oldalszámmal áll; ha a lecke nem azonosítható, " \
           "a sor elmarad" in argv.prompt(role, "file", grade=9)
    root = Path(__file__).resolve().parents[4]
    assert "The `🔖 Tankönyv:` line stands only with an identified lesson and page." in (
        root / "instructions/note-formatting.md").read_text(encoding="utf-8")
