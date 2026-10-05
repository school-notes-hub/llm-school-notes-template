"""Fix-49 (2.6.1): recheck-only runs once a round with one owner mail after three failures;
an unreviewed drawn figure and a transient writer interruption are no tries; the owner's
reopen; a whole figure block may be removed by the writer."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from school_notes2.flows import clear, context, fix, operational_report, round as scheduler, unchecked
from school_notes2.log import TZ
from school_notes2.state import phase
from tests.conftest import recording_mailer
from tests.flows.test_fix47 import PAGE, held, task_for  # noqa: F401
from tests.operations.test_round import cfg  # noqa: F401


@pytest.fixture
def world(cfg, monkeypatch):
    ctx = context.make(cfg, "third", console=False)
    notices = []
    ctx.mailer = recording_mailer(cfg.state_dir, ctx.log, monkeypatch, notices)
    return ctx, notices


@pytest.mark.parametrize("recheck_only,cycles", [(True, 1), (False, 2)])
def test_a_recheck_only_run_is_no_progress_of_the_round(cfg, monkeypatch, recheck_only, cycles):
    """REJT-14: the round does not start another cycle because a recheck-only run finished."""
    monkeypatch.setattr(scheduler, "now", lambda: datetime(2026, 10, 4, 8, tzinfo=TZ))
    monkeypatch.setattr(scheduler.nightly, "nightly", lambda c: None)
    calls = []
    def run(ctx):
        calls.append(ctx.name)
        if len(calls) == 1:                    # the first learner's first run
            task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "done")
            task.update(recheck_only=recheck_only)
    monkeypatch.setattr(scheduler.run, "run", run)
    scheduler.round(cfg)
    assert calls.count(calls[0]) == cycles


def test_one_recheck_only_run_per_round(tmp_path, held, monkeypatch):
    ctx, _ = held
    unchecked.update(ctx, task_for(tmp_path, "b1"), {PAGE: "b1"}, set())
    ctx.worktree = lambda _: SimpleNamespace(run=lambda *a, **kw: None)
    ctx.bare = lambda: None
    ctx.task_root = lambda: tmp_path / "root"
    ctx.cfg.timeouts = SimpleNamespace(fetch_s=1)
    ctx.cfg.limits = SimpleNamespace(max_agents=3)
    monkeypatch.setattr(fix.repos, "fetch", lambda *a: None)
    monkeypatch.setattr(fix.repos, "rev", lambda *a: "main")
    monkeypatch.setattr(fix.files, "open_items", lambda *a: [])
    monkeypatch.setattr(fix.pending, "load", lambda *a: [])
    monkeypatch.setattr(fix.correction_figures, "assignable", lambda *a: [])
    monkeypatch.setattr(fix.fix_progress, "available", lambda ctx, items, waiting: (items, waiting))
    monkeypatch.setattr(fix.fix_progress, "runnable_images", lambda ctx, waiting: waiting)
    monkeypatch.setattr(fix.reopen, "pending", lambda ctx: [])
    task = fix.next_task(ctx)
    assert task.get("recheck_only") is True
    task.data["closed"] = True
    task.save()
    assert fix.next_task(ctx) is None          # the same round: no second recheck-only run
    assert unchecked.startable(ctx)


def test_three_failed_rechecks_one_mail_and_the_owner_lifts_it(tmp_path, world):
    ctx, notices = world
    task = SimpleNamespace(run_id="r0")
    for n in range(unchecked.LIMIT):
        task = SimpleNamespace(run_id=f"r{n}")
        unchecked.update(ctx, task, {PAGE: "b1"}, set())
        assert len(notices) == (1 if n == unchecked.LIMIT - 1 else 0)
    unchecked.update(ctx, SimpleNamespace(run_id="other"), {PAGE: "b1"}, set())   # a later run of other work
    assert len(notices) == 1
    text = notices[0].get_content()
    assert "háromszor" in text and "status --clear third unchecked --continue" in text
    assert not unchecked.startable(ctx) and unchecked.exhausted(ctx) == [PAGE]
    answer = clear.clear(ctx, "unchecked", "continue")
    assert "1 oldal" in answer
    assert unchecked.startable(ctx) and unchecked.exhausted(ctx) == []
    from school_notes2.notify import incidents
    assert not [i for i in incidents.active(ctx) if i["scope"] == unchecked.SCOPE]
    # A page rechecked by another run ends the owner state too.
    for n in range(unchecked.LIMIT):
        unchecked.update(ctx, SimpleNamespace(run_id=f"s{n}"), {PAGE: "b1"}, set())
    unchecked.update(ctx, SimpleNamespace(run_id="t"), {}, {PAGE})
    assert not [i for i in incidents.active(ctx) if i["scope"] == unchecked.SCOPE]


def test_a_recheck_only_run_sends_no_completion_mail(world, monkeypatch):
    ctx, notices = world
    sent = []
    monkeypatch.setattr(operational_report.pending, "send", lambda ctx, notice: sent.append(notice))
    for flag in (True, False):
        task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "done")
        task.update(mode="fix", recheck_only=flag)
        operational_report.completed(ctx, task, {}, 0)
    assert [n.kind.split(":")[0] for n in sent] == ["completion"] and sent[0].run_id == task.run_id


BRIEF = {"id": "hellasz-terkep", "page": "wiki/t/hellasz.md", "anchor": "Hol?", "kind": "figure",
         "purpose": "A térségek helye", "must_show": ["három térség"], "avoid_misreading": "nem határ",
         "taught_conventions": [], "text_complete_without_figure": True}
REVIEW = "docs/review/2026-10-05-review.md"
REPORT = f"""---
reviewer: check
range: {{from: a, to: b}}
items: {{R37: fixed, R38: owner}}
status: open
repair_policy: 1
item_details:
  R37: {{round: 1, chain: 0, file: wiki/t/hellasz.md}}
  R38: {{round: 1, chain: 0, file: wiki/t/hellasz.md, repair_attempts: 3, repair_runs: [r1, r2, r3], owner_question: Mi legyen?}}
---

# Review – 2026-10-05

### R38 – wiki/t/hellasz.md:49

**Probléma:** Nincs térkép.
"""


def pending_entry(owner=True, kind="figure"):
    return {"commission": {**BRIEF, "kind": kind}, "status": "pending", "runs": 3 if owner else 1,
            "run_ids": ["r1", "r2", "r3"] if owner else ["r1"], "defects": [], "owner_required": owner}


class Bare:
    def __init__(self, table):
        self.table = table

    def run(self, *args, check=True, **kw):
        text = self.table.get(args[1].split(":", 1)[1])
        return SimpleNamespace(returncode=0 if text is not None else 128, stdout=(text or "").encode())


def origin(owner=True, kind="figure"):
    import json
    return {REVIEW: REPORT, "docs/figure-pending.json": json.dumps([pending_entry(owner, kind)]),
            BRIEF["page"]: "---\ntitle: H\n---\n# H\n\n## Hol?\n\n<!-- figure: hellasz-terkep -->\n"}


def test_reopen_request_is_validated_logged_and_unparks(world):
    from school_notes2.flows import fix_progress, reopen
    from school_notes2.state.files import read_json, write_json
    ctx, _ = world
    ctx.bare = lambda: Bare(origin())
    write_json(fix_progress.path(ctx), {f"{REVIEW}#R38": "2999-01-01T00:00:00+00:00",
                                        "figure:hellasz-terkep": "2999-01-01T00:00:00+00:00", "other": "2999-01-01T00:00:00+00:00"})
    refused = reopen.request(ctx, [f"{REVIEW}#R37", "figure:nincs", "wiki/x.md"])
    assert refused.startswith("Nem rögzítettem") and reopen.load(ctx) == []
    assert "R37: not waiting for the owner (fixed)" in refused
    answer = reopen.request(ctx, [f"{REVIEW}#R38", "figure:hellasz-terkep"])
    assert "1 tétel, 1 ábra" in answer
    [value] = reopen.load(ctx)
    assert value["items"] == [f"{REVIEW}#R38"] and value["figures"] == ["hellasz-terkep"]
    assert list(read_json(fix_progress.path(ctx), {})) == ["other"]
    assert "owner.reopen_requested" in ctx.log.main.read_text()
    ctx.bare = lambda: Bare(origin(kind="banner"))
    assert "generated image" in reopen.request(ctx, ["figure:hellasz-terkep"])


def test_the_fix_run_applies_the_reopen_once(world):
    import json
    from school_notes2.figures import migration_gate, pending
    from school_notes2.flows import reopen
    from school_notes2.review import files
    from school_notes2.state import safefs
    ctx, _ = world
    repo = ctx.notes_path
    repo.mkdir(parents=True)
    for rel, text in origin().items():
        safefs.write_text(repo, rel, text)
    safefs.write_json(repo, migration_gate.MARK, {"pending_format": "attempted-runs"})
    ctx.bare = lambda: Bare(origin())
    reopen.request(ctx, [f"{REVIEW}#R38", "figure:hellasz-terkep"])
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "moved")
    assert [v["id"] for v in reopen.pending(ctx)] == [reopen.load(ctx)[0]["id"]]
    written, figures = reopen.apply(ctx, task)
    assert written == ["docs/figure-pending.json", REVIEW] and figures == ["hellasz-terkep"]
    page = files.read_report(repo, repo / REVIEW)
    assert page.meta["items"] == {"R37": "fixed", "R38": "open"}
    assert page.meta["item_details"]["R38"]["repair_attempts"] == 0
    assert "owner_question" not in page.meta["item_details"]["R38"]
    assert page.body.count("## Újranyitva (") == 1
    assert "* R38 – újranyitva: a tulajdonos újranyitotta" in page.body
    assert [i["item_id"] for i in files.open_items(repo, "cron")] == ["R38"]
    [entry] = pending.load(repo)
    assert entry["runs"] == 0 and entry["run_ids"] == [] and not entry["owner_required"]
    before = safefs.read_text(repo, REVIEW)
    assert reopen.apply(ctx, task)[0] == [REVIEW]          # an interrupted preparation: no second section
    assert safefs.read_text(repo, REVIEW) == before
    assert reopen.pending(ctx) == []                        # the run carries it
    task.data["closed"] = True                              # discarded: the next run applies it again
    task.save()
    assert len(reopen.pending(ctx)) == 1
    task2 = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "moved")
    reopen.apply(ctx, task2)
    task2.set_phase("done")
    assert reopen.pending(ctx) == [] and reopen.load(ctx) == []
    assert "owner.reopened" in ctx.log.main.read_text() and json.loads(
        safefs.read_text(repo, "docs/figure-pending.json"))[0]["runs"] == 0


def test_missing_images_say_what_they_count(world):
    """Fix-49/9: "hiányzó kép" is wider than "függő ábra"; the line names the parts."""
    import json
    from school_notes2.figures import migration_gate
    from school_notes2.flows import work_pending
    from school_notes2.state import safefs
    ctx, _ = world
    repo = ctx.notes_path
    repo.mkdir(parents=True)
    safefs.write_text(repo, BRIEF["page"], "---\ntitle: H\ntype: topic\ndescription: d\n---\n# H\n\n## Hol?\n\n"
                      "<!-- figure: hellasz-terkep -->\n\n<!-- image: arva-fejlec -->\n\n![x](../assets/nincs.png)\n")
    safefs.write_text(repo, "docs/figure-pending.json", json.dumps([pending_entry(owner=False)]))
    safefs.write_json(repo, migration_gate.MARK, {"pending_format": "attempted-runs"})
    line = work_pending.completion(ctx)[1]
    assert line.endswith("3 hiányzó kép (1 függő ábra; 1 ábrahely, amely nincs a függő ábrák között; 1 törött képlink)")
