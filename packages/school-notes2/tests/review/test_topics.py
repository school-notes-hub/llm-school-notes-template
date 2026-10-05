"""T-095/T-037: real local Git, fake roles, no network or learner-specific behavior."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from school_notes2.config import Role, Harness
from school_notes2.flows import night_topics
from school_notes2.llm import launch
from school_notes2.reader import units, verdicts
from school_notes2.review import close, nightly, topic_call, topic_input, topic_result, topics
from school_notes2.state import phase, safefs
from school_notes2.state.errors import BadWork, WaitingQuota
from school_notes2.wiki import frontmatter

from .conftest import sh

FIX = "repair\n\nSchool-Notes-Run: fix"
IDENT = close.Identity("learner", "fake/high", "2", "2026-10-04", "2026-10-04T04:00:00+02:00")


def prepare(tmp_path, repos, learner="one"):
    return nightly.prepare(tmp_path / "srv", learner, repos.repo, repos.wt,
                           fetch_timeout=60, rasterize=lambda *args: [])


def context(tmp_path, repos, log, learner="one"):
    (tmp_path / "state").mkdir(exist_ok=True)
    role = Role("claude-review", "fake", "high", 5400)
    harness = Harness("claude-review", [], [], [])
    cfg = SimpleNamespace(state_dir=tmp_path / "state", role=lambda name: (role, harness),
                          roles={"reviewer": role}, limits=SimpleNamespace(max_agents=3),
                          provider_domains=(), browser=tmp_path / "browser",
                          timeouts=SimpleNamespace(rasterize_s=2))
    return SimpleNamespace(name=learner, cfg=cfg, bare=lambda: repos.repo, worktree=lambda kind: repos.wt,
                           student=SimpleNamespace(grade=9), image_tag=lambda: "fake", release=lambda: tmp_path,
                           log=log, mailer=SimpleNamespace(send_once=lambda notice: True))


def good(run, **kwargs):
    assigned = safefs.read_json(run.mounts.in_dir, "assigned.json")
    value = {"verdict": "ok", "pages": [{"file": p, "verdict": "ok"} for p in assigned["pages"]],
             "findings": [], "owner_notes": [], "hits": [
                 {"hit_id": h, "verdict": "megengedett", "reason": "érthető", "covered_by": None}
                 for h in assigned["hits"]], "items": [
                 {"key": i["key"], "verdict": {"fixed": "ok", "disagree": "accept"}.get(i["status"], "open"),
                  "answer": "ellenőrizve"} for i in assigned["items"]]}
    safefs.write_json(run.mounts.out_dir, "review.json", value)
    return SimpleNamespace(output=value)


@pytest.mark.parametrize("learner", ["one", "two"])
def test_quota_resume_only_missing_topics_and_pinned_head(tmp_path, repos, log, monkeypatch, learner):
    head = repos.commit({"wiki/a.md": "# A\n\nElső.\n", "wiki/b.md": "# B\n\nMásodik.\n"})
    task, ctx = prepare(tmp_path, repos, learner), context(tmp_path, repos, log, learner)
    called = []
    def invoke(run, **kw):
        called.append(run.label)
        if run.label == units.slug("wiki/b.md") and called.count(run.label) == 1:
            raise WaitingQuota("quota")
        return good(run)
    monkeypatch.setattr(launch, "run_headless", invoke)
    with pytest.raises(WaitingQuota):
        night_topics.run(ctx, task)
    repos.commit({"wiki/c.md": "Új, a következő éjszakáé.\n"})
    resumed = phase.load(task.dir)
    nightly.resume_prepared(resumed, repos.repo, repos.wt, lambda *a: [])
    night_topics.run(ctx, resumed)
    assert called == [units.slug("wiki/a.md"), units.slug("wiki/b.md"), units.slug("wiki/b.md")]
    assert resumed.get("H") == head and resumed.get("all_topics_done")
    r, m = close.close(resumed, repos.repo, repos.wt, IDENT)
    assert m == head and r != head
    assert len(sh("git", "--git-dir", str(repos.origin), "log", "--format=%s", f"{head}..main").splitlines()) == 2
    assert verdicts.valid(repos.wt_path, "wiki/a.md") is not None
    assert topics.load(repos.wt_path)["done_topics"] == []


def test_targeted_final_state_once_and_mixed_commit_full(tmp_path, repos):
    base = repos.commit({"wiki/a.md": "# A\n\nRégi.\n", "wiki/b.md": "# B\n"})
    sh("git", "push", "-q", "origin", "HEAD:claude-reviewed", cwd=repos.laptop)
    repos.commit({"wiki/a.md": "# A\n\nJavítás 1.\n"}, FIX)
    head = repos.commit({"wiki/a.md": "# A\n\nJavítás 2.\n"}, FIX)
    task = prepare(tmp_path, repos)
    assert [(u["topic"], u["mode"]) for u in task.get("units")] == [("wiki/a.md", "targeted")]
    unit = task.get("units")[0]
    assert unit["assigned_pages"] == ["wiki/a.md"]
    patch = topics.patch(repos.repo, unit, head)
    assert "Javítás 2" in patch and "Javítás 1" not in patch
    repos.commit({"wiki/a.md": "# A\n\nEmberi változás.\n"}, "manual")
    next_task = prepare(tmp_path, repos, "two")
    assert next_task.get("units")[0]["mode"] == "full"


def test_actual_tool_diff_and_initial_report_do_not_start_llm(tmp_path, repos):
    repos.commit({"wiki/a.md": "# A\n", "docs/review/report.md": "---\nitems: {R1: open}\n---\n### R1 – wiki/a.md\n"})
    sh("git", "push", "-q", "origin", "HEAD:claude-reviewed", cwd=repos.laptop)
    repos.commit({"wiki/a.md": "# A\n\n<!-- school-notes:generated pending -->\nx\n<!-- /school-notes:generated -->\n",
                  "sources/source.jpg": b"x", "docs/evidence/pages/a.md": "evidence"}, "not a tool title")
    task = prepare(tmp_path, repos)
    assert task.get("units") == []


@pytest.mark.parametrize("report_after_marker", [False, True])
def test_closure_only_assigns_topic_and_fix_origin(tmp_path, repos, report_after_marker):
    report = "---\nitems: {R1: open}\nitem_details: {R1: {file: wiki/a.md, round: 1, chain: 0}}\n---\n### R1 – wiki/a.md\nHiba.\n"
    initial = {"wiki/a.md": "# A\n"}
    if not report_after_marker:
        initial["docs/review/old.md"] = report
    repos.commit(initial)
    sh("git", "push", "-q", "origin", "HEAD:claude-reviewed", cwd=repos.laptop)
    if report_after_marker:
        repos.commit({"docs/review/old.md": report}, "report")
    repos.commit({"docs/review/old.md": report.replace("R1: open", "R1: fixed")}, FIX)
    task = prepare(tmp_path, repos)
    unit = task.get("units")[0]
    data = topic_input.prepare(repos.repo, repos.wt_path, task, unit, task.dir / "in")
    assert unit["mode"] == "targeted" and data["items"][0]["fix_commit"]
    answer = {"key": "docs/review/old.md#R1", "verdict": "not-ok", "answer": "Hibás javítás."}
    _, owner = topic_result.apply_item(repos.wt_path, data["items"][0], answer)
    assert owner is None
    meta = frontmatter.split((repos.wt_path / "docs/review/old.md").read_text()).meta
    assert meta["items"]["R1"] == "open" and meta["item_details"]["R1"]["chain"] == 1


def test_blame_chain_even_full_mode_and_missing_quote(tmp_path, repos):
    repos.commit({"wiki/a.md": "# A\n\nRégi.\n"})
    repos.commit({"wiki/a.md": "# A\n\nJavított, de hibás.\n"}, FIX)
    head = repos.commit({"wiki/a.md": "# A\n\nJavított, de hibás.\n\nÚj anyag.\n"}, "new source")
    task = prepare(tmp_path, repos)
    assert task.get("units")[0]["mode"] == "full"
    finding = {"file": "wiki/a.md", "quote": "Javított, de hibás."}
    assert topic_result.chain(repos.repo, head, finding)["chain"] == 1
    assert topic_result.chain(repos.repo, head, {**finding, "quote": "Új anyag."})["chain"] == 0
    result = topic_result.chain(repos.repo, head, {**finding, "quote": "Nincs ilyen."})
    assert result["unlocated"] and result["chain"] == 0


def test_shared_image_item_is_assigned_only_to_primary_topic(tmp_path, repos):
    report = "---\nitems: {R1: open}\nitem_details: {R1: {file: wiki/assets/a.png}}\n---\n### R1 – wiki/assets/a.png\nHiba.\n"
    repos.commit({"wiki/a.md": "# A\n\n![Rajz](assets/a.png)\n",
                  "wiki/b.md": "# B\n\n![Rajz](assets/a.png)\n",
                  "wiki/assets/a.png": b"image", "docs/review/old.md": report})
    task = prepare(tmp_path, repos)
    assignments = [topic_input.prepare(repos.repo, repos.wt_path, task, unit, task.dir / str(i))["assigned"]
                   for i, unit in enumerate(task.get("units"))]
    assert [a["items"] for a in assignments] == [[{"key": "docs/review/old.md#R1", "status": "open"}], []]


def test_receipt_crash_resumes_without_call(tmp_path, repos, log, monkeypatch):
    repos.commit({"wiki/a.md": "# A\n"})
    task, ctx = prepare(tmp_path, repos), context(tmp_path, repos, log)
    original = topic_call._save
    calls = []
    def invoke(run, **kw):
        calls.append(run.label)
        return good(run)
    def crash(*args):
        raise KeyboardInterrupt()
    monkeypatch.setattr(launch, "run_headless", invoke)
    monkeypatch.setattr(topic_call, "_save", crash)
    with pytest.raises(KeyboardInterrupt):
        night_topics.run(ctx, task)
    monkeypatch.setattr(topic_call, "_save", original)
    night_topics.run(ctx, phase.load(task.dir))
    assert len(calls) == 1


def test_second_timeout_blocks_only_topic_done_topics_have_own_base(tmp_path, repos, log, monkeypatch):
    repos.commit({"wiki/a.md": "# A\n", "wiki/b.md": "# B\n"})
    base = repos.remote("claude-reviewed")
    ctx = context(tmp_path, repos, log)
    count = 0
    called = []
    def invoke(run, **kw):
        nonlocal count
        called.append(run.label)
        if run.label == units.slug("wiki/a.md"):
            count += 1
            raise launch.TimedOut("timeout", details={"count": count})
        return good(run)
    monkeypatch.setattr(launch, "run_headless", invoke)
    first = prepare(tmp_path, repos)
    night_topics.run(ctx, first)
    close.close(first, repos.repo, repos.wt, IDENT)
    assert repos.remote("claude-reviewed") == base
    assert topics.load(repos.wt_path)["done_topics"] == [{"topic": "wiki/b.md", "commit": first.get("H")}]
    second = prepare(tmp_path, repos)
    night_topics.run(ctx, second)
    close.close(second, repos.repo, repos.wt, IDENT)
    assert called.count(units.slug("wiki/b.md")) == 1
    assert second.data["needs_owner"] is None
    assert topics.load(repos.wt_path)["blocked_topics"][0]["since_commit"] == base
    third = prepare(tmp_path, repos)
    night_topics.run(ctx, third)
    assert count == 2
    # Owner clear makes the blocked topic eligible without touching done topics.
    safefs.write_json(ctx.cfg.state_dir, "one/nightly-cleared.json", {"at": "9999"})
    third.update(topic_results=[])
    monkeypatch.setattr(launch, "run_headless", good)
    night_topics.run(ctx, third)
    assert third.get("all_topics_done")


def test_prepared_crash_rebuilds_same_units(tmp_path, repos):
    repos.commit({"wiki/a.md": "# A\n"})
    task = prepare(tmp_path, repos)
    expected = task.get("units")
    task.update(units=None)
    repos.commit({"wiki/b.md": "# B\n"})
    nightly.resume_prepared(phase.load(task.dir), repos.repo, repos.wt, lambda *a: [])
    assert phase.load(task.dir).get("units") == expected


def test_warning_accounting_is_complete(tmp_path, repos):
    repos.commit({"wiki/a.md": "# A\n\nA 3. dián látszik.\n"})
    task = prepare(tmp_path, repos)
    data = topic_input.prepare(repos.repo, repos.wt_path, task, task.get("units")[0], task.dir / "in")
    assert data["assigned"]["hits"]
    value = {"verdict": "ok", "pages": [{"file": "wiki/a.md", "verdict": "ok"}], "items": [], "hits": [], "findings": [], "owner_notes": []}
    with pytest.raises(ValueError, match="exactly one"):
        topic_call.check(value, data["assigned"], repos.wt_path)


def test_report_push_crash_resumes_without_duplicate_commit(tmp_path, repos, log, monkeypatch):
    repos.commit({"wiki/a.md": "# A\n"})
    task, ctx = prepare(tmp_path, repos), context(tmp_path, repos, log)
    monkeypatch.setattr(launch, "run_headless", good)
    night_topics.run(ctx, task)
    original = close._finish
    monkeypatch.setattr(close, "_finish", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        close.close(task, repos.repo, repos.wt, IDENT)
    commit = repos.remote("main")
    monkeypatch.setattr(close, "_finish", original)
    resumed = phase.load(task.dir)
    close.close(resumed, repos.repo, repos.wt, IDENT)
    assert resumed.phase == "done" and repos.remote("main") == commit
    assert repos.remote("claude-reviewed") == commit


@pytest.mark.parametrize("failure, expected", [(BadWork("invalid"), 2), (launch.TimedOut("timeout"), 1)])
def test_bounded_retry_and_failed_receipt_resume(tmp_path, repos, log, monkeypatch, failure, expected):
    repos.commit({"wiki/a.md": "# A\n"})
    task, ctx = prepare(tmp_path, repos), context(tmp_path, repos, log)
    invoked = []
    def invoke(run, **kw):
        invoked.append(run)
        raise failure
    monkeypatch.setattr(launch, "run_headless", invoke)
    night_topics.run(ctx, task)
    night_topics.run(ctx, phase.load(task.dir))
    assert len(invoked) == expected
    assert not task.get("all_topics_done")


def test_template_allows_native_subagents_and_nightly_default():
    from school_notes2.config import default_harnesses, _role, Harness
    table = default_harnesses()["claude-review"]
    argv = table["headless"]
    assert "--tools" not in argv and "Agent" not in argv and "Task" not in argv
    assert "--dangerously-skip-permissions" in argv and "--mcp-config" not in argv
    role = _role("reviewer", {"harness": "claude-review", "model": "fake", "effort": "high"}, {"claude-review": object()})
    assert role.timeout_s == 5400


def test_done_topic_uses_own_base_even_when_global_diff_is_empty(tmp_path, repos):
    base = repos.commit({"wiki/a.md": "# A\n\nOriginal.\n"})
    done = repos.commit({"wiki/a.md": "# A\n\nReviewed.\n"})
    head = repos.commit({"wiki/a.md": "# A\n\nOriginal.\n"}, FIX)
    nightly.fetch(repos.repo, 60)
    repos.wt.run("switch", "--detach", head)
    grouped, skipped = topics.plan(repos.repo, repos.wt_path, base, head,
                                   {"done_topics": [{"topic": "wiki/a.md", "commit": done}]})
    assert [(u["topic"], u["base"], u["mode"]) for u in grouped] == [("wiki/a.md", done, "targeted")]


def test_sources_follow_lesson_index_then_source_order(tmp_path):
    from school_notes2.wiki import markers
    root = tmp_path
    safefs.write_text(root, "wiki/s/a.md", "---\ntype: concept\n---\n# A\n")
    for name, sources in (("first", ["z.jpg", "a.jpg"]), ("second", ["b.jpg"])):
        meta = {"type": "lesson-notes", "lessons": [{"topics": ["a.md"]}],
                "sources": [{"resource": "../../sources/s/" + s} for s in sources]}
        safefs.write_text(root, f"wiki/s/{name}.md", frontmatter.set_keys("# Óra\n", meta))
        for src in sources:
            safefs.write_bytes(root, "sources/s/" + src, b"source")
    safefs.write_text(root, "wiki/s/index.md", "# S\n" + markers.wrap("lessons", "[2](second.md)\n[1](first.md)\n"))
    assert topic_input.sources(root, "wiki/s/a.md") == ["sources/s/b.jpg", "sources/s/z.jpg", "sources/s/a.jpg"]


@pytest.mark.parametrize("first_line", ["A 3. dián látszik.", "[^web]: A 3. dián látszik. https://example.org"])
def test_allowed_hits_and_existing_review_items_are_not_reassigned(tmp_path, repos, first_line):
    from school_notes2.review import warnings
    repos.commit({"wiki/a.md": f"# A\n\n{first_line}\n\nA 4. dián látszik.\n"})
    task = prepare(tmp_path, repos)
    unit = task.get("units")[0]
    data = topic_input.prepare(repos.repo, repos.wt_path, task, unit, task.dir / "in")
    assert len(data["hits"]) == 2
    first, second = sorted(data["hits"], key=lambda h: h["line"])
    warnings.record(repos.wt_path, [first], [{"id": first["id"], "verdict": "megengedett", "reason": "allowed"}])
    from school_notes2.review import files
    files.write_review(repos.wt_path, "2026-10-01", {"verdict": "changes", "findings": [
        {"id": "R1", "file": "wiki/a.md", "problem": "Already assigned", "hit_id": second["id"], "relates_to": None}]},
        "fake", "a", "b")
    repeated = topic_input.prepare(repos.repo, repos.wt_path, task, unit, task.dir / "filtered")
    assert repeated["assigned"]["hits"] == []
    assert len(repeated["assigned"]["items"]) == 1


def test_disagreement_keep_is_round_two_without_chain(tmp_path, repos):
    from school_notes2.review import files, relations
    repos.commit({"wiki/a.md": "# A\n"})
    task = prepare(tmp_path, repos)
    report = files.write_review(repos.wt_path, "2026-10-01", {"verdict": "changes", "findings": [
        {"id": "R1", "file": "wiki/a.md", "problem": "Issue", "relates_to": None}]}, "fake", "a", "b")
    path = report.relative_to(repos.wt_path).as_posix()
    files.apply_closure(repos.wt_path, "fix", [{"file": path, "item_id": "R1", "status": "disagree", "note": "Reason"}], [])
    item = {"key": path + "#R1", "verdict": "keep", "answer": "Still wrong"}
    _, owner = topic_result.apply_item(repos.wt_path, {"status": "disagree", "fix_commit": True}, item)
    record = relations.inventory(repos.wt_path)["items"][path + "#R1"]
    assert owner is None and record["status"] == "open" and record["round"] == 2 and record["chain"] == 0
