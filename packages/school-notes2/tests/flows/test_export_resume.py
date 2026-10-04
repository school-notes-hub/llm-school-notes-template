"""T-095: request filing and banner refresh reuse the existing atomic write journal."""

from types import SimpleNamespace

import pytest

from school_notes2.flows import learning, licensing
from school_notes2.figures import requests
from school_notes2.state import phase, safefs
from school_notes2.wiki import frontmatter, guard, markers
from tests.wiki.conftest import repo
from tests.wiki.test_guard import snapshot, run


@pytest.mark.parametrize("step", ["request", "banner"])
@pytest.mark.parametrize("crash", ["before", "after"])
def test_closure_writes_resume(repo, tmp_path, monkeypatch, step, crash):
    ctx = SimpleNamespace(notes_path=repo)
    task = phase.create(tmp_path / "tasks", "sample", "notes", "interactive", "prepared")
    if step == "request":
        rel = requests.PATH
        safefs.write_text(repo, "wiki/proba/elso.md", "# Téma\n\n<!-- figure-request: test -->\n")
        result = {"figure_requests": [{"id": "test", "page": "wiki/proba/elso.md", "source": "sources/proba/csomag/01.jpg",
                  "crop": "teljes kép", "purpose": "Tanulás", "origin": "unknown"}]}
        invoke = lambda t: licensing.refresh(ctx, t, result, [
            {"path": "sources/proba/csomag/01.jpg", "original_sha256": "a" * 64}])
    else:
        rel = "wiki/proba/2026-09-10-elso-jegyzet.md"
        safefs.write_text(repo, rel, frontmatter.set_keys(safefs.read_text(repo, rel), {"banner_from": "elso.md"}))
        invoke = lambda t: learning.refresh(ctx, t)
    base = snapshot(repo)
    real = safefs.write_text
    def interrupted(root, path, data, **kw):
        if path == rel:
            if crash == "after":
                real(root, path, data, **kw)
            raise RuntimeError("power loss")
        return real(root, path, data, **kw)
    with monkeypatch.context() as patch:
        patch.setattr(safefs, "write_text", interrupted)
        with pytest.raises(RuntimeError, match="power loss"):
            invoke(task)
    task = phase.load(task.dir)
    changed = [(p, "modified" if p in base else "added") for p, data in snapshot(repo).items() if base.get(p) != data]
    assert not run(repo, base, changed, tool_parts=task.get("tool_parts", {}),
                   tool_files=task.get("tool_writes", {}), pending_write=task.get("learning_pending"))
    invoke(task)
    first = snapshot(repo)
    invoke(phase.load(task.dir))
    assert snapshot(repo) == first
    if step == "banner":
        markers.check(safefs.read_text(repo, rel))
        assert "abra.svg" in markers.read(safefs.read_text(repo, rel), "lesson-banner")


def test_only_owner_session_can_edit_licenses(repo):
    safefs.write_json(repo, "docs/licenses.json", [])
    change = [guard.Change("docs/licenses.json", "added")]
    assert guard.run(guard.GuardInput(repo, change, lambda _: None, interactive=False))
    assert not guard.run(guard.GuardInput(repo, change, lambda _: None, interactive=True))


@pytest.mark.parametrize("crash", ["before", "after"])
def test_generated_rights_receipt_crash_resume(repo, tmp_path, monkeypatch, crash):
    from school_notes2.flows import handlers
    from school_notes2.wiki import public
    asset = "wiki/assets/fresh.webp"
    safefs.write_bytes(repo, asset, b"generated")
    digest = public.sha256(repo, asset)
    ctx = SimpleNamespace(notes_path=repo, image_settings=lambda: None, log=None)
    task = phase.create(tmp_path / "tasks", "sample", "notes", "interactive", "prepared")
    monkeypatch.setattr(handlers.image_generate, "generate", lambda *a, **kw: {
        "state": "generated", "number": 1, "sha256": "a" * 64, "preview_sha256": digest})
    real = safefs.write_text
    def interrupted(root, path, data, **kw):
        if crash == "after":
            real(root, path, data, **kw)
        raise RuntimeError("power loss")
    with monkeypatch.context() as patch:
        patch.setattr(safefs, "write_text", interrupted)
        with pytest.raises(RuntimeError, match="power loss"):
            handlers.generate(ctx, task, "fresh", None)
    handlers.generate(ctx, phase.load(task.dir), "fresh", None)
    assert public.media_receipt_rights(repo)(asset)[0] == "generated"
    safefs.write_bytes(repo, asset, b"changed")
    assert public.media_receipt_rights(repo)(asset) is None


@pytest.mark.parametrize("crash", ["before", "after"])
def test_source_note_publication_write_resumes(repo, tmp_path, monkeypatch, crash):
    from school_notes2.flows import steps
    task = phase.create(tmp_path / "tasks", "sample", "notes", "interactive", "prepared")
    ctx = SimpleNamespace(notes_path=repo)
    safefs.write_text(repo, "PROFILE.md", "* **Student**: Minta.\n")
    real = safefs.write_text
    def interrupted(root, path, data, **kw):
        if path == "publication/public.json":
            if crash == "after":
                real(root, path, data, **kw)
            raise RuntimeError("power loss")
        return real(root, path, data, **kw)
    with monkeypatch.context() as patch:
        patch.setattr(safefs, "write_text", interrupted)
        with pytest.raises(RuntimeError, match="power loss"):
            steps.generate_all(ctx, task)
    steps.generate_all(ctx, phase.load(task.dir))
    first = snapshot(repo)
    steps.generate_all(ctx, phase.load(task.dir))
    assert snapshot(repo) == first
    assert "A jegyzet Minta órai jegyzetei" in safefs.read_text(repo, "publication/public.json")


def test_licenses_and_requests_are_in_existing_commit_inventory():
    from school_notes2.git.finish import COMMIT_PATHS
    assert {"docs/licenses.json", "docs/figure-requests.json"} <= set(COMMIT_PATHS)
