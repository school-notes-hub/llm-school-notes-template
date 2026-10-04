"""Inherited generated candidates keep their host receipt through correction."""

from types import SimpleNamespace

import pytest

from school_notes2.figures import inputs
from school_notes2.flows import correction, inspection
from school_notes2.state import phase, safefs
from school_notes2.wiki.pages import sha256
from .test_review_fixes import figure


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("crash", [False, True])
def test_empty_figure_result_refreshes_inherited_candidate(setup, monkeypatch, learner, crash):
    ctx, task, page = setup
    brief, candidate = figure(ctx, task, page)
    safefs.unlink(ctx.notes_path, "wiki/assets/render.json")
    digest = sha256(ctx.notes_path, candidate["asset"])
    ctx.image_settings = lambda: SimpleNamespace(learner=learner, ledger=lambda: {"jobs": {"job": {
        "learner": learner, "attempts": [{"state": "generated", "preview_sha256": digest}]}}})
    task.update(inspection_figures=[{"brief": brief, "candidate": candidate}])
    root = inspection.folder(task) / "correction"
    saved = {"status": "done", "result": {"status": "done", "figures": []}}
    if crash:
        write = safefs.write_text
        def interrupted(repo, path, text, **kw):
            write(repo, path, text, **kw)
            if path == "docs/evidence/image-generation/ledger.json":
                raise RuntimeError("power loss")
        with monkeypatch.context() as patch:
            patch.setattr(safefs, "write_text", interrupted)
            with pytest.raises(RuntimeError, match="power loss"):
                correction.apply(ctx, task, root, saved)
        task = phase.load(task.dir)
    correction.apply(ctx, task, root, saved)
    assert task.get("inspection_figures")[0]["candidate"]["state"] == "candidate"
    prepared = inputs.prepare(ctx.notes_path, [brief], task.dir / "review-input",
                              lambda kind, data, fid: data)
    assert not prepared["failed"] and len(prepared["figures"]) == 1
