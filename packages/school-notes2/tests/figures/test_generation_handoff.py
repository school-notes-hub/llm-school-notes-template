"""No paid generation without a figure insertion route; no network or socket."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from school_notes2.figures import context, insert
from school_notes2.flows import fetch, run
from school_notes2.images import generate
from school_notes2.images.settings import ImageSettings
from school_notes2.state import safefs
from test_insert import receipt


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("problem", ["missing", "inline", "wrong-page", "wrong-section"])
def test_invalid_commission_stops_before_ledger_or_provider(repo, make_figure, tmp_path, log, monkeypatch, learner, problem):
    brief, _ = make_figure()
    if problem == "missing":
        safefs.unlink(repo, ".school-notes/figures/forces.json")
    elif problem == "inline":
        text = safefs.read_text(repo, brief["page"]).replace("<!-- figure:", "- <!-- figure:")
        safefs.write_text(repo, brief["page"], text)
    else:
        brief["page" if problem == "wrong-page" else "anchor"] = "missing"
        safefs.write_json(repo, ".school-notes/figures/forces.json", brief)
    settings = ImageSettings(learner, repo, tmp_path / "script", tmp_path / "state",
                             tmp_path / "plans", tmp_path / "lock", tmp_path / "key",
                             Decimal("10"), Decimal("10"))
    monkeypatch.setattr(generate, "call", lambda *a, **k: pytest.fail("provider called"))
    result = generate.generate(settings, "forces", log=log)
    assert result["state"] == "error" and "commission required" in result["message"]
    assert not settings.state_root.exists() and not settings.lock_path.exists()


def test_generated_publication_preview_is_the_inserted_asset(repo, make_figure, tmp_path, monkeypatch):
    brief, candidate = make_figure()
    settings = SimpleNamespace(learner="student", worktree=repo, plans_dir=tmp_path)
    preview = tmp_path / "preview.webp"
    from PIL import Image
    Image.new("RGB", (100, 50), "blue").save(preview)
    Image.new("RGB", (100, 50), "blue").save(tmp_path / "image.png")
    import hashlib
    sha = hashlib.sha256(preview.read_bytes()).hexdigest()
    monkeypatch.setattr(generate, "call", lambda *a, **k: {"path": str(preview), "sha256": sha})
    paths = generate._preview(settings, {"id": "student-forces", "role": "banner", "target": "plan"}, {"number": 1})
    candidate["asset"] = "wiki/assets/physics/forces-1.webp"
    safefs.copy_in(repo / paths["preview"], repo, candidate["asset"])
    safefs.write_json(repo, ".school-notes/figures/forces/figure.json", candidate)
    assert not context.verdict_key(repo, brief, candidate) == ""
    insert.insert(repo, brief, receipt(repo, brief, candidate), at="date")
    assert safefs.read_bytes(repo, candidate["asset"]) == preview.read_bytes()
    assert f"sha256: {sha}" in safefs.read_text(repo, brief["page"])


def test_legacy_image_marker_does_not_start_a_generation_only_run(monkeypatch):
    monkeypatch.setattr(fetch, "_scan", lambda *a: [])
    ctx = SimpleNamespace()
    assert fetch.start(ctx, "cron", None) is None
    from school_notes2.flows import repair
    monkeypatch.setattr(fetch, "drive_client", lambda *a: None)
    monkeypatch.setattr(repair, "next_task", lambda *a: None)
    # ctx deliberately has no image settings: there is no image-only scan or spending.
    assert run._new_task(ctx) is None


def test_generation_receipt_does_not_reserve_the_commission_identity(repo, make_figure, tmp_path, monkeypatch):
    from school_notes2.flows import handlers
    from school_notes2.state import phase
    from school_notes2.figures import commissions
    from school_notes2.wiki import public
    brief, candidate = make_figure()
    digest = public.sha256(repo, candidate["asset"])
    ctx = SimpleNamespace(notes_path=repo, image_settings=lambda: None, log=None)
    task = phase.create(tmp_path / "tasks", "sample", "notes", "interactive", "prepared")
    monkeypatch.setattr(handlers.image_generate, "generate", lambda *a, **kw: {
        "state": "generated", "number": 1, "sha256": digest, "preview_sha256": digest})
    handlers.generate(ctx, task, brief["id"], None)
    commissions.check_identity(repo, brief)
    insert.insert(repo, brief, receipt(repo, brief, candidate), at="date")
    assert public.media_receipt_rights(repo)(candidate["asset"])[0] == "generated"
