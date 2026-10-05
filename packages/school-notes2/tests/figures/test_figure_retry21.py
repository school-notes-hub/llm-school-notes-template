"""Generated headers, real retries and a replay-safe one-time migration."""

import hashlib
from types import SimpleNamespace

import pytest

from school_notes2.figures import commissions, context, machine, migrate_pending, pending
from school_notes2.flows import correction_figures, review_phases
from school_notes2.state import safefs
from school_notes2.wiki import banners
from school_notes2.wiki.check_result import check_result


@pytest.mark.parametrize("kind", ["banner", "infographic"])
def test_generation_receipt_gate(repo, make_figure, kind):
    brief, candidate = make_figure(kind=kind)
    assert any("generation receipt" in e for e in machine.generation_errors(repo, brief, candidate))
    candidate["asset"] = "wiki/assets/physics/generated.webp"
    safefs.write_bytes(repo, candidate["asset"], b"generated preview")
    assert machine.generation_errors(repo, brief, candidate)
    safefs.write_json(repo, "docs/evidence/image-generation/ledger.json", {
        "rights": "generated", "outputs": [hashlib.sha256(b"generated preview").hexdigest()]})
    assert not machine.generation_errors(repo, brief, candidate)
    safefs.write_bytes(repo, candidate["asset"], b"changed preview")
    assert machine.generation_errors(repo, brief, candidate)


def test_banner_embedding_and_mandatory_marker(repo, make_figure):
    brief, candidate = make_figure(kind="banner")
    assert context.embedding(repo, brief, candidate)["alt"] == candidate["alt"]
    assert context.embedding(repo, brief, candidate)["caption"] == candidate["caption"]
    page = brief["page"]
    assert banners.check_required(repo, [page])  # A footer marker is no header.
    safefs.write_text(repo, page, "---\ntype: topic\ntitle: Forces\n---\n<!-- image: forces -->\n# Forces\n")
    assert not banners.check_required(repo, [page])
    candidate = {"state": "no-figure", "reason": "No header"}
    safefs.write_json(repo, ".school-notes/figures/forces/figure.json", candidate)
    with pytest.raises(ValueError, match="required banner"):
        commissions.candidate(repo, brief)


def test_only_real_attempts_count_and_missing_candidate_is_check_error(repo, make_figure):
    brief, _ = make_figure()
    first = pending.record(repo, brief, "one", [])
    safefs.unlink(repo, ".school-notes/figures/forces/figure.json")
    assert pending.record(repo, brief, "two", [])["runs"] == 1
    fetch = {"packages": [], "pages": [], "pending_figures": [first]}
    assert check_result(repo, {"status": "done"}, fetch, set())
    safefs.write_json(repo, ".school-notes/figures/forces/figure.json", {"state": "failed", "reason": "Render failed"})
    assert not check_result(repo, {"status": "done"}, fetch, set())
    assert pending.record(repo, brief, "two", [])["runs"] == 2
    assert pending.record(repo, brief, "two", [])["runs"] == 2


def test_defects_keep_review_when_writer_failed():
    old = [{"location": "arrow", "observed": "reversed", "expected": "forward"}]
    state = {"brief": {"id": "f"}, "candidate": {"state": "failed", "reason": "render failed"}}
    found = correction_figures.defects(state, {}, old)
    assert found[0] == old[0] and len(found) == 2
    assert correction_figures.defects(state, {}, found) == found


@pytest.mark.parametrize("boundary", ["page", "pending", "receipt"])
def test_migration_replay_and_no_second_reset(repo, make_figure, monkeypatch, boundary):
    brief, _ = make_figure(kind="banner")
    old = [{"location": "letters", "observed": "unreadable", "expected": "larger"}]
    pending.record(repo, brief, "one", [{"location": "f", "observed": "nem készült új jelölt", "expected": "new"}])
    monkeypatch.setattr(migrate_pending, "historical", lambda *a: {brief["id"]: old})
    write_json, write_text = safefs.write_json, safefs.write_text
    fired = []
    def save(root, path, value):
        write_json(root, path, value)
        if not fired and ((boundary == "pending" and path == pending.PATH) or
                          (boundary == "receipt" and path == migrate_pending.RECEIPT)):
            fired.append(1)
            raise KeyboardInterrupt()
    def text(root, path, value, mode=0o644):
        write_text(root, path, value, mode)
        if not fired and ((boundary == "page" and path == brief["page"]) or
                          (boundary == "pending" and path == pending.PATH)):
            fired.append(1)
            raise KeyboardInterrupt()
    monkeypatch.setattr(safefs, "write_json", save)
    monkeypatch.setattr(safefs, "write_text", text)
    with pytest.raises(KeyboardInterrupt):
        migrate_pending.migrate(repo, state_dir=repo.parent / "state", repo=object())
    migrate_pending.migrate(repo, state_dir=repo.parent / "state", repo=object())
    entry = pending.load(repo)[0]
    assert entry["runs"] == 0 and entry["run_ids"] == [] and not entry["owner_required"]
    assert entry["defects"] == old
    assert "<!-- image: forces -->" in safefs.read_text(repo, brief["page"])
    pending.record(repo, brief, "new-run", old)
    migrate_pending.migrate(repo, state_dir=repo.parent / "state", repo=object())
    assert pending.load(repo)[0]["runs"] == 1


def test_history_restores_latest_unpoisoned_defects():
    import json
    def record(message):
        return json.dumps([{"commission": {"id": "f"}, "defects": [{"observed": message}]}]).encode()
    blobs = {"latest": record("nem készült új jelölt"), "good": record("wrong arrow"), "older": record("old")}
    git = SimpleNamespace(out=lambda *a: "latest\ngood\nolder\n",
                          run=lambda *a, **k: SimpleNamespace(returncode=0, stdout=blobs[a[1].split(":")[0]]))
    assert migrate_pending.historical(git, {"f"}) == {"f": [{"observed": "wrong arrow"}]}


@pytest.mark.parametrize("boundary", ["marker", "pending"])
def test_nightly_rejection_resumes_without_duplicate_queue(repo, make_figure, monkeypatch, boundary):
    from school_notes2.figures import rejected
    from school_notes2.review import night_figures
    brief, candidate = make_figure()
    page = brief["page"]
    safefs.write_text(repo, page, safefs.read_text(repo, page).replace("<!-- figure: forces -->", "![F](../assets/physics/forces.png)"))
    spec = night_figures.discover(repo, {"topic": page, "pages": [page]})[0]
    verdict = {"defects": [{"location": "arrow", "observed": "wrong", "expected": "right"}],
               "text_mismatch": [], "observed": "arrow"}
    entry = rejected.request(spec, brief, verdict, night_figures.fingerprint(repo, spec))
    original = safefs.write_text
    fired = []
    def crash(root, path, value, mode=0o644):
        original(root, path, value, mode)
        if not fired and path == (page if boundary == "marker" else pending.PATH):
            fired.append(1)
            raise KeyboardInterrupt()
    monkeypatch.setattr(safefs, "write_text", crash)
    with pytest.raises(KeyboardInterrupt):
        rejected.apply(repo, [entry])
    rejected.apply(repo, [entry])
    rejected.apply(repo, [entry])
    assert pending.load(repo)[0]["runs"] == 0
    assert safefs.read_text(repo, page).count(f"<!-- figure: {entry['commission']['id']} -->") == 1


@pytest.mark.parametrize("inherited", [False, True])
def test_p1_rejects_drawn_banner_even_with_invalid_inherited_context(repo, make_figure, inherited):
    brief, _ = make_figure(kind="banner")
    assignment = {k: brief[k] for k in ("id", "page", "kind")}
    fetch = {"packages": [], "pages": [], "pending_figures": [{"commission": brief}] if inherited else []}
    result = {"status": "done", "figures": [] if inherited else [assignment]}
    problems = check_result(repo, result, fetch, set(), base_content=lambda _: None)
    assert any("generation receipt" in p["message"] for p in problems)
