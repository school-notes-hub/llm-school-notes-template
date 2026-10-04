import io
from types import SimpleNamespace

from PIL import Image

from school_notes2.config import Harness, Role
from school_notes2.figures import insert, review
from school_notes2.llm.launch import Mounts, RoleRun
from school_notes2.review import night_figures
from school_notes2.state import safefs


def png():
    out = io.BytesIO()
    Image.new("RGB", (400, 200), "white").save(out, format="PNG")
    return out.getvalue()


def test_legacy_image_checked_once_and_context_invalidates(tmp_path, log, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    safefs.write_text(repo, "wiki/s/a.md", "---\ntype: concept\n---\n# A\n\nTananyag.\n\n![Rajz](../assets/a.png)\n")
    safefs.write_bytes(repo, "wiki/assets/a.png", png())
    unit = {"topic": "wiki/s/a.md", "pages": ["wiki/s/a.md"]}
    root = tmp_path / "night"
    root.mkdir()
    role = Role("claude-review", "fake", "high", 1800)
    run = RoleRun("one", "night", "reviewer", role, Harness("claude-review", [], [], []), "fake", Mounts(),
                  root / "unused", "figure-review", root, grade=9)
    calls = []
    def invoke(run, **kw):
        calls.append(run)
        assigned = safefs.read_json(run.mounts.in_dir, "assigned.json")
        value = {"figures": [{**fig, "verdict": "accept", "observed": "Rajz.", "defects": [],
                               "text_mismatch": [], "relates_to": None} for fig in assigned["figures"]], "owner_notes": []}
        safefs.write_json(run.mounts.out_dir, "review.json", value)
        return SimpleNamespace(output=value)
    original = review.run_batch
    monkeypatch.setattr(review, "run_batch", lambda *a, **kw: original(*a, **kw, invoke=invoke))
    before = safefs.read_bytes(repo, "wiki/s/a.md")
    result = night_figures.run(repo, unit, root, run, lambda *a: png(), log)
    assert len(calls) == 1 and len(result["records"]) == 1
    assert calls[0].role_name == "figure-review" and calls[0].mounts.work_readonly
    assert safefs.read_bytes(repo, "wiki/s/a.md") == before
    night_figures.apply(repo, result["records"], "now")
    assert not insert.invalidated(repo)
    another = tmp_path / "next"
    another.mkdir()
    assert not night_figures.run(repo, unit, another, run, lambda *a: png(), log)["records"]
    assert len(calls) == 1
    safefs.write_text(repo, "wiki/s/a.md", before.decode().replace("Tananyag.", "Más tananyag."))
    assert len(insert.invalidated(repo)) == 1
    # A saved valid figure output is reusable after a crash before the topic receipt.
    assert night_figures.run(repo, unit, root, run, lambda *a: png(), log) == result
    assert len(calls) == 1


def test_missing_image_stays_pending_without_a_call(tmp_path, log, monkeypatch):
    repo, root = tmp_path / "repo", tmp_path / "night"
    repo.mkdir()
    root.mkdir()
    safefs.write_text(repo, "wiki/a.md", "# A\n\n![Rajz](assets/missing.png)\n")
    role = Role("claude-review", "fake", "high", 1800)
    run = RoleRun("one", "night", "reviewer", role, Harness("claude-review", [], [], []), "fake", Mounts(),
                  root / "unused", "figure-review", root, grade=9)
    original = review.run_batch
    def invoke(*args, **kwargs):
        raise AssertionError("missing bytes must not start the harness")
    monkeypatch.setattr(review, "run_batch", lambda *a, **kw: original(*a, **kw, invoke=invoke))
    result = night_figures.run(repo, {"topic": "wiki/a.md", "pages": ["wiki/a.md"]},
                               root, run, lambda *a: png(), log)
    assert result["records"] == result["findings"] == []
    assert result["pending"] and result["notes"]
    assert night_figures.run(repo, {}, root, run, lambda *a: png(), log) == result


def test_one_hardlinked_view_per_night_and_adaptation_resume(tmp_path, log, monkeypatch):
    import pytest
    repo, night = tmp_path / "repo", tmp_path / "night"
    repo.mkdir()
    night.mkdir()
    for page in ("a", "b"):
        safefs.write_text(repo, f"wiki/s/{page}.md", f"# {page}\n\n![Rajz](../assets/{page}.png)\n")
        safefs.write_bytes(repo, f"wiki/assets/{page}.png", png())
    safefs.write_bytes(repo, "sources/large.bin", b"source")
    role = Role("claude-review", "fake", "high", 1800)
    run = RoleRun("one", "night", "reviewer", role, Harness("claude-review", [], [], []), "fake", Mounts(),
                  night / "unused", "figure-review", night, grade=9)
    view = night / "figure-view"
    cloned = []
    original = safefs.link_or_copy
    def link(*args):
        cloned.append(args[2])
        return original(*args)
    monkeypatch.setattr(safefs, "link_or_copy", link)
    def crash(*args, **kwargs):
        raise KeyboardInterrupt()
    monkeypatch.setattr(review, "run_batch", crash)
    unit = {"topic": "wiki/s/a.md", "pages": ["wiki/s/a.md"]}
    with pytest.raises(KeyboardInterrupt):
        night_figures.run(repo, unit, night / "a", run, lambda *a: png(), log, view_folder=view)
    monkeypatch.setattr(review, "run_batch", lambda *a, **kw: {"status": "pending", "reason": "suspended"})
    night_figures.run(repo, unit, night / "a", run, lambda *a: png(), log, view_folder=view)
    night_figures.run(repo, {"topic": "wiki/s/b.md", "pages": ["wiki/s/b.md"]}, night / "b",
                      run, lambda *a: png(), log, view_folder=view)
    assert cloned.count("sources/large.bin") == 1
    assert (view / "sources/large.bin").stat().st_ino == (repo / "sources/large.bin").stat().st_ino
    assert safefs.read_text(view, "wiki/s/a.md").count("<!-- figure:") == 1
    assert "<!-- figure:" not in safefs.read_text(repo, "wiki/s/a.md")
    assert not (night / "a/figure-view").exists() and not (night / "b/figure-view").exists()


def test_partial_snapshot_crash_resumes(tmp_path, monkeypatch):
    import pytest
    repo, view = tmp_path / "repo", tmp_path / "view"
    repo.mkdir()
    safefs.write_text(repo, "wiki/a.md", "A")
    safefs.write_text(repo, "sources/a.txt", "Source")
    original = safefs.link_or_copy
    def crash(src, dest, rel):
        original(src, dest, rel)
        raise KeyboardInterrupt()
    monkeypatch.setattr(safefs, "link_or_copy", crash)
    with pytest.raises(KeyboardInterrupt):
        night_figures.prepare_view(repo, view)
    assert not (view / "snapshot.json").exists()
    monkeypatch.setattr(safefs, "link_or_copy", original)
    night_figures.prepare_view(repo, view)
    assert safefs.read_text(view, "sources/a.txt") == "Source"


def test_failed_figure_is_operational_only_and_notice_clears(tmp_path, log, monkeypatch):
    from school_notes2.review import figure_waiting, relations
    from school_notes2.reader import notices, units, verdicts
    repo, folder = tmp_path / "repo", tmp_path / "night"
    repo.mkdir()
    folder.mkdir()
    page = "wiki/s/a.md"
    safefs.write_text(repo, page, "# A\n\n![Rajz](../assets/a.png)\n")
    safefs.write_bytes(repo, "wiki/assets/a.png", png())
    role = Role("claude-review", "fake", "high", 1800)
    run = RoleRun("one", "night", "reviewer", role, Harness("claude-review", [], [], []), "fake", Mounts(),
                  folder / "unused", "figure-review", folder, grade=9)
    monkeypatch.setattr(review, "run_batch", lambda *a, **kw: {"status": "pending", "reason": "timed out"})
    result = night_figures.run(repo, {"topic": page, "pages": [page]}, folder, run, lambda *a: png(), log)
    assert not result["findings"] and result["pending"] and result["notes"]
    figure_waiting.apply(repo, result["pending"])
    verdicts.record(repo, [{"file": page, "verdict": "ok"}], {page: units.page_key(repo, page)}, "fake", "now")
    notices.refresh(repo, [page])
    assert notices.FIGURE in safefs.read_text(repo, page)
    assert not relations.inventory(repo)["items"]
    assert figure_waiting.active(repo) == result["pending"]
    spec = result["pending"][0]["spec"]
    night_figures.apply(repo, [{"role": "figure-review", "file": page, "id": spec["id"],
                              "key": night_figures.fingerprint(repo, spec), "verdict": "accept", "model": "fake",
                              "night_spec": spec, "observed": "A"}], "now")
    figure_waiting.apply(repo, [])
    notices.refresh(repo, [page])
    assert not figure_waiting.active(repo) and "⏳" not in safefs.read_text(repo, page)


def test_rejected_figure_problem_is_readable(tmp_path, log, monkeypatch):
    repo, folder = tmp_path / "repo", tmp_path / "night"
    repo.mkdir()
    folder.mkdir()
    page = "wiki/a.md"
    safefs.write_text(repo, page, "# A\n\n![Rajz](assets/a.png)\n")
    safefs.write_bytes(repo, "wiki/assets/a.png", png())
    role = Role("claude-review", "fake", "high", 1800)
    run = RoleRun("one", "night", "reviewer", role, Harness("claude-review", [], [], []), "fake", Mounts(),
                  folder / "unused", "figure-review", folder, grade=9)
    def rejected(repo, briefs, *args, **kwargs):
        return {"status": "reviewed", "review": {"figures": [
            {"id": briefs[0]["id"], "verdict": "reject", "observed": "Wrong", "relates_to": None,
             "defects": [{"location": "Nyíl", "observed": "Balra mutat", "expected": "Jobbra mutasson"}],
             "text_mismatch": []}]}}
    monkeypatch.setattr(review, "run_batch", rejected)
    result = night_figures.run(repo, {"topic": page, "pages": [page]}, folder, run, lambda *a: png(), log)
    assert result["findings"][0]["problem"] == "Nyíl: Balra mutat → Jobbra mutasson"


def test_real_rejection_replaces_previous_missing_verdict(tmp_path):
    from school_notes2.review import figure_waiting
    page = "wiki/a.md"
    safefs.write_text(tmp_path, page, "# A\n\n![New alt](assets/a.png)\n")
    safefs.write_bytes(tmp_path, "wiki/assets/a.png", png())
    spec = {"id": "old", "page": page, "asset": "wiki/assets/a.png", "kind": "figure", "anchor": "A"}
    entry = {"spec": spec, "reason": "missing"}
    figure_waiting.apply(tmp_path, [entry])
    assert figure_waiting.active(tmp_path)
    # A changed alt gives a legacy figure a new ID; the same image has now been judged.
    figure_waiting.apply(tmp_path, [], [{**spec, "id": "new"}])
    assert not figure_waiting.active(tmp_path)
