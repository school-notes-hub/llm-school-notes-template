"""Controller decisions K-1, K-2, K-6, K-7 and shared unblock semantics."""

import pytest

from school_notes2.flows import night_topics
from school_notes2.llm import launch
from school_notes2.review import close, files, nightly, relations, topic_result, topics
from school_notes2.reader.units import slug
from school_notes2.state import phase, safefs
from school_notes2.state.errors import BadWork, NeedsOwner, Prerequisite
from tests.review.test_topics import FIX, IDENT, context, good, prepare


@pytest.mark.parametrize("learner", ["one", "two"])
def test_quiet_close_does_not_create_another_night(tmp_path, repos, log, monkeypatch, learner):
    repos.commit({"wiki/a.md": "# A\n\nText.\n"})
    task, ctx = prepare(tmp_path, repos, learner), context(tmp_path, repos, log, learner)
    monkeypatch.setattr(launch, "run_headless", good)
    night_topics.run(ctx, task)
    report, marker = close.close(task, repos.repo, repos.wt, IDENT)
    assert marker == report == repos.remote("main")
    assert prepare(tmp_path, repos, learner) is None
    assert prepare(tmp_path, repos, learner) is None
    assert repos.remote("main") == report


@pytest.mark.parametrize("mode", ["targeted", "full"])
@pytest.mark.parametrize("quote", ["Missing quote.", "Duplicate."])
def test_unlocated_fix_finding_is_owner(tmp_path, repos, mode, quote):
    repos.commit({"wiki/a.md": "# A\n\nOld.\n"})
    repos.commit({"wiki/a.md": "# A\n\nDuplicate.\n\nDuplicate.\n"}, FIX)
    if mode == "full":
        repos.commit({"wiki/a.md": "# A\n\nDuplicate.\n\nDuplicate.\n\nNew.\n"})
    task = prepare(tmp_path, repos)
    unit = task.get("units")[0]
    unit["mode"] = mode
    task.update(topic_results=[{"unit": unit, "receipt": {"status": "reviewed", "review": {
        "findings": [{"file": "wiki/a.md", "quote": quote, "problem": "Wrong", "relates_to": None}],
        "hits": []}}, "input": {"hits": []}}])
    value = topic_result.assemble(task, repos.repo, repos.wt_path)
    path = files.write_review(repos.wt_path, IDENT.date, value, "fake", "a", "b")
    item = relations.inventory(repos.wt_path)["items"][path.relative_to(repos.wt_path).as_posix() + "#R1"]
    assert item["status"] == "owner" and item["chain"] == 1 and item["unlocated"]


def test_markdown_second_search_retains_blame_line(tmp_path, repos):
    repos.commit({"wiki/a.md": "# A\n\nOld.\n"})
    head = repos.commit({"wiki/a.md": "# A\n\n**A [force](https://example.test)** is $F$.[^1]\n"}, FIX)
    nightly.fetch(repos.repo, 60)
    finding = {"file": "wiki/a.md", "quote": "A force is F."}
    actual = topic_result.chain(repos.repo, head, finding)
    assert actual["line"] == 3 and actual["chain"] == 1 and not actual["unlocated"]


@pytest.mark.parametrize("state, inherited", [("fixed", 0), ("settled", 0), ("fixed", 1)])
def test_relates_to_chain_cannot_be_lowered(tmp_path, state, inherited):
    safefs.write_text(tmp_path, "wiki/a.md", "# A\n")
    safefs.write_text(tmp_path, "docs/review/old.md", f"---\nitems: {{R1: {state}}}\n"
                      f"item_details: {{R1: {{file: wiki/a.md, chain: {inherited}}}}}\n---\n")
    value = {"verdict": "changes", "findings": [{"id": "R1", "file": "wiki/a.md", "problem": "Wrong",
              "chain": 0, "relates_to": "docs/review/old.md#R1"}]}
    path = files.write_review(tmp_path, IDENT.date, value, "fake", "a", "b")
    item = relations.inventory(tmp_path)["items"][path.relative_to(tmp_path).as_posix() + "#R1"]
    assert item["status"] == "owner" and item["chain"] == 1


@pytest.mark.parametrize("error", [Prerequisite, NeedsOwner])
def test_preflight_does_not_consume_crash_retry(tmp_path, repos, log, monkeypatch, error):
    repos.commit({"wiki/a.md": "# A\n"})
    task, ctx = prepare(tmp_path, repos), context(tmp_path, repos, log)
    def fail(*args, **kwargs):
        raise error("preflight")
    monkeypatch.setattr(launch, "run_headless", fail)
    for _ in range(3):
        with pytest.raises(error):
            night_topics.run(ctx, phase.load(task.dir))
        state = safefs.read_json(task.dir, f"nightly/{slug('wiki/a.md')}/call.json")
        assert state["attempts"] == []
    monkeypatch.setattr(launch, "run_headless", good)
    resumed = phase.load(task.dir)
    night_topics.run(ctx, resumed)
    assert resumed.get("all_topics_done") and not resumed.get("failed_topics")


def test_format_then_first_timeout_blocks_and_notifies(tmp_path, repos, log, monkeypatch):
    repos.commit({"wiki/a.md": "# A\n"})
    ctx = context(tmp_path, repos, log)
    notices = []
    ctx.mailer.send_once = lambda notice: notices.append(notice) or True
    def fail(*args, **kwargs):
        raise BadWork("format")
    monkeypatch.setattr(launch, "run_headless", fail)
    first = prepare(tmp_path, repos)
    night_topics.run(ctx, first)
    close.close(first, repos.repo, repos.wt, IDENT)
    def timeout(*args, **kwargs):
        raise launch.TimedOut("first timeout", details={"count": 1})
    monkeypatch.setattr(launch, "run_headless", timeout)
    second = prepare(tmp_path, repos)
    night_topics.run(ctx, second)
    assert second.get("failed_topics")[0]["count"] == 2
    assert second.get("blocked_topics")[0]["topic"] == "wiki/a.md"
    assert len(notices) == 1


def test_unblocked_is_sorted_and_clear_applies_to_old_records(tmp_path):
    entries = [{"topic": "wiki/z.md", "at": "3"}, {"topic": "wiki/a.md", "at": "2"}, {"topic": "wiki/b.md"}]
    assert [r["topic"] for r in topics.unblocked(entries, tmp_path, "one")] == ["wiki/a.md", "wiki/b.md", "wiki/z.md"]
    safefs.write_json(tmp_path, "one/nightly-cleared.json", {"at": "2"})
    assert topics.unblocked(entries, tmp_path, "one") == [entries[0]]


def test_preparation_never_materializes_unused_full_patch(tmp_path, repos, monkeypatch):
    repos.commit({"wiki/a.md": "# A\n"})
    def unused(*args):
        raise AssertionError("unused global patch/image inventory")
    monkeypatch.setattr(nightly, "build_patch", unused)
    monkeypatch.setattr(nightly, "images", unused)
    assert prepare(tmp_path, repos).get("units")
    with pytest.raises(TypeError):
        nightly.select(repos.repo, fetch_timeout=60, misspelled=True)


def test_missing_figure_close_resume_keeps_operational_state_and_status(tmp_path, repos, log, monkeypatch):
    from school_notes2.flows import status
    from school_notes2.review import figure_waiting
    from school_notes2.reader import notices
    repos.commit({"wiki/a.md": "# A\n\n![Ábra](assets/missing.png)\n"})
    task, ctx = prepare(tmp_path, repos), context(tmp_path, repos, log)
    monkeypatch.setattr(launch, "run_headless", good)
    night_topics.run(ctx, task)
    assert task.get("topic_results")[0]["figure_pending"]
    original = close._finish
    monkeypatch.setattr(close, "_finish", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        close.close(task, repos.repo, repos.wt, IDENT)
    report = repos.remote("main")
    monkeypatch.setattr(close, "_finish", original)
    close.close(phase.load(task.dir), repos.repo, repos.wt, IDENT)
    assert repos.remote("main") == report
    assert not relations.inventory(repos.wt_path)["items"]
    assert figure_waiting.active(repos.wt_path)
    assert notices.FIGURE in safefs.read_text(repos.wt_path, "wiki/a.md")
    nightly.fetch(repos.repo, 60)
    assert status._nightly_state(ctx)["pending_figures"]
