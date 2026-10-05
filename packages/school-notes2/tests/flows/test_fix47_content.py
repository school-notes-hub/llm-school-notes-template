"""Fix-47 on a real Git worktree: SVG provenance receipts and the public gate in cron."""

import io

import pytest
from PIL import Image

from school_notes2.flows import generation_receipts, steps
from school_notes2.state import safefs
from school_notes2.wiki import public, rights
from tests.flows.test_kiss46_content import commit, cron
from tests.flows.test_learning_checks import TOPIC, learning_run  # noqa: F401

SVG = "wiki/assets/proba/sajat.svg"


def link_svg(ctx, body='<svg xmlns="http://www.w3.org/2000/svg"><circle r="1"/></svg>\n'):
    safefs.write_text(ctx.notes_path, SVG, body)
    path = ctx.notes_path / TOPIC
    if "sajat.svg" not in path.read_text():
        path.write_text(path.read_text() + "\n![Saját ábra](../assets/proba/sajat.svg)\n")


def asset(ctx, rel):
    return next(a for a in safefs.read_json(ctx.notes_path, "publication/public.json")["assets"] if a["path"] == rel)


def test_svg_drawn_in_the_run_gets_a_receipt_and_is_authored(learning_run):
    """Védelmek-review 4: `authored` only with a provenance receipt (hash + run id)."""
    ctx, task = learning_run
    cron(task)
    link_svg(ctx)
    generation_receipts.refresh_svgs(ctx, task)
    receipt = safefs.read_json(ctx.notes_path, rights.SVG_RECEIPTS)
    assert receipt == {"rights": "authored", "svgs": [
        {"path": SVG, "sha256": public.sha256(ctx.notes_path, SVG), "run_id": task.run_id}]}
    steps.write_public(ctx, task)
    assert asset(ctx, SVG)["rights"] == "authored" and asset(ctx, SVG)["rightsEvidence"] == rights.SVG_RECEIPTS
    assert not task.get("public_problems")


def test_svg_without_a_receipt_is_refused_and_held_in_cron(learning_run):
    """An SVG that arrived outside a writer run (e.g. pushed, third party) has no receipt:
    the gate refuses it; in cron that is an item and a held release, never an owner stop."""
    ctx, task = learning_run
    cron(task)
    link_svg(ctx)
    commit(ctx, task)                       # in the base: this run did not draw it
    generation_receipts.refresh_svgs(ctx, task)
    assert not safefs.is_file(ctx.notes_path, rights.SVG_RECEIPTS)
    steps.write_public(ctx, task)           # no CheckFailed in cron
    assert [p["file"] for p in task.get("public_problems")] == [SVG]
    report = task.get("inspection_report")
    assert report and SVG in safefs.read_text(ctx.notes_path, report)
    task.data["mode"] = "interactive"
    task.save()
    with pytest.raises(steps.CheckFailed):  # a session gets the error back
        steps.write_public(ctx, task)


def test_svg_already_published_keeps_its_rights(learning_run):
    """A 2.5.1-accepted SVG listed in public.json with these bytes stays authored."""
    ctx, task = learning_run
    cron(task)
    link_svg(ctx)
    manifest = safefs.read_json(ctx.notes_path, "publication/public.json")
    manifest["assets"].append({"path": SVG, "sha256": public.sha256(ctx.notes_path, SVG),
                               "rights": "authored", "rightsEvidence": "docs/evidence/media/x/figure.json"})
    safefs.write_json(ctx.notes_path, "publication/public.json", manifest)
    commit(ctx, task)
    steps.write_public(ctx, task)
    assert not task.get("public_problems") and asset(ctx, SVG)["rights"] == "authored"
    link_svg(ctx, '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>\n')  # changed bytes in the run
    generation_receipts.refresh_svgs(ctx, task)
    steps.write_public(ctx, task)
    assert asset(ctx, SVG)["rightsEvidence"] == rights.SVG_RECEIPTS


def test_svg_embedding_a_raster_is_never_authored(learning_run):
    ctx, task = learning_run
    cron(task)
    link_svg(ctx, '<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/png;base64,AA=="/></svg>\n')
    generation_receipts.refresh_svgs(ctx, task)
    steps.write_public(ctx, task)
    assert [p["file"] for p in task.get("public_problems")] == [SVG]


def test_raster_without_rights_in_cron_is_an_item_and_a_held_release(learning_run):
    """Futás-review 6: `write_public` refusing an image no longer stops the learner."""
    ctx, task = learning_run
    cron(task)
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(buffer, "PNG")
    safefs.write_bytes(ctx.notes_path, "wiki/assets/proba/uj.png", buffer.getvalue())
    path = ctx.notes_path / TOPIC
    path.write_text(path.read_text() + "\n![Új kép](../assets/proba/uj.png)\n")
    before = safefs.read_text(ctx.notes_path, "publication/public.json")
    steps.write_public(ctx, task)
    assert task.get("public_problems")[0]["file"] == "wiki/assets/proba/uj.png"
    assert safefs.read_text(ctx.notes_path, "publication/public.json") == before
    path.write_text(path.read_text().replace("\n![Új kép](../assets/proba/uj.png)\n", ""))
    steps.write_public(ctx, task)
    assert not task.get("public_problems")  # fixed: the hold reason is gone
