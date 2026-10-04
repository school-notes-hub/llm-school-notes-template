"""Publication-preview hashes stay in host state even if the worktree copy crashes."""

from types import SimpleNamespace

import pytest

from school_notes2.images import generate
from school_notes2.state import safefs
from school_notes2.state.files import read_json, write_json
from school_notes2.wiki.pages import sha256


@pytest.mark.parametrize("crash", [False, True])
def test_preview_records_publication_hash_before_copy(tmp_path, monkeypatch, crash):
    repo, state = tmp_path / "repo", tmp_path / "state"
    repo.mkdir()
    state.mkdir()
    safefs.write_bytes(state, "sample-plan/1/image.png", b"original")
    safefs.write_bytes(state, "sample-plan/1/publication.webp", b"publication")
    write_json(state / "ledger.json", {"jobs": {"sample-plan": {"learner": "sample", "attempts": [
        {"number": 1, "state": "generated", "sha256": sha256(state, "sample-plan/1/image.png")}]}}})
    settings = SimpleNamespace(learner="sample", worktree=repo, state_dir=state,
                               plans_dir=state, ledger=lambda: read_json(state / "ledger.json"))
    digest = sha256(state, "sample-plan/1/publication.webp")
    monkeypatch.setattr(generate, "call", lambda *a, **kw: {
        "path": str(state / "sample-plan/1/publication.webp"), "sha256": digest})
    job = {"id": "sample-plan", "target": "target", "role": "banner"}
    if crash:
        with monkeypatch.context() as patch:
            def fail(*a, **kw):
                raise RuntimeError("power loss")
            patch.setattr(safefs, "copy_in", fail)
            with pytest.raises(RuntimeError, match="power loss"):
                generate._preview(settings, job, {"number": 1})
        assert settings.ledger()["jobs"][job["id"]]["attempts"][0]["preview_sha256"] == digest
    result = generate._preview(settings, job, {"number": 1})
    assert sha256(repo, result["preview"]) == digest
    assert settings.ledger()["jobs"][job["id"]]["attempts"][0]["preview_sha256"] == digest
