"""Regressions from the independent unit 2a review (K-1 through K-12)."""

import hashlib

import pytest

from school_notes2.figures import commissions, context, inputs, insert, machine, pending, review
from school_notes2.reader import verdicts
from school_notes2.state import safefs
from school_notes2.wiki import markers
from school_notes2.wiki.check import check_links
from school_notes2.wiki.guard import Change, GuardInput, run
from test_insert import receipt
from test_review import fake_render, make_run, success


def assignment(brief):
    return {k: brief[k] for k in ("id", "page", "kind")}


@pytest.mark.parametrize("problem,expected", [
    ("schema", "alt"), ("missing", "missing figure.json"), ("file", "missing file"),
    ("anchor", "exactly once"), ("outside", "outside"), ("crop", "bounds"),
    ("alt", "one line"), ("svg", "editable source"),
])
def test_p1_reports_candidate_problems(repo, make_figure, problem, expected):
    brief, candidate = make_figure()
    if problem == "schema":
        del candidate["alt"]
    elif problem == "file":
        candidate["asset"] = "wiki/assets/absent.png"
    elif problem == "anchor":
        brief["anchor"] = "Missing"
    elif problem == "outside":
        text = safefs.read_text(repo, brief["page"]).replace("<!-- figure:", "# Other\n\n<!-- figure:")
        safefs.write_text(repo, brief["page"], text)
    elif problem == "crop":
        brief["source_image"] = {"path": candidate["asset"], "crop": [0, 0, 1001, 500]}
    elif problem == "alt":
        candidate["alt"] = "one\ntwo"
    elif problem == "svg":
        candidate["asset"] = "wiki/assets/forces.svg"
        safefs.write_text(repo, candidate["asset"], '<svg xmlns="http://www.w3.org/2000/svg"/>')
    safefs.write_json(repo, ".school-notes/figures/forces.json", brief)
    safefs.write_json(repo, ".school-notes/figures/forces/figure.json", candidate)
    if problem == "missing":
        safefs.unlink(repo, ".school-notes/figures/forces/figure.json")
    errors = commissions.check(repo, [assignment(brief)])
    assert any(expected in e["message"] for e in errors), errors


def test_p1_all_figures_checked_and_explicit_failure_is_valid(repo, make_figure):
    briefs = [make_figure(fid)[0] for fid in ("a", "b", "c")]
    for fid in ("a", "b"):
        safefs.write_json(repo, f".school-notes/figures/{fid}/figure.json", {"state": "candidate"})
    safefs.write_json(repo, ".school-notes/figures/c/figure.json", {"state": "failed", "reason": "renderer unavailable"})
    errors = commissions.check(repo, list(map(assignment, reversed(briefs))))
    assert [e["file"] for e in errors] == [f".school-notes/figures/{fid}/figure.json" for fid in ("a", "b")]


@pytest.mark.parametrize("prefix,suffix", [("- ", ""), ("  ", ""), ("Text ", ""), ("", " text")])
def test_marker_must_be_its_own_unindented_line(repo, make_figure, prefix, suffix):
    brief, _ = make_figure()
    text = safefs.read_text(repo, brief["page"]).replace("<!-- figure: forces -->", prefix + "<!-- figure: forces -->" + suffix)
    safefs.write_text(repo, brief["page"], text)
    with pytest.raises(ValueError, match="stand alone"):
        commissions.validate_assignments(repo, [assignment(brief)])


def test_notebook_drawings_need_assigned_notebook_commissions(repo, make_figure):
    brief, candidate = make_figure()
    drawing = {"figure": brief["id"], "source": "sources/page.png", "crop": "top drawing"}
    assert commissions.check(repo, [], [drawing])
    assert commissions.check(repo, [assignment(brief)], [drawing])
    brief.update(kind="notebook-drawing", source_image={"path": candidate["asset"], "crop": [0, 0, 100, 100]})
    candidate["corrections"] = []
    safefs.write_json(repo, ".school-notes/figures/forces.json", brief)
    safefs.write_json(repo, ".school-notes/figures/forces/figure.json", candidate)
    assert not commissions.check(repo, [assignment(brief)], [drawing])


def test_anchored_lesson_topic_is_the_primary_unit(repo, make_figure):
    make_figure()
    brief, _ = make_figure("lesson", "wiki/physics/lesson.md")
    text = safefs.read_text(repo, brief["page"]).replace("type: topic", 'type: lesson-notes\nlessons:\n  - topics: ["forces.md#forces"]')
    safefs.write_text(repo, brief["page"], text)
    assert commissions.topic(repo, brief["page"]) == "wiki/physics/forces.md"


@pytest.mark.parametrize("record", ["accepted", "pending", "block"])
def test_id_cannot_be_reused_on_another_page(repo, make_figure, record):
    old, candidate = make_figure()
    if record == "accepted":
        insert.insert(repo, old, receipt(repo, old, candidate), at="date")
    elif record == "pending":
        pending.record(repo, old, "run-1", [])
        safefs.write_text(repo, old["page"], "# Forces\n")
    else:
        safefs.write_text(repo, old["page"], markers.wrap("figure-forces", "old"))
    brief, _ = make_figure(page="wiki/physics/other.md")
    with pytest.raises(ValueError, match="already"):
        commissions.validate_assignments(repo, [assignment(brief)])
    with pytest.raises(ValueError, match="already"):
        pending.record(repo, brief, "run-2", [])


def test_two_replacements_in_one_section_survive_insertion_and_resume(repo, make_figure):
    pairs = []
    for fid in ("first", "second"):
        asset = f"wiki/assets/physics/old-{fid}.png"
        safefs.write_bytes(repo, asset, b"old")
        brief, candidate = make_figure(fid, replaces=asset, decision_reason={"code": "c", "text": "correction"})
        text = safefs.read_text(repo, brief["page"])
        safefs.write_text(repo, brief["page"], text + f"![old](../assets/physics/old-{fid}.png)\n\n<!-- image-description\nobserved: old\n-->\n")
        pairs.append((brief, candidate))
    judged = [receipt(repo, b, c) for b, c in pairs]
    for (brief, _), result in zip(pairs, judged):
        insert.insert(repo, brief, result, at="date")
    for (brief, _), result in zip(pairs, judged):
        insert.insert(repo, brief, result, at="date")
    assert not insert.invalidated(repo)
    assert len(markers.names(safefs.read_text(repo, pairs[0][0]["page"]))) == 2


def test_other_use_machine_blocks_do_not_change_key(repo, make_figure):
    brief, candidate = make_figure()
    page = "wiki/physics/other.md"
    text = "# Other\n\nContext.\n\n![force](../assets/physics/forces.png)\n"
    safefs.write_text(repo, page, text)
    key = context.verdict_key(repo, brief, candidate)
    safefs.write_text(repo, page, text + markers.wrap("pending", "Pending") + markers.wrap("figure-other", "image"))
    assert context.verdict_key(repo, brief, candidate) == key
    safefs.write_text(repo, page, text.replace("Context.", "Different context."))
    assert context.verdict_key(repo, brief, candidate) != key


def test_mermaid_reordering_keeps_keys_and_only_new_content_needs_commission(repo, make_figure):
    brief, candidate = make_figure()
    source = "graph LR\n A --> B\n"
    candidate.pop("asset")
    candidate["mermaid"] = hashlib.sha256(source.encode()).hexdigest()
    safefs.write_json(repo, ".school-notes/figures/forces/figure.json", candidate)
    text = safefs.read_text(repo, brief["page"]) + f"```mermaid\n{source}```\n"
    safefs.write_text(repo, brief["page"], text)
    insert.insert(repo, brief, receipt(repo, brief, candidate), at="date")
    extra = "# Other\n\n```mermaid\ngraph LR\n C --> D\n```\n\n"
    old = text + "\n" + extra
    new = extra + text
    safefs.write_text(repo, brief["page"], new)
    assert not run(GuardInput(repo, [Change(brief["page"], "modified")], lambda p: old.encode()))
    assert not insert.invalidated(repo)
    # 6b: a new inline Mermaid needs no commission.
    assert not run(GuardInput(repo, [Change(brief["page"], "modified")], lambda p: text.encode()))


@pytest.mark.parametrize("target", ["force.svg", "https://example.org/a.png", "//example.org/a.png", "data:image/png;base64,eA=="])
def test_check_refuses_non_asset_images(repo, target):
    assert check_links(repo, "wiki/physics/forces.md", f"![force]({target})")


def test_guard_covers_changed_images_outside_assets(repo, make_figure):
    brief, _ = make_figure()
    asset = "wiki/physics/force.png"
    safefs.write_text(repo, brief["page"], "# Forces\n\n![force](force.png)\n")
    safefs.write_bytes(repo, asset, b"old")
    base = {p: safefs.read_bytes(repo, p) for p in safefs.walk_files(repo)}
    safefs.write_bytes(repo, asset, b"new")
    assert run(GuardInput(repo, [Change(asset, "modified")], base.get))


@pytest.mark.parametrize("viewbox", ["0,0,100,50", "nonsense", "0 0", "0 0 x 50"])
def test_svg_viewbox_never_crashes_hints(viewbox):
    assert isinstance(machine.svg_hints(f'<svg viewBox="{viewbox}"/>', {"must_show": []}, {}), list)


def test_deleted_page_prunes_verdict_without_stale_noise(repo, make_figure):
    brief, candidate = make_figure()
    insert.insert(repo, brief, receipt(repo, brief, candidate), at="date")
    safefs.unlink(repo, brief["page"])
    assert not verdicts.invalidate(repo)
    assert safefs.read_json(repo, insert.VERDICTS) == []


@pytest.mark.parametrize("crash_at", ["output", "receipt", "none"])
def test_one_bad_render_does_not_fail_batch_and_resume_keeps_outcomes(repo, make_figure, tmp_path, log, monkeypatch, crash_at):
    briefs = [make_figure(fid)[0] for fid in ("a", "b", "c", "d")]
    seen = []
    def renderer(kind, data, fid):
        seen.append(fid)
        if fid == "b":
            raise ValueError("unsupported SVG element")
        return fake_render(kind, data, fid)
    def invoke(actual, **kwargs):
        assert [f["id"] for f in safefs.read_json(actual.mounts.in_dir, "assigned.json")["figures"]] == ["a", "c", "d"]
        value = success(actual)
        if crash_at == "output":
            raise KeyboardInterrupt
        return value
    original = review._save
    if crash_at == "receipt":
        monkeypatch.setattr(review, "_save", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    run_args = (repo, briefs, "batch", make_run(tmp_path))
    if crash_at != "none":
        with pytest.raises(KeyboardInterrupt):
            review.run_batch(*run_args, render=renderer, log=log, invoke=invoke)
    else:
        review.run_batch(*run_args, render=renderer, log=log, invoke=invoke)
    monkeypatch.setattr(review, "_save", original)
    result = review.run_batch(*run_args, render=lambda *a: pytest.fail("rerender"), log=log,
                              invoke=lambda *a, **k: pytest.fail("duplicate call"))
    assert seen == ["a", "b", "c", "d"]
    assert review.for_figure(result, "b") == {"status": "pending", "reason": "unsupported SVG element"}
    for fid in ("a", "c", "d"):
        assert review.for_figure(result, fid)["status"] == "reviewed"


def test_other_use_caption_is_bound_even_in_a_generated_block(repo, make_figure):
    brief, candidate = make_figure()
    page = "wiki/physics/other.md"
    body = "![force](<../assets/physics/forces.png>)\n\nOther caption.\n\n<!-- image-description\nobserved: force\n-->"
    text = "# Other\n\nContext.\n\n" + markers.wrap("figure-other", body)
    safefs.write_text(repo, page, text)
    key = context.verdict_key(repo, brief, candidate)
    safefs.write_text(repo, page, text.replace("Other caption.", "A changed claim."))
    assert context.verdict_key(repo, brief, candidate) != key
