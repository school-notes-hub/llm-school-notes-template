"""K-12, K-14, K-15: malformed paths and inherited defects never trap a run."""

from types import SimpleNamespace

import pytest

from school_notes2.figures import pending
from school_notes2.flows import inspection, review_phases
from school_notes2.reader import calls, contracts, notices, verdicts
from school_notes2.review import relations
from school_notes2.state import phase, safefs
from school_notes2.wiki.check_result import check_result
from .helpers import finding
from .helpers import pass1
from .test_review_fixes import figure


@pytest.mark.parametrize("path", ["/work/m/summary.md", "../wiki/m/summary.md", "wiki/m/missing.md"])
def test_unassigned_unknown_path_does_not_fail_or_recur(setup, monkeypatch, path):
    ctx, task, page = setup
    invoked = []
    def invoke(*args, **kwargs):
        invoked.append(1)
        return SimpleNamespace(output={**pass1(page), "findings": [finding(path)]})
    monkeypatch.setattr(calls.launch, "run_headless", invoke)
    inspection.prepare(ctx, task)
    inspection.inspect(ctx, task)
    inspection.inspect(ctx, phase.load(task.dir))
    assert invoked == [1]
    assert not relations.inventory(ctx.notes_path)["items"]
    assert path in task.get("reader_owner_notes")[0]
    assert verdicts.valid(ctx.notes_path, page) is not None
    task.set_phase("review_ready")
    review_phases.advance(ctx, task, lambda _: None)
    assert task.phase == "finishing" and task.data["needs_owner"] is None


def test_unreached_pending_figure_stays_pending_without_error(setup):
    ctx, task, page = setup
    brief, _ = figure(ctx, task, page)
    entry = pending.record(ctx.notes_path, brief, "previous", [])
    base = {p: safefs.read_bytes(ctx.notes_path, p) for p in safefs.walk_files(ctx.notes_path)}
    fetch = {"packages": [], "pages": [], "pending_figures": [entry]}
    safefs.unlink(ctx.notes_path, ".school-notes/figures/f/figure.json")
    assert not check_result(ctx.notes_path, {"status": "done"}, fetch, set(), base_content=base.get)  # #18
    safefs.write_json(ctx.notes_path, ".school-notes/figures/f/figure.json", {"state": "failed", "reason": "Nem sikerült"})
    assert not check_result(ctx.notes_path, {"status": "done"}, fetch, set(), base_content=base.get)


def test_inherited_broken_notebook_drawing_is_not_a_p1_accounting_error(setup):
    ctx, task, page = setup
    brief, candidate = figure(ctx, task, page)
    brief.update(kind="notebook-drawing", source_image={"path": candidate["asset"], "crop": [0, 0, 20, 10]})
    safefs.write_json(ctx.notes_path, ".school-notes/figures/f/figure.json", {"state": "failed", "reason": "Missing source"})
    safefs.write_json(ctx.notes_path, ".school-notes/figures/f.json", brief)
    entry = pending.record(ctx.notes_path, brief, "previous", [])
    safefs.unlink(ctx.notes_path, page)
    base = {p: safefs.read_bytes(ctx.notes_path, p) for p in safefs.walk_files(ctx.notes_path)}
    result = {"status": "done", "figures": [{k: brief[k] for k in ("id", "kind", "page")}],
              "notebook_drawings": [{"figure": "f", "source": candidate["asset"], "crop": "whole"}]}
    fetch = {"packages": [], "pages": [], "pending_figures": [entry]}
    assert not check_result(ctx.notes_path, result, fetch, set(), base_content=base.get)


def test_ignored_paths_are_named_in_format_retry(setup):
    ctx, task, page = setup
    folder = task.dir / "reader"
    seen = []
    paths = ["wiki/m/missing.md", "../wiki/m/topic.md"]
    def invoke(*args, **kwargs):
        seen.append(1)
        if len(seen) == 1:
            return SimpleNamespace(output=pass1(page, [{**finding(p), "id": f"F-{n}"}
                                                       for n, p in enumerate(paths, 1)]))
        error = safefs.read_json(folder, "in/format-error.json")["error"]
        assert "changes page verdict needs a finding" in error
        return SimpleNamespace(output=pass1(page, [finding(page)]))
    result = calls.run(ctx.notes_path, ctx.notes_path, folder, "reader-1", {"pages": [{"file": page}]},
                       inspection.role(ctx, task), log=ctx.log, invoke=invoke)
    assert result["status"] == "reviewed" and len(seen) == 2


@pytest.mark.parametrize("path", ["/work/m/topic.md", "m/topic.md"])
def test_context_path_recovered_after_crash_uses_internal_allowlist(setup, path):
    ctx, task, page = setup
    other = "wiki/m/assigned.md"
    folder = task.dir / "reader"
    folder.mkdir()
    safefs.write_json(folder, "state.json", {"status": "ready", "attempts": ["running"]})
    safefs.write_json(folder, "out/review.json", {**pass1(other), "findings": [finding(path)]})
    def forbidden(*args, **kwargs):
        pytest.fail("completed call repeated")
    result = calls.run(ctx.notes_path, ctx.notes_path, folder, "reader-1", {"pages": [{"file": other}]},
                       inspection.role(ctx, task), log=ctx.log, invoke=forbidden,
                       allowed_paths={page, other})
    assert result["review"]["findings"] == [finding(page)]
    assert result["review"]["owner_notes"] == []


@pytest.mark.parametrize("path", ["/work/m/../m/topic.md", "./m/topic.md", "/wiki/m/topic.md", "topic.md"])
def test_other_path_spellings_remain_owner_notes(setup, path):
    _, _, page = setup
    result = contracts.check({**pass1(page), "findings": [finding(path)]}, "reader-1",
                             {"pages": [{"file": page}]})
    assert result["findings"] == [] and path in result["owner_notes"][0]


def test_final_notices_leave_public_json_current(setup, monkeypatch):
    """A ⏳ notice written by final_keys after step 6 must not leave a stale page hash in
    public.json (the site build rejects it: VM finish 2026-10-04)."""
    from school_notes2.flows import steps
    from school_notes2.wiki import public
    ctx, task, page = setup
    steps.write_public(ctx, task)
    def refresh(repo, pages, **kwargs):
        safefs.write_text(repo, page, safefs.read_text(repo, page) + "\n" + notices.PAGE + "\n")
        return [page]
    monkeypatch.setattr(review_phases.notices, "refresh", refresh)
    task.update(review_complete=True)
    review_phases.final_keys(ctx, task)
    repo = ctx.notes_path
    rights = public.either(public.render_rights(repo), public.media_receipt_rights(repo))
    assert public.write(repo, rights) is False
    assert task.get("tool_writes")["publication/public.json"]


def test_final_keys_repairs_public_json_after_an_interrupted_notice(setup, monkeypatch):
    """The notice is already on the page (an earlier final_keys stopped before public.json):
    refresh writes nothing now, yet public.json must become current."""
    from school_notes2.flows import steps
    from school_notes2.wiki import public
    ctx, task, page = setup
    steps.write_public(ctx, task)
    safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "\n" + notices.PAGE + "\n")
    monkeypatch.setattr(review_phases.notices, "refresh", lambda repo, pages, **kwargs: [])
    task.update(review_complete=True)
    review_phases.final_keys(ctx, task)
    repo = ctx.notes_path
    rights = public.either(public.render_rights(repo), public.media_receipt_rights(repo))
    assert public.write(repo, rights) is False
