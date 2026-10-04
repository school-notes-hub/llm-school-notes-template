"""Nightly export, deferred figure verdicts and quiet blocked nights (Ú-1/2/4)."""

import pytest

from school_notes2.figures import review
from school_notes2.flows import night_topics, operation
from school_notes2.llm import guard, launch, timeouts
from school_notes2.reader import notices
from school_notes2.review import close, figure_waiting, night_figures, topics
from school_notes2.state import phase, safefs
from school_notes2.wiki import public
from tests.review.test_night_figures import png
from tests.conftest import record_render
from tests.review.test_topics import IDENT, context, good, prepare


@pytest.mark.parametrize("learner", ["one", "two"])
@pytest.mark.parametrize("error", [False, True])
def test_nightly_public_refresh_survives_close_crash(tmp_path, repos, log, monkeypatch, learner, error):
    page = "wiki/a.md"
    text = "# A\n\nTananyag.\n"
    repos.commit({page: text})
    # The H manifest is current, but the nightly page verdict removes a notice.
    notices.refresh(repos.laptop, [page])
    public.write(repos.laptop, lambda _: None)
    repos.commit({page: safefs.read_text(repos.laptop, page),
                  "publication/public.json": safefs.read_text(repos.laptop, "publication/public.json")})
    task, ctx = prepare(tmp_path, repos, learner), context(tmp_path, repos, log, learner)
    monkeypatch.setattr(launch, "run_headless", good)
    night_topics.run(ctx, task)
    if error:
        def fail(*args):
            raise public.PublicError(["wiki/assets/unknown.png"])
        monkeypatch.setattr(public, "write", fail)
    original = close._commit
    monkeypatch.setattr(close, "_commit", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        close.close(task, repos.repo, repos.wt, IDENT)
    monkeypatch.setattr(close, "_commit", original)
    resumed = phase.load(task.dir)
    close.close(resumed, repos.repo, repos.wt, IDENT)
    assert resumed.phase == "done"
    assert "⏳" not in safefs.read_text(repos.wt_path, page)
    if error:
        notes = safefs.read_json(task.dir, "review.json")["owner_notes"]
        assert len(notes) == 1 and "unknown.png" in notes[0]
        reports = safefs.glob(repos.wt_path, "docs/review", "docs/review/*-review.md")
        assert len(reports) == 1
        assert safefs.read_text(repos.wt_path, reports[0]).count(notes[0]) == 1
    else:
        manifest = public.read_existing(repos.wt_path)
        assert all(p["sha256"] == public.sha256(repos.wt_path, p["path"]) for p in manifest["pages"])
        assert "publication/public.json" in repos.wt.out("show", "--format=", "--name-only", "HEAD")


@pytest.mark.parametrize("learner", ["one", "two"])
@pytest.mark.parametrize("suspended", [False, True])
def test_missing_figure_retried_after_suspension_and_next_night(tmp_path, repos, log, monkeypatch, learner, suspended):
    page, asset = "wiki/a.md", "wiki/assets/a.png"
    safefs.write_bytes(repos.laptop, asset, png())
    record_render(repos.laptop, asset)
    repos.commit({page: "# A\n\n![Ábra](assets/a.png)\n", asset: png()})
    ctx = context(tmp_path, repos, log, learner)
    monkeypatch.setattr(launch, "run_headless", good)
    monkeypatch.setattr(night_topics, "Renderer", lambda *a, **kw: lambda *args: png())
    original = review.run_batch
    calls = []
    def invoke(run, **kw):
        def outcome(configured):
            calls.append(configured)
            if len(calls) == 1:
                raise launch.TimedOut("timeout")
            assigned = safefs.read_json(configured.mounts.in_dir, "assigned.json")
            value = {"figures": [{**f, "verdict": "accept", "observed": "Ábra.", "defects": [],
                                    "text_mismatch": [], "relates_to": None} for f in assigned["figures"]],
                     "owner_notes": []}
            from types import SimpleNamespace
            return SimpleNamespace(output=value)
        return guard.headless(run, outcome)
    monkeypatch.setattr(review, "run_batch", lambda *a, **kw: original(*a, **kw, invoke=invoke))
    first = prepare(tmp_path, repos, learner)
    night_topics.run(ctx, first)
    assert not first.get("all_topics_done")
    close.close(first, repos.repo, repos.wt, IDENT)
    assert topics.load(repos.wt_path)["done_topics"] == []
    assert figure_waiting.active(repos.wt_path)
    assert notices.FIGURE in safefs.read_text(repos.wt_path, page)
    marker = repos.remote("claude-reviewed")
    # A suspended role never invokes a harness and still does not mark the topic done.
    if suspended:
        safefs.write_json(ctx.cfg.state_dir, f"{learner}/timeouts.json", {
            "figure-review": {"count": 2, "suspended": True}})
        token = operation.CURRENT.set((ctx, False, {}))
        try:
            second = prepare(tmp_path, repos, learner)
            night_topics.run(ctx, second)
        finally:
            operation.CURRENT.reset(token)
        close.close(second, repos.repo, repos.wt, IDENT)
        assert len(calls) == 1 and not second.get("all_topics_done")
        assert repos.remote("claude-reviewed") == marker
        timeouts.clear(ctx, "figure-review")
    third = prepare(tmp_path, repos, learner)
    night_topics.run(ctx, third)
    assert third.get("all_topics_done") and len(calls) == 2
    close.close(third, repos.repo, repos.wt, IDENT)
    assert not figure_waiting.active(repos.wt_path)
    assert "⏳" not in safefs.read_text(repos.wt_path, page)
    assert repos.remote("claude-reviewed") == repos.remote("main")


@pytest.mark.parametrize("learner", ["one", "two"])
@pytest.mark.parametrize("changed", [False, True])
def test_empty_blocked_night_only_commits_changed_state(tmp_path, repos, log, monkeypatch, learner, changed):
    repos.commit({"wiki/a.md": "# A\n"})
    ctx = context(tmp_path, repos, log, learner)
    def fail(*args, **kwargs):
        raise launch.TimedOut("timeout")
    monkeypatch.setattr(launch, "run_headless", fail)
    for _ in range(2):
        task = prepare(tmp_path, repos, learner)
        night_topics.run(ctx, task)
        close.close(task, repos.repo, repos.wt, IDENT)
    head, marker = repos.remote("main"), repos.remote("claude-reviewed")
    before = safefs.read_bytes(repos.wt_path, topics.STATE)
    task = prepare(tmp_path, repos, learner)
    night_topics.run(ctx, task)
    assert not task.get("topic_results")
    if changed:
        task.update(failed_topics=[])
    original = close._finish
    monkeypatch.setattr(close, "_finish", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        close.close(task, repos.repo, repos.wt, IDENT)
    monkeypatch.setattr(close, "_finish", original)
    resumed = phase.load(task.dir)
    close.close(resumed, repos.repo, repos.wt, IDENT)
    assert resumed.phase == "done"
    assert (repos.remote("main") != head) == changed
    assert repos.remote("claude-reviewed") == marker
    assert (safefs.read_bytes(repos.wt_path, topics.STATE) != before) == changed
