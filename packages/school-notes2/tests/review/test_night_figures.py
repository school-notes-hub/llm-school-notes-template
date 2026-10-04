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
    assert result["records"] == [] and result["findings"][0]["unlocated"]
    assert night_figures.run(repo, {}, root, run, lambda *a: png(), log) == result
