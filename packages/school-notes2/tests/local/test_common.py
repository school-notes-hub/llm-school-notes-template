"""The real `common.Local` (not FakeLocal) builds what the commands use from the configuration
(Opus m5): image settings, the study-site renderer, and the close bookkeeping on its paths."""

from decimal import Decimal
from pathlib import Path

from school_notes2 import config
from school_notes2.local import common, figure_close, keys, machine_data, publish
from school_notes2.figures import insert
from school_notes2.state import safefs
from school_notes2.wiki.author import page_key


def local(tmp_path) -> common.Local:
    cfg = config.parse({"root": str(tmp_path / "state-root"), "git": {"name": "O", "email": "o@example.com"},
                        "limits": {"image_monthly_usd": 7.5, "image_year_learner_usd": 50},
                        "timeouts": {"image_generate_s": 33, "build_s": 44},
                        "students": {"barna": {"site_repo": "https://github.com/o/b.git", "drive_root": "d",
                                               "grade": 11, "local_repo": str(tmp_path / "repo")}}})
    (tmp_path / "repo").mkdir(parents=True)
    return common.Local(cfg, cfg.student("barna"), tmp_path / "repo")


def test_image_settings_come_from_the_config_and_the_release(tmp_path):
    s = local(tmp_path).image_settings()
    root = tmp_path / "state-root" / "state"
    assert (s.learner, s.worktree, s.key_file) == ("barna", tmp_path / "repo", keys.ENV_FILE)
    assert s.script == common.RELEASE / "tools" / "learning_image.py"
    assert (s.state_root, s.plans_root, s.lock_path) == (root / "images", root / "image-plans", root / "images.lock")
    assert (s.monthly_usd, s.learner_max_usd, s.max_total_usd) == (Decimal("7.5"), Decimal("50"), Decimal("120.0"))
    assert s.timeout_s == 33 and local(tmp_path / "x").image_settings(Path("/w")).worktree == Path("/w")


def test_the_renderer_is_the_releases_study_site_with_a_pdf_cache_per_learner(tmp_path):
    r = publish.renderer(local(tmp_path))
    assert r.study_site == common.RELEASE / "packages" / "study-site"
    assert r.pdf_cache == tmp_path / "state-root" / "state" / "pdf-cache" / "barna" and r.build_s == 44


def test_the_generation_receipt_lists_the_learners_ledger_outputs(tmp_path):
    loc = local(tmp_path)
    settings = loc.image_settings()
    ledger = {"request_id": settings.request_id, "jobs": {
        "barna-x": {"learner": "barna", "attempts": [{"state": "accepted", "sha256": "b" * 64, "preview_sha256": "a" * 64}]},
        "benedek-x": {"learner": "benedek", "attempts": [{"state": "generated", "sha256": "c" * 64}]}}}
    from school_notes2.state.files import write_json
    write_json(settings.state_dir / "ledger.json", ledger)
    changed = []
    figure_close.generation_ledger(loc, loc.repo, changed)
    assert changed == [figure_close.LEDGER]
    assert safefs.read_json(loc.repo, figure_close.LEDGER) == {"rights": "generated", "outputs": ["a" * 64, "b" * 64]}
    figure_close.generation_ledger(loc, loc.repo, changed)
    assert changed == [figure_close.LEDGER]                     # unchanged: not written again


def test_reader_bookkeeping_keeps_figure_verdicts_and_ages_reader_verdicts(tmp_path):
    repo = local(tmp_path).repo
    safefs.write_text(repo, "wiki/a/p.md", "---\ntitle: P\n---\n# P\n\nSzöveg.\n")
    figure = {"role": "figure-review", "file": "wiki/a/gone.md", "id": "f", "key": "k"}
    records = [figure,
               {"role": "reader", "file": "wiki/a/p.md", "key": page_key(repo, "wiki/a/p.md")},
               {"role": "reader", "file": "wiki/a/gone.md", "key": "x"}]
    safefs.write_json(repo, insert.VERDICTS, records)
    machine_data.reader_bookkeeping(repo)
    assert safefs.read_json(repo, insert.VERDICTS) == records[:2]          # the deleted page's reader verdict goes
    safefs.write_text(repo, "wiki/a/p.md", "---\ntitle: P\n---\n# P\n\nMás szöveg.\n")
    machine_data.reader_bookkeeping(repo)
    assert [r["role"] for r in safefs.read_json(repo, insert.VERDICTS)] == ["figure-review", "reader-history"]
