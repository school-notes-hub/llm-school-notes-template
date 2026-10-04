from types import SimpleNamespace

import pytest

from school_notes2.flows import correction, inspection, recheck, review_phases, steps
from school_notes2.llm import launch
from school_notes2.reader import calls, notices, units, verdicts
from school_notes2.review import files, relations
from school_notes2.state import phase, safefs
from school_notes2.state.errors import BadWork, WaitingQuota
from school_notes2.wiki import frontmatter, source_refs
from .test_reader import pass1


def install_reader(monkeypatch, page, *, findings=None):
    invoked = []
    def fake(repo, view, folder, stage, assigned, configured, **kw):
        invoked.append(stage)
        if stage == "reader-1":
            review = pass1(page, findings)
        elif stage == "reader-2":
            review = {"hits": [{"hit_id": h, "verdict": "hiba", "covered_by": "F-1" if findings else None,
                                 "reason": "Hibás"} for h in assigned["hits"]], "owner_notes": []}
        else:
            review = {"items": [{"key": i["key"], "verdict": "ok" if i["status"] == "fixed" else "keep",
                                   "answer": "Indok"} for i in assigned["items"]],
                      "hits": [{"hit_id": h, "verdict": "megengedett", "reason": "rendben"} for h in assigned["hits"]],
                      "owner_notes": []}
        return {"status": "reviewed", "model": "model/high", "review": review}
    monkeypatch.setattr(calls, "run", fake)
    return invoked


def finding(page):
    return {"id": "F-1", "file": page, "quote": "A test lefelé gyorsul.", "category": "olvasói lyuk",
            "problem": "Hiányzik az ok.", "suggestion": "Magyarázd el.", "relates_to": None}


@pytest.mark.parametrize("boundary", ["figures", "inspecting", "correcting", "rechecking", "review_ready"])
def test_t095_every_phase_resumes_after_completed_action(setup, monkeypatch, boundary):
    ctx, task, page = setup
    invoked = install_reader(monkeypatch, page, findings=[finding(page)])
    corrections = []
    def fix(ctx, task, restores=None):
        corrections.append(1)
        path = task.get("inspection_report")
        closure = {"file": path, "item_id": "R1", "status": "fixed", "note": "Javítva"}
        correction.snapshot(ctx.notes_path, inspection.folder(task) / "correction")
        files.apply_closure(ctx.notes_path, task.run_id + "-fix", [closure], [{"file": path, "item_id": "R1"}])
        task.update(correction_result={"status": "done", "review_closure": [closure]})
    monkeypatch.setattr(correction, "run", fix)
    original = task.set_phase
    fired = []
    def crash(next_phase, **kw):
        if task.phase == boundary and not fired:
            fired.append(1)
            raise RuntimeError("crash before next phase")
        original(next_phase, **kw)
    monkeypatch.setattr(task, "set_phase", crash)
    with pytest.raises(RuntimeError, match="crash"):
        review_phases.advance(ctx, task, lambda _: None)
    resumed = phase.load(task.dir)
    review_phases.advance(ctx, resumed, lambda _: None)
    assert resumed.phase == "finishing" and resumed.get("review_complete")
    assert invoked.count("reader-1") == 1
    assert invoked.count("recheck") == 1
    assert relations.inventory(ctx.notes_path)["items"][resumed.get("inspection_report") + "#R1"]["status"] == "fixed"


def test_two_pass_merge_and_empty_list_skips_second_call(setup, monkeypatch):
    ctx, task, page = setup
    invoked = install_reader(monkeypatch, page, findings=[finding(page)])
    task.update(check_warnings=[{"id": "H1", "file": page, "line": 7, "message": "jelzés", "severity": "warning"}])
    inspection.prepare(ctx, task)
    inspection.inspect(ctx, task)
    assert invoked == ["reader-1", "reader-2"]
    assert list(relations.inventory(ctx.notes_path)["items"]) == [task.get("inspection_report") + "#R1"]
    task.update(attempt=2, check_warnings=[])
    inspection.inspect(ctx, task)
    assert invoked == ["reader-1", "reader-2", "reader-1"]


def test_p6_without_p5_after_open_or_rollback(setup, monkeypatch):
    ctx, task, page = setup
    invoked = install_reader(monkeypatch, page, findings=[finding(page)])
    def rollback(ctx, task, restores=None):
        task.update(correction_result={"status": "done"}, correction_rolled_back=True)
    monkeypatch.setattr(correction, "run", rollback)
    review_phases.advance(ctx, task, lambda _: None)
    assert task.phase == "finishing" and "recheck" not in invoked


def test_actual_fix_rollback_and_resume(setup, monkeypatch):
    ctx, task, page = setup
    install_reader(monkeypatch, page, findings=[finding(page)])
    inspection.prepare(ctx, task)
    inspection.inspect(ctx, task)
    before = safefs.read_text(ctx.notes_path, page)
    count = []
    def bad(ctx, child, handlers):
        count.append(1)
        safefs.write_text(ctx.notes_path, page, "bad replacement")
        safefs.write_text(ctx.notes_path, "wiki/m/new.md", "unrelated")
        raise BadWork("bad fix")
    monkeypatch.setattr(correction.writer, "run_ranges", bad)
    correction.run(ctx, task)
    correction.run(ctx, phase.load(task.dir))
    assert safefs.read_text(ctx.notes_path, page) == before
    assert not safefs.is_file(ctx.notes_path, "wiki/m/new.md")
    assert len(count) == 1 and task.get("correction_rolled_back")


def test_waiting_quota_keeps_phase(setup, monkeypatch):
    ctx, task, page = setup
    def wait(ctx, task):
        raise WaitingQuota("weekly")
    monkeypatch.setattr(inspection, "inspect", wait)
    with pytest.raises(WaitingQuota):
        review_phases.advance(ctx, task, lambda _: None)
    assert task.phase == "waiting_quota" and task.get("quota_phase") == "inspecting"
    install_reader(monkeypatch, page)
    monkeypatch.undo()


@pytest.mark.parametrize("count", [1, 2])
def test_t095_p4_timeout_rolls_back_and_second_stops(setup, monkeypatch, count):
    ctx, task, page = setup
    install_reader(monkeypatch, page, findings=[finding(page)])
    inspection.prepare(ctx, task)
    inspection.inspect(ctx, task)
    before = safefs.read_text(ctx.notes_path, page)
    def timeout(ctx, child, handlers):
        safefs.write_text(ctx.notes_path, page, "Partial fix")
        raise launch.TimedOut("timeout", details={"count": count})
    monkeypatch.setattr(correction.writer, "run_ranges", timeout)
    if count == 2:
        with pytest.raises(launch.TimedOut):
            correction.run(ctx, task)
    else:
        correction.run(ctx, task)
    assert safefs.read_text(ctx.notes_path, page) == before
    monkeypatch.setattr(correction.writer, "run_ranges", lambda *a: pytest.fail("replayed timed-out P4"))
    resumed = phase.load(task.dir)
    correction.run(ctx, resumed)
    assert resumed.get("correction_rolled_back")


def test_notices_are_idempotent_and_keep_hash(setup):
    ctx, task, page = setup
    key = units.page_key(ctx.notes_path, page)
    notices.refresh(ctx.notes_path, [page])
    first = safefs.read_text(ctx.notes_path, page)
    notices.refresh(ctx.notes_path, [page])
    assert safefs.read_text(ctx.notes_path, page) == first
    assert units.page_key(ctx.notes_path, page) == key


@pytest.mark.parametrize("status", ["fixed", "disagree", "open"])
def test_real_fix_call_assignment_and_targeted_recheck(setup, monkeypatch, status):
    from school_notes2.flows import fetch, writer
    ctx, task, page = setup
    invoked = install_reader(monkeypatch, page, findings=[finding(page)])
    inspection.prepare(ctx, task)
    inspection.inspect(ctx, task)
    seen = []
    monkeypatch.setattr(writer, "write_changes", lambda *a: None)
    monkeypatch.setattr(steps, "guard_step", lambda *a: None)
    monkeypatch.setattr(steps, "check_changed", lambda *a, **kw: None)
    monkeypatch.setattr(steps, "order_step", lambda *a: [])
    def fix(ctx, child, k, role, harness, handlers):
        supplied = fetch.fetch_json(child, k, grade=9)
        assert supplied["mode"] == "fix" and supplied["pages"] == []
        item = supplied["open_review_items"][0]
        assert item["file"] == task.get("inspection_report") and item["chain"] == 0
        seen.append(k)
        if status == "fixed":
            safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "\nA gravitáció miatt.\n")
        result = {"status": "done", "review_closure": [{"file": item["file"], "item_id": "R1",
                                                       "status": status, "note": "Szakmai indok"}]}
        safefs.write_json(ctx.notes_path, ".school-notes/result.json", result)
        return result
    monkeypatch.setattr(writer, "_call", fix)
    correction.run(ctx, task)
    correction.run(ctx, phase.load(task.dir))
    assert seen == [1]
    assert correction.needs_recheck(ctx, task) == (status != "open")
    if status != "open":
        recheck.run(ctx, task)
    state = relations.inventory(ctx.notes_path)["items"][task.get("inspection_report") + "#R1"]
    assert state["status"] == ("fixed" if status == "fixed" else "open")
    assert state["round"] == (2 if status == "disagree" else 1)
    if status == "fixed":
        assert verdicts.valid(ctx.notes_path, page) is not None


def test_unchanged_attempt_reuses_reader_verdict(setup, monkeypatch):
    ctx, task, page = setup
    invoked = install_reader(monkeypatch, page)
    inspection.prepare(ctx, task)
    inspection.inspect(ctx, task)
    task.update(attempt=2)
    inspection.prepare(ctx, task)
    assert task.get("inspection_units") == []
    inspection.inspect(ctx, task)
    assert invoked == ["reader-1"]


def test_recheck_not_ok_reopens_without_changing_chain(setup):
    from school_notes2.reader import report
    ctx, task, page = setup
    path = "docs/review/report.md"
    report.write(ctx.notes_path, path, [{**finding(page), "origin": "reader"}], [], "model", "base", "2026-10-04")
    closure = {"file": path, "item_id": "R1", "status": "fixed"}
    files.apply_closure(ctx.notes_path, "fix", [closure], [])
    report.reopen(ctx.notes_path, path + "#R1", "Még hibás")
    report.reopen(ctx.notes_path, path + "#R1", "Még hibás")
    record = relations.inventory(ctx.notes_path)["items"][path + "#R1"]
    assert record["status"] == "open" and record["chain"] == 0 and record["origin"] == "recheck"


def test_fix_crash_retry_is_durable_and_bounded(setup, monkeypatch):
    from school_notes2.flows import writer
    from school_notes2.state.errors import Transient
    ctx, task, page = setup
    task.update(mode="fix")
    count = []
    def crash(*a):
        count.append(1)
        raise Transient("container crash")
    monkeypatch.setattr(writer, "_call", crash)
    with pytest.raises(Transient):
        writer._invoke(ctx, task, 1, None, None, None)
    assert len(count) == 2
    assert phase.load(task.dir).get("fix_crash_retries") == [1]


def test_pending_figure_third_run_owner_and_resume(setup, monkeypatch):
    from school_notes2.figures import pending
    ctx, task, page = setup
    install_reader(monkeypatch, page)
    brief = {"id": "f", "page": page, "anchor": "Téma", "kind": "figure", "purpose": "Megértés",
             "must_show": ["erő"], "avoid_misreading": "irány", "taught_conventions": [],
             "text_complete_without_figure": True}
    safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "\n<!-- figure: f -->\n")
    safefs.write_json(ctx.notes_path, ".school-notes/figures/f.json", brief)
    for rid in ("older-1", "older-2"):
        pending.record(ctx.notes_path, brief, rid, [])
    task.update(inspection_result={"status": "done", "figures": [{k: brief[k] for k in ("id", "page", "kind")}]})
    notified = []
    review_phases.advance(ctx, task, notified.extend)
    assert task.phase == "finishing" and len(notified) == 1
    assert pending.load(ctx.notes_path)[0]["runs"] == 3
    assert pending.load(ctx.notes_path)[0]["owner_required"]
    before = safefs.read_text(ctx.notes_path, page)
    review_phases.finalize(ctx, phase.load(task.dir))
    assert safefs.read_text(ctx.notes_path, page) == before
    assert pending.load(ctx.notes_path)[0]["runs"] == 3
    assert len(relations.inventory(ctx.notes_path)["items"]) == 1
    assert notices.FIGURE.strip() in safefs.read_text(ctx.notes_path, page)


def test_capacity_exhausted_still_completes_p4_before_p6(setup, monkeypatch):
    ctx, task, page = setup
    install_reader(monkeypatch, page, findings=[finding(page)])
    task.update(inspection_result={"status": "done", "review_closure": [
        {"file": "docs/review/older.md", "item_id": f"R{n}", "status": "fixed"} for n in range(20)]})
    # The old closures' pages are absent from the fixture, so they add no review unit.
    review_phases.advance(ctx, task, lambda _: None)
    saved = safefs.read_json(inspection.folder(task) / "correction", "receipt.json")
    assert saved["status"] == "done" and task.phase == "finishing"
    assert task.get("correction_items") == []


def test_open_section_notice_is_byte_stable(setup, monkeypatch):
    ctx, task, page = setup
    install_reader(monkeypatch, page, findings=[finding(page)])
    inspection.prepare(ctx, task)
    inspection.inspect(ctx, task)
    notices.refresh(ctx.notes_path, [page])
    before = safefs.read_text(ctx.notes_path, page)
    notices.refresh(ctx.notes_path, [page])
    assert safefs.read_text(ctx.notes_path, page) == before
    assert notices.SECTION.strip() in before


def test_fix_resume_never_adopts_previous_writer_result(setup, monkeypatch):
    from school_notes2.flows import writer
    ctx, task, page = setup
    task.update(mode="fix")
    safefs.write_json(ctx.notes_path, ".school-notes/result.json", {"status": "done"})
    assert writer._fix_resume(ctx, task, 1) is None
    assert not safefs.is_file(ctx.notes_path, ".school-notes/result.json")
    task = phase.load(task.dir)
    assert writer._fix_resume(ctx, task, 1) is None
    with pytest.raises(BadWork, match="twice"):
        writer._fix_resume(ctx, phase.load(task.dir), 1)


def test_recovered_fix_result_still_needs_warning_accounting(setup):
    from school_notes2.flows import writer
    ctx, task, page = setup
    task.update(mode="fix", fix_calls={"1": 1}, writer_check={"count": 1, "warnings": ["H1"]})
    safefs.write_json(ctx.notes_path, ".school-notes/result.json", {"status": "done"})
    with pytest.raises(steps.CheckFailed):
        writer._fix_resume(ctx, task, 1)


def test_partial_figure_batch_finalizes_only_good_candidates_and_keeps_reason(setup, monkeypatch):
    import io
    from PIL import Image
    from school_notes2.figures import context, pending
    ctx, task, page = setup
    install_reader(monkeypatch, page)
    data = io.BytesIO()
    Image.new("RGB", (20, 10), "white").save(data, format="PNG")
    briefs = []
    for fid in ("good", "bad"):
        brief = {"id": fid, "page": page, "anchor": "Téma", "kind": "figure",
                 "purpose": "Teach", "must_show": ["force"], "avoid_misreading": "direction",
                 "taught_conventions": [], "text_complete_without_figure": True}
        candidate = {"state": "candidate", "asset": f"wiki/assets/{fid}.png", "alt": "Force",
                     "caption": "", "form": "diagram", "tool": "test", "elements": [],
                     "visible_text": [], "attempt": 1}
        safefs.write_bytes(ctx.notes_path, candidate["asset"], data.getvalue())
        safefs.write_json(ctx.notes_path, f".school-notes/figures/{fid}.json", brief)
        safefs.write_json(ctx.notes_path, f".school-notes/figures/{fid}/figure.json", candidate)
        safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + f"\n<!-- figure: {fid} -->\n")
        briefs.append(brief)
    task.update(inspection_result={"status": "done", "figures": [{k: b[k] for k in ("id", "page", "kind")} for b in briefs]})
    monkeypatch.setattr(inspection, "render", lambda *a: lambda kind, data, fid: data)
    def partial(*args):
        brief = briefs[0]
        candidate = safefs.read_json(ctx.notes_path, ".school-notes/figures/good/figure.json")
        return {"status": "reviewed", "model": "independent/high", "review": {
            "figures": [{"id": "good", "key": context.verdict_key(ctx.notes_path, brief, candidate),
                         "verdict": "accept", "observed": "Force", "defects": [],
                         "text_mismatch": [], "relates_to": None}], "owner_notes": []},
            "failed": [{"id": "bad", "state": "failed", "reason": "render failed"}]}
    monkeypatch.setattr(inspection, "figures", partial)
    inspection.prepare(ctx, task)
    inspection.inspect(ctx, task)
    review_phases.finalize(ctx, task)
    review_phases.finalize(ctx, phase.load(task.dir))
    text = safefs.read_text(ctx.notes_path, page)
    assert "generated figure-good" in text and "<!-- figure: bad -->" in text
    entries = pending.load(ctx.notes_path)
    assert len(entries) == 1 and entries[0]["commission"]["id"] == "bad"
    assert entries[0]["runs"] == 1 and entries[0]["defects"][0]["observed"] == "render failed"
