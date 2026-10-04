"""Pre-release review regressions: topic scope, quiet nights and finding routing."""

import json

import pytest

from school_notes2.flows import night_topics
from school_notes2.llm import launch
from school_notes2.reader import notices, verdicts
from school_notes2.review import close, files, nightly, relations, topic_result, topics
from school_notes2.state import phase, safefs
from school_notes2.wiki import public
from tests.review.conftest import sh
from tests.review.test_topics import FIX, IDENT, context, good, prepare


@pytest.mark.parametrize("learner", ["one", "two"])
@pytest.mark.parametrize("companion", ["source", "receipt", "preview", "folder", "all"])
def test_render_companions_belong_to_embedding_topic(tmp_path, repos, learner, companion):
    topic, lesson = "wiki/a.md", "wiki/lesson.md"
    folder = "wiki/assets/drawing"
    source, receipt = "wiki/assets/drawing.py", folder + "/render.json"
    preview, extra, asset = folder + "/figure.png", folder + "/preview.png", folder + "/figure.svg"
    repos.commit({topic: "# A\n", "wiki/z.md": "# Z\n\n![Ábra](assets/drawing/figure.svg)\n",
                  lesson: "---\ntype: lesson-notes\nlessons:\n- topics: [a.md]\n---\n"
                          "# Óra\n\n![Ábra](assets/drawing/figure.svg)\n", asset: "<svg/>\n"})
    sh("git", "push", "-q", "origin", "HEAD:claude-reviewed", cwd=repos.laptop)
    changes = {"source": {source: "print('figure')\n"},
               "receipt": {receipt: json.dumps({"source": source, "outputs": {"figure.svg": {}, "figure.png": {}}})},
               "preview": {preview: b"\x89PNG\x00binary payload"},
               "folder": {extra: b"\x89PNG\x00folder preview"}}
    # Companion-only commits must work even when the receipt itself is unchanged.
    repos.commit({path: value for group in changes.values() for path, value in group.items()})
    if companion != "all":
        sh("git", "push", "-q", "origin", "HEAD:claude-reviewed", cwd=repos.laptop)
        changes = {companion: {path: value + (b"\n" if isinstance(value, bytes) else "\n")
                              for path, value in changes[companion].items()}}
        repos.commit(changes[companion])
    task = prepare(tmp_path, repos, learner)
    units = task.get("units")
    assert len(units) == 1 and units[0]["topic"] == topic
    assert units[0]["assigned_pages"] == [topic, lesson]
    assert set(units[0]["context"]) == {path for group in changes.values() for path in group}
    patch = topics.patch(repos.repo, units[0], task.get("H"))
    assert "binary payload" not in patch and "folder preview" not in patch
    for path in (preview, extra):
        if path in units[0]["context"]:
            assert f"Binary file {path}\n" in patch
    again, _ = topics.plan(repos.repo, repos.wt_path, task.get("base"), task.get("H"), {})
    assert again == units


@pytest.mark.parametrize("learner", ["one", "two"])
def test_non_pages_and_orphan_assets_never_get_units_or_notices(tmp_path, repos, log, monkeypatch, learner):
    log_text = "# Wiki Update Log\n\nÚj naplósor.\n"
    repos.commit({"wiki/log.md": log_text, "wiki/assets/README.md": "# Leírás\n",
                  "wiki/assets/orphan/render.json": '{"source":"wiki/assets/orphan.py","outputs":{}}',
                  "wiki/assets/orphan.py": "print('orphan')\n", "wiki/assets/orphan/a.png": b"\x00PNG"})
    def unexpected(*args, **kwargs):
        raise AssertionError("non-learning files must not launch a reviewer")
    monkeypatch.setattr(launch, "run_headless", unexpected)
    task = prepare(tmp_path, repos, learner)
    assert task.get("units") == []
    night_topics.run(context(tmp_path, repos, log, learner), task)
    close.close(task, repos.repo, repos.wt, IDENT)
    verdicts.invalidate(repos.wt_path)
    notices.refresh(repos.wt_path, [])
    assert safefs.read_text(repos.wt_path, "wiki/log.md") == log_text
    assert safefs.read_json(repos.wt_path, verdicts.PATH) == []


@pytest.mark.parametrize("learner", ["one", "two"])
def test_empty_completed_night_advances_marker_after_crash(tmp_path, repos, log, monkeypatch, learner):
    repos.commit({"wiki/a.md": "# A\n"})
    ctx = context(tmp_path, repos, log, learner)
    monkeypatch.setattr(launch, "run_headless", good)
    first = prepare(tmp_path, repos, learner)
    night_topics.run(ctx, first)
    close.close(first, repos.repo, repos.wt, IDENT)
    sh("git", "pull", "-q", "--ff-only", cwd=repos.laptop)
    head = repos.commit({"sources/new.txt": "New source only.\n"})
    task = prepare(tmp_path, repos, learner)
    night_topics.run(ctx, task)
    assert task.get("all_topics_done") and not task.get("units")
    original = close._finish
    monkeypatch.setattr(close, "_finish", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        close.close(task, repos.repo, repos.wt, IDENT)
    report = repos.remote("main")
    assert report != head and report == repos.remote("claude-reviewed")
    monkeypatch.setattr(close, "_finish", original)
    assert close.close(phase.load(task.dir), repos.repo, repos.wt, IDENT) == (report, report)
    assert prepare(tmp_path, repos, learner) is None


@pytest.mark.parametrize("learner", ["one", "two"])
def test_export_error_and_reviewer_notes_share_one_section(tmp_path, repos, log, monkeypatch, learner):
    old_report = "docs/review/old.md"
    old = "---\nitems: {R1: open}\nitem_details: {R1: {file: wiki/a.md, chain: 0}}\n---\n"
    repos.commit({"wiki/a.md": "# A\n\nHibás állítás.\n", old_report: old})
    repos.commit({old_report: old.replace("R1: open", "R1: fixed")})
    task = prepare(tmp_path, repos, learner)
    def review(run, **kwargs):
        result = good(run)
        result.output["owner_notes"] = ["Lektori észrevétel."]
        result.output["findings"] = [{"id": "R1", "file": "wiki/a.md", "quote": "Hibás állítás.",
                                      "problem": "Javítandó.", "category": "tárgyi",
                                      "relates_to": old_report + "#R1"}]
        result.output["items"][0]["verdict"] = "not-ok"
        safefs.write_json(run.mounts.out_dir, "review.json", result.output)
        return result
    monkeypatch.setattr(launch, "run_headless", review)
    night_topics.run(context(tmp_path, repos, log, learner), task)
    def fail(*args):
        raise public.PublicError(["wiki/assets/unknown.png"])
    monkeypatch.setattr(public, "write", fail)
    original = close._commit
    monkeypatch.setattr(close, "_commit", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        close.close(task, repos.repo, repos.wt, IDENT)
    monkeypatch.setattr(close, "_commit", original)
    close.close(phase.load(task.dir), repos.repo, repos.wt, IDENT)
    reports = safefs.glob(repos.wt_path, "docs/review", "docs/review/*-review.md")
    assert len(reports) == 1
    text = safefs.read_text(repos.wt_path, reports[0])
    assert text.count("## Tulajdonosi észrevételek") == 1
    notes = safefs.read_json(task.dir, "review.json")["owner_notes"]
    assert len(notes) == 2 and all(text.count(n) == 1 for n in notes)
    assert files.read_items(repos.wt_path, repos.wt_path / reports[0]) == {"R1": "owner"}
    assert task.get("notify_owner_items")[0]["item_id"] == "R1"
    assert "⏳" in safefs.read_text(repos.wt_path, "wiki/a.md")


@pytest.mark.parametrize("origin", ["findings", "hits", "figure_findings"])
def test_nightly_routes_generated_findings_before_blame(tmp_path, repos, origin):
    literal = "# 📝 Jegyzetek"
    repos.commit({"wiki/a.md": "---\ntitle: Régi cím\n---\n# A\n"})
    repos.commit({"wiki/a.md": "---\ntitle: Hibás cím\n---\n# A\n"}, FIX)
    repos.commit({"wiki/index.md": "# Index\n\n<!-- school-notes:generated notes -->\n"
                                  + literal + "\nHibás cím\n<!-- /school-notes:generated -->\n\nÚj próza.\n"})
    task = prepare(tmp_path, repos)
    unit = next(u for u in task.get("units") if u["topic"] == "wiki/index.md")
    findings = [{"file": "wiki/index.md", "quote": q, "problem": "Hibás.", "relates_to": None}
                for q in (literal, "Hibás cím")]
    value = {"findings": [], "hits": []}
    entry = {"unit": unit, "receipt": {"status": "reviewed", "review": value}, "input": {"hits": []}}
    if origin == "hits":
        lines = safefs.read_text(repos.wt_path, "wiki/index.md").splitlines()
        entry["input"]["hits"] = [{"id": str(n), "file": f["file"], "line": lines.index(f["quote"]) + 1}
                                  for n, f in enumerate(findings)]
        value["hits"] = [{"hit_id": str(n), "verdict": "hiba", "reason": f["problem"]}
                         for n, f in enumerate(findings)]
    elif origin == "figure_findings":
        entry[origin] = findings
    else:
        value[origin] = findings
    task.update(topic_results=[entry])
    result = topic_result.assemble(task, repos.repo, repos.wt_path)
    assert len(result["owner_notes"]) == 1 and "Tool-sablon" in result["owner_notes"][0]
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["id"] == "R1" and finding["file"] == "wiki/a.md"
    assert finding["reported_file"] == "wiki/index.md"
    assert finding["chain"] == 1 and not finding["unlocated"]
    report = files.write_review(repos.wt_path, IDENT.date, result, "fake", "a", "b")
    assert files.read_items(repos.wt_path, report) == {"R1": "owner"}
    assert topic_result.assemble(phase.load(task.dir), repos.repo, repos.wt_path) == result
