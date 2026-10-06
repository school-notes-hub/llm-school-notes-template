"""Fix-50 (2.6.2): a reopened item about a pending figure and the reopened figure are one
assignment – one call, the figure listed once; a pending figure's run counter grows once per
judged run even if the figure was listed twice."""

import pytest

from school_notes2.figures import commissions, pending
from school_notes2.flows import fetch, reopen, writer
from school_notes2.review import files
from school_notes2.sources import calls
from school_notes2.state import phase
from tests.flows.test_fix49 import BRIEF, REPORT, REVIEW, Bare, _seed, origin, world  # noqa: F401
from tests.flows.test_fix47 import held  # noqa: F401
from tests.operations.test_round import cfg  # noqa: F401

FIGURE = "owner_question: Mi legyen?, figure_id: hellasz-terkep"


def _table():
    """Benedek, 2026-10-06: R38 (about the map) and the map itself wait for the owner; R37
    is an ordinary open item on the same page."""
    table = origin()
    table[REVIEW] = (REPORT.replace("owner_question: Mi legyen?", FIGURE)
                     .replace("items: {R37: fixed, R38: owner}", "items: {R37: open, R38: owner}"))
    return table


@pytest.mark.parametrize("targets", [[f"{REVIEW}#R38"], [f"{REVIEW}#R38", "figure:hellasz-terkep"]])
def test_a_reopened_item_and_its_reopened_figure_are_one_assignment(world, monkeypatch, targets):
    from school_notes2.state import safefs
    ctx, _ = world
    _seed(ctx)
    table = _table()
    safefs.write_text(ctx.notes_path, REVIEW, table[REVIEW])
    ctx.bare = lambda: Bare(table)
    assert "1 tétel, 1 ábra" in reopen.request(ctx, targets)
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "moved")
    _, figures = reopen.apply(ctx, task)
    assert figures == ["hellasz-terkep"]
    items = files.open_items(ctx.notes_path, "cron")
    waiting = pending.load(ctx.notes_path)
    assert [i["item_id"] for i in items] == ["R37", "R38"] and len(waiting) == 1
    grouping = calls.fix_assignments(ctx.notes_path, items, waiting)
    assert grouping == calls.fix_assignments(ctx.notes_path, items[::-1], waiting)
    # The text call keeps R37; R38 goes with its figure into the figure's call.
    assert [[i["item_id"] for i in c["open_review_items"]] for c in grouping] == [["R37"], ["R38"]]
    assert [c["pending_figure_ids"] for c in grouping] == [[], ["hellasz-terkep"]]
    task.update(mode="fix", calls=grouping, ranges=calls.ranges(grouping), open_review_items=items,
                pending_figures=waiting, packages=[], pages=[])
    monkeypatch.setattr(fetch, "validate", lambda *a: None)
    text, figure = (fetch.fetch_json(task, k, grade=9) for k in (1, 2))
    assert text["pending_figures"] == []
    assert [e["commission"]["id"] for e in figure["pending_figures"]] == ["hellasz-terkep"]
    assert [i["item_id"] for i in figure["open_review_items"]] == ["R38"]


def test_an_item_about_a_figure_that_is_not_pending_stays_in_the_text_call(world):
    from school_notes2.state import safefs
    ctx, _ = world
    _seed(ctx)
    table = _table()
    safefs.write_text(ctx.notes_path, REVIEW, table[REVIEW].replace("R38: owner", "R38: open"))
    items = files.open_items(ctx.notes_path, "cron")
    grouping = calls.fix_assignments(ctx.notes_path, items, [])
    assert [[i["item_id"] for i in c["open_review_items"]] for c in grouping] == [["R37", "R38"]]


def test_the_same_figure_from_two_calls_is_one_assignment():
    entry = {"id": BRIEF["id"], "page": BRIEF["page"], "kind": "figure"}
    first = {"status": "done", "figures": [entry]}
    second = {"status": "done", "figures": [dict(entry)]}
    merged = writer.merge([first, second])
    assert merged["figures"] == [entry]
    waiting = [{"commission": BRIEF}]
    assert [a["id"] for a in commissions.assignments(merged, waiting)] == [BRIEF["id"]]
    # A different page or kind under the same id is a real conflict and stays visible.
    other = writer.merge([first, {"status": "done", "figures": [{**entry, "kind": "banner"}]}])
    assert len(other["figures"]) == 2


# Fix-50/4: an orphan figure place is a machine item of the next fix run.

ORPHAN_PAGE = "wiki/m/grafok.md"
ORPHAN = "<!-- image: grafok-fejlec -->"


def _orphan(ctx):
    from school_notes2.state import safefs
    _seed(ctx)
    safefs.write_text(ctx.notes_path, ORPHAN_PAGE, f"---\ntitle: G\ntype: topic\ndescription: d\n---\n# G\n\n{ORPHAN}\n\nSzöveg.\n")
    safefs.write_bytes(ctx.notes_path, "wiki/assets/m/grafok-fejlec-1.webp", b"RIFF")   # the image exists


def test_an_orphan_figure_place_becomes_one_machine_item(world):
    from school_notes2.flows import orphan_places, work_pending
    from school_notes2.review import relations
    ctx, _ = world
    _orphan(ctx)
    assert orphan_places.new(ctx.notes_path) == [
        {"id": "grafok-fejlec", "page": ORPHAN_PAGE, "line": 8, "quote": ORPHAN}]
    assert work_pending.completion(ctx, tasks=[])[1].endswith(
        "2 hiányzó kép (1 függő ábra; 1 árva ábrahely, a következő javító futás gépi tételként kiosztja)")
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "moved")
    task.update(mode="fix", base="b")
    for _ in range(2):                         # a resumed preparation adds no second item
        orphan_places.record(ctx, task)
    items = [i for i in files.open_items(ctx.notes_path, "cron") if i["file"] == task.get("inspection_report")]
    assert len(items) == 1
    detail = relations.inventory(ctx.notes_path)["items"][items[0]["key"]]
    assert detail["file"] == ORPHAN_PAGE and detail["figure_id"] == "grafok-fejlec" and detail["quote"] == ORPHAN
    assert detail["hit_id"] == f"orphan-figure-place:{ORPHAN_PAGE}#grafok-fejlec"
    assert "Árva ábrahely" in (ctx.notes_path / items[0]["file"]).read_text()
    assert orphan_places.new(ctx.notes_path) == []
    assert work_pending.completion(ctx, tasks=[])[1].endswith(
        "(1 függő ábra; 1 árva ábrahely, amelynek már van gépi tétele)")
    # The item is ordinary text work: the figure is not pending, so it stays in a text call.
    grouping = calls.fix_assignments(ctx.notes_path, items, pending.load(ctx.notes_path))
    assert grouping[0]["open_review_items"] == items and grouping[0]["pending_figure_ids"] == []
    # A closed item (e.g. the writer disagreed) never brings the place back as a new item.
    from school_notes2.state import safefs
    rel = items[0]["file"]
    safefs.write_text(ctx.notes_path, rel, safefs.read_text(ctx.notes_path, rel).replace(
        f"{items[0]['item_id']}: open", f"{items[0]['item_id']}: disagree"))
    assert orphan_places.new(ctx.notes_path) == []


def test_a_marker_waiting_for_a_licence_is_not_an_orphan_place(world):
    """Review M1: a `figure-request` marker waits for its licence in docs/figure-requests.json."""
    from school_notes2.figures import licenses, requests
    from school_notes2.flows import orphan_places
    from school_notes2.state import safefs
    ctx, _ = world
    _orphan(ctx)
    repo = ctx.notes_path
    source = "sources/m/grafok.png"
    safefs.write_bytes(repo, source, b"PNG")
    safefs.write_text(repo, ORPHAN_PAGE, safefs.read_text(repo, ORPHAN_PAGE).replace(
        ORPHAN, "<!-- figure-request: grafok-engedely -->"))
    request = {"id": "grafok-engedely", "page": ORPHAN_PAGE, "source": source, "crop": "0,0,10,10",
               "purpose": "Gráf", "origin": "third-party"}
    safefs.write_json(repo, requests.PATH, requests.collect(repo, [request], [{"path": source, "original_sha256": "a" * 64}]))
    before = safefs.read_bytes(repo, requests.PATH)
    [active] = requests.active(repo)
    assert active["id"] == "grafok-engedely" and licenses.permission(repo, active) is None   # licence pending
    assert orphan_places.places(repo) == [] and orphan_places.new(repo) == []
    assert safefs.read_bytes(repo, requests.PATH) == before
    assert "<!-- figure-request: grafok-engedely -->" in safefs.read_text(repo, ORPHAN_PAGE)


def test_a_repeated_marker_on_one_page_is_one_place_and_the_quote_is_its_line(world):
    """Review m1 and m2: one item per key, and line and quote come from the same split."""
    from school_notes2.flows import orphan_places
    from school_notes2.state import safefs
    ctx, _ = world
    _orphan(ctx)
    repo = ctx.notes_path
    # A form feed is a line break for str.splitlines() but not for the line count.
    safefs.write_text(repo, ORPHAN_PAGE, safefs.read_text(repo, ORPHAN_PAGE).replace(
        "# G\n", "# G \x0c fej\n") + f"\nMég.\n\n{ORPHAN}\n")
    every = orphan_places.places(repo)
    assert every == [{"id": "grafok-fejlec", "page": ORPHAN_PAGE, "line": 8, "quote": ORPHAN}]
    assert len({orphan_places.key(p) for p in every}) == len(every)


def test_an_orphan_place_alone_starts_a_fix_run(tmp_path, held, monkeypatch):
    from types import SimpleNamespace
    from school_notes2.flows import fix
    from school_notes2.state import safefs
    from tests.flows.test_fix47 import PAGE
    ctx, _ = held
    safefs.write_text(ctx.notes_path, PAGE, safefs.read_text(ctx.notes_path, PAGE) + f"\n{ORPHAN}\n")
    ctx.worktree = lambda _: SimpleNamespace(run=lambda *a, **kw: None)
    ctx.bare = lambda: None
    ctx.task_root = lambda: tmp_path / "root"
    ctx.cfg.timeouts = SimpleNamespace(fetch_s=1)
    ctx.cfg.limits = SimpleNamespace(max_agents=3)
    monkeypatch.setattr(fix.repos, "fetch", lambda *a: None)
    monkeypatch.setattr(fix.repos, "rev", lambda *a: "main")
    monkeypatch.setattr(fix.correction_figures, "assignable", lambda *a: [])
    monkeypatch.setattr(fix.fix_progress, "available", lambda ctx, items, waiting: (items, waiting))
    monkeypatch.setattr(fix.fix_progress, "runnable_images", lambda ctx, waiting: waiting)
    monkeypatch.setattr(fix.reopen, "pending", lambda ctx: [])
    task = fix.next_task(ctx)
    assert task is not None and not task.get("recheck_only")
