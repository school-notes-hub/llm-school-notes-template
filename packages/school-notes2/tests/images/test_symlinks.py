"""T7 for the image flow: planted symlinks never lead host writes outside the worktree."""

import os

import pytest

from school_notes2.images import generate as gen
from school_notes2.images import plans
from school_notes2.state.safefs import UnsafePath

from image_fakes import prepare_candidate, independent_accept

PLAN = ".school-notes/images/termeles-banner.json"


def test_review3_b1_dangling_plan_link_does_not_create_a_host_file(make_settings, fake_api, log,
                                                                    tmp_path):
    """generate keeps the plan, the LLM swaps it for a dangling link to ~/.bash_aliases,
    restoring it must not create the canary."""
    s = make_settings()
    assert gen.generate(s, "termeles-banner", log=log, sleep=lambda x: None)["state"] == "generated"
    canary = tmp_path / "bash_aliases"
    (s.worktree / PLAN).unlink()
    os.symlink(canary, s.worktree / PLAN)
    with pytest.raises(UnsafePath):
        plans.restore(s, ["termeles-banner"])
    assert not canary.exists()


def test_plan_read_through_a_link_is_refused(make_settings, log, tmp_path):
    s = make_settings()
    secret = tmp_path / "secret.json"
    secret.write_text('{"x": 1}')
    (s.worktree / PLAN).unlink()
    os.symlink(secret, s.worktree / PLAN)
    with pytest.raises(UnsafePath):
        plans.keep(s, "termeles-banner")
    assert not (s.plans_dir / "termeles-banner.json").exists()


def test_preview_copy_does_not_follow_a_linked_images_folder(make_settings, fake_api, log,
                                                             tmp_path):
    s = make_settings()
    gen.generate(s, "termeles-banner", log=log, sleep=lambda x: None)   # plan kept
    outside = tmp_path / "outside"
    outside.mkdir()
    images = s.worktree / ".school-notes/images"
    for f in images.iterdir():
        f.unlink()
    images.rmdir()
    os.symlink(outside, images)
    try:
        gen.generate(s, "termeles-banner", log=log, sleep=lambda x: None)
    except UnsafePath:
        pass
    assert list(outside.iterdir()) == []


def test_linked_assets_folder_stops_learning_image(make_settings, fake_api, log, tmp_path):
    s = make_settings()
    gen.generate(s, "termeles-banner", log=log, sleep=lambda x: None)
    outside = tmp_path / "assets-outside"
    outside.mkdir()
    assets = s.worktree / "wiki/assets"
    if assets.exists():
        os.rename(assets, tmp_path / "assets-moved")
    os.symlink(outside, assets)
    with pytest.raises(UnsafePath):
        prepare_candidate(s)
    assert list(outside.iterdir()) == []


def test_markers_behind_a_linked_folder_are_not_seen(make_settings, tmp_path):
    s = make_settings()
    outside = tmp_path / "pages"
    outside.mkdir()
    (outside / "x.md").write_text("<!-- image: stolen -->\n")
    os.symlink(outside, s.worktree / "wiki/evil")
    assert "stolen" not in plans.find_markers(s.worktree)


JOB = "benedek-termeles-banner"
RECEIPTS = "docs/evidence/media/termeles-banner"


def test_receipt_symlink_cannot_overwrite_external_evidence(make_settings, fake_api, log, tmp_path):
    s = make_settings()
    gen.generate(s, "termeles-banner", log=log, sleep=lambda x: None)
    prepare_candidate(s)
    folder = s.worktree / RECEIPTS
    folder.mkdir(parents=True)
    canary = tmp_path / "canary.json"
    os.symlink(canary, folder / "figure.json")
    with pytest.raises(UnsafePath):
        independent_accept(s)
    assert not canary.exists()


def test_round2_b1_linked_receipt_folder_is_refused(make_settings, fake_api, log, tmp_path):
    s = make_settings()
    gen.generate(s, "termeles-banner", log=log, sleep=lambda x: None)
    prepare_candidate(s)
    outside = tmp_path / "receipts-outside"
    outside.mkdir()
    (s.worktree / "docs/evidence/media").mkdir(parents=True, exist_ok=True)
    os.symlink(outside, s.worktree / RECEIPTS)
    with pytest.raises(UnsafePath):
        independent_accept(s)
    assert list(outside.iterdir()) == []


def test_learning_image_works_on_a_staging_copy_only(tmp_path):
    """copy_back takes only the job's receipt folder and its asset from the staging copy."""
    from school_notes2.images.executor import ExecutorError, copy_back
    RECEIPTS = f"docs/evidence/media/{JOB}"
    work, stage = tmp_path / "work", tmp_path / "stage"
    (work / "wiki").mkdir(parents=True)
    (stage / "wiki").mkdir(parents=True)
    (stage / "wiki/index.md").write_text("rewritten by the tool?\n")
    with pytest.raises(ExecutorError, match="unexpected file"):
        copy_back(work, stage, {"id": JOB}, {})
    (stage / "wiki/index.md").unlink()
    (stage / RECEIPTS).mkdir(parents=True)
    (stage / f"{RECEIPTS}/receipt-1.json").write_text("{}")
    (stage / "wiki/assets/banner").mkdir(parents=True)
    (stage / f"wiki/assets/banner/{JOB}.webp").write_bytes(b"new")
    (work / "wiki/assets/banner").mkdir(parents=True)
    (work / f"wiki/assets/banner/{JOB}.webp").write_bytes(b"old")
    with pytest.raises(ExecutorError, match="different bytes"):
        copy_back(work, stage, {"id": JOB}, {})
    (work / f"wiki/assets/banner/{JOB}.webp").unlink()
    assert copy_back(work, stage, {"id": JOB}, {}) == [f"{RECEIPTS}/receipt-1.json",
                                                      f"wiki/assets/banner/{JOB}.webp"]


def test_asset_names_match_exactly():
    from school_notes2.images.executor import is_job_asset
    assert is_job_asset("wiki/assets/banner/benedek-x-a.webp", "benedek-x-a")
    assert is_job_asset("wiki/assets/banner/benedek-x-a-r2.webp", "benedek-x-a")
    assert not is_job_asset("wiki/assets/banner/benedek-x-ab.webp", "benedek-x-a")
    assert not is_job_asset("docs/benedek-x-a.webp", "benedek-x-a")


def test_refused_output_writes_nothing(tmp_path):
    import pytest
    from school_notes2.images.executor import ExecutorError, copy_back
    worktree, stage = tmp_path / "wt", tmp_path / "stage"
    (worktree / "wiki").mkdir(parents=True)
    receipt = stage / "docs/evidence/media/benedek-x/receipt-1.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text("{}")
    (stage / "wiki").mkdir()
    (stage / "wiki/elsewhere.md").write_text("no")
    with pytest.raises(ExecutorError):
        copy_back(worktree, stage, {"id": "benedek-x"}, {})
    assert not (worktree / "docs").exists()
