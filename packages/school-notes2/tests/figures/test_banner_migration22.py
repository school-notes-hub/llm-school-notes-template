"""Unassigned headers and safe, content-addressed migration restarts."""

import hashlib

import pytest

from school_notes2.figures import migrate_pending, pending
from school_notes2.state import safefs
from school_notes2.wiki import banners


def test_existing_banner_needs_hash_bound_generation_proof(repo):
    page, asset = "wiki/m/t.md", "wiki/assets/header.svg"
    safefs.write_bytes(repo, asset, b"<svg/>")
    safefs.write_text(repo, page, "---\ntype: topic\n---\n![Header](../assets/header.svg)\nText.\n")
    safefs.write_json(repo, "publication/public.json", {"assets": [{"path": asset,
        "sha256": hashlib.sha256(b"<svg/>").hexdigest(), "rights": "authored"}]})
    body = lambda: safefs.read_text(repo, page).split("---\n", 2)[2]
    assert not banners.generated_header(repo, page, body())
    safefs.write_json(repo, "docs/evidence/image-generation/ledger.json", {
        "rights": "generated", "outputs": [hashlib.sha256(b"<svg/>").hexdigest()]})
    assert banners.generated_header(repo, page, body())
    safefs.write_bytes(repo, asset, b"<svg>changed</svg>")
    assert not banners.generated_header(repo, page, body())


def legacy(repo):
    for name, kind in [("topic", "topic"), ("summary", "chapter-summary"), ("index", None)]:
        meta = f"type: {kind}\n" if kind else ""
        safefs.write_text(repo, f"wiki/m/{name}.md", f"---\n{meta}title: Header\n---\n![Header](../assets/header.svg)\n\nLesson.\n")
    safefs.write_bytes(repo, "wiki/assets/header.svg", b"<svg/>")


@pytest.mark.parametrize("boundary", ["receipt", "pending", "page", "mark"])
def test_migration_headers_dry_run_restart_and_receipt_loss(repo, monkeypatch, boundary):
    legacy(repo)
    monkeypatch.setattr(migrate_pending, "historical", lambda *a: {})
    state = repo.parent / "state"
    before = {p: safefs.read_bytes(repo, p) for p in safefs.walk_files(repo, "wiki")}
    preview = migrate_pending.migrate(repo, state_dir=state, repo=object(), dry_run=True)
    assert len(preview["commissions"]) == 3 and not state.exists()
    assert before == {p: safefs.read_bytes(repo, p) for p in safefs.walk_files(repo, "wiki")}
    write = safefs.write_text
    fired = []
    target = {"receipt": migrate_pending.RECEIPT, "pending": pending.PATH,
              "page": "wiki/m/index.md", "mark": migrate_pending.MARK}[boundary]
    def crash(root, path, text, mode=0o644):
        write(root, path, text, mode)
        if path == target and not fired:
            fired.append(1)
            raise KeyboardInterrupt()
    monkeypatch.setattr(safefs, "write_text", crash)
    with pytest.raises(KeyboardInterrupt):
        migrate_pending.migrate(repo, state_dir=state, repo=object())
    migrate_pending.migrate(repo, state_dir=state, repo=object())
    entries = pending.load(repo)
    assert len(entries) == 3
    for entry in entries:
        brief = entry["commission"]
        assert brief["kind"] == "banner" and brief["replaces"] == "wiki/assets/header.svg"
        assert brief["decision_reason"]["code"] == "c" and entry["runs"] == 0
        text = safefs.read_text(repo, brief["page"])
        assert "![Header]" in text and text.count(f"<!-- image: {brief['id']} -->") == 1
    receipt = safefs.read_text(state, migrate_pending.RECEIPT)
    assert "Lesson." not in receipt and "purpose" not in receipt
    pending.record(repo, entries[0]["commission"], "real-run", [], attempted=True)
    safefs.unlink(state, migrate_pending.RECEIPT)
    assert migrate_pending.migrate(repo, state_dir=state, repo=object())["status"] == "already-migrated"
    assert pending.load(repo)[0]["runs"] == 1


@pytest.mark.parametrize("during_plan", [False, True])
def test_migration_stops_on_concurrent_page_edit(repo, monkeypatch, during_plan):
    legacy(repo)
    state = repo.parent / "state"
    monkeypatch.setattr(migrate_pending, "historical", lambda *a: {})
    page = "wiki/m/topic.md"
    if during_plan:
        plan = migrate_pending.plan
        def race(*args):
            result = plan(*args)
            safefs.write_text(repo, page, "New author text.\n")
            return result
        monkeypatch.setattr(migrate_pending, "plan", race)
    else:
        apply = migrate_pending.apply
        monkeypatch.setattr(migrate_pending, "apply", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            migrate_pending.migrate(repo, state_dir=state, repo=object())
        monkeypatch.setattr(migrate_pending, "apply", apply)
        safefs.write_text(repo, page, "New author text.\n")
    with pytest.raises(ValueError, match="migration input changed"):
        migrate_pending.migrate(repo, state_dir=state, repo=object())
    assert safefs.read_text(repo, page) == "New author text.\n"
    assert not safefs.is_file(repo, migrate_pending.MARK)


def test_migration_lists_missing_history_and_clears_poison(repo, make_figure, monkeypatch):
    brief, _ = make_figure()
    pending.record(repo, brief, "old", [{"severity": "hiba", "location": "f", "observed": "nem készült új jelölt", "expected": "new"}])
    monkeypatch.setattr(migrate_pending, "historical", lambda *a: {})
    result = migrate_pending.migrate(repo, state_dir=repo.parent / "state", repo=object())
    assert result["restored"] == [] and result["unrestored"] == [brief["id"]]
    assert pending.load(repo)[0]["defects"] == []
