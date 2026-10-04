"""Review K-1, K-5–K-8: explicit scope, usable retries and unchanged figure reuse."""

import io

import pytest
from PIL import Image

from school_notes2.figures import context, pending
from school_notes2.flows import correction, inspection, review_phases
from school_notes2.llm.argv import prompt
from school_notes2.reader import calls, contracts, inputs, units, verdicts
from school_notes2.review import relations
from school_notes2.state import phase, safefs
from school_notes2.wiki.check_result import check_result
from .test_phases import finding, install_reader
from .test_reader import pass1


def figure(ctx, task, page):
    brief = {"id": "f", "page": page, "anchor": "Téma", "kind": "figure", "purpose": "Megértés",
             "must_show": ["erő"], "avoid_misreading": "irány", "taught_conventions": [],
             "text_complete_without_figure": True}
    candidate = {"state": "candidate", "asset": "wiki/assets/f.png", "alt": "Erő", "caption": "",
                 "form": "diagram", "tool": "test", "elements": [], "visible_text": [], "attempt": 1}
    data = io.BytesIO()
    Image.new("RGB", (20, 10), "white").save(data, format="PNG")
    safefs.write_bytes(ctx.notes_path, candidate["asset"], data.getvalue())
    safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "\n<!-- figure: f -->\n")
    safefs.write_json(ctx.notes_path, ".school-notes/figures/f.json", brief)
    safefs.write_json(ctx.notes_path, ".school-notes/figures/f/figure.json", candidate)
    task.update(inspection_result={"status": "done", "figures": [{k: brief[k] for k in ("id", "page", "kind")}]})
    return brief, candidate


def acceptance(ctx, brief, candidate):
    return {"status": "reviewed", "model": "independent/high", "review": {
        "figures": [{"id": brief["id"], "key": context.verdict_key(ctx.notes_path, brief, candidate),
                     "verdict": "accept", "observed": "Erő", "defects": [],
                     "text_mismatch": [], "relates_to": None}], "owner_notes": []}}


def test_complete_owner_text_and_format_error_in_prompts():
    text = prompt("reader-1", grade=9)
    assert ('szigorúan ellenőrzi minden oldalon: logikusan épül-e fel (minden fogalom megvan-e, '
            'mielőtt használjuk; a tananyag menetét követi-e, nem a forrás – dia, oldal – sorrendjét); '
            'érthető-e a nyelvezete a korosztálynak (ISO 24495-1, `content-and-curriculum.md` „Plain language”); '
            'kontextusba helyezi-e az olvasót (miről szól, mikor, hol, miért fontos); rajta van-e minden '
            'információ, hogy a tanuló forrás nélkül megtanulhassa. A jegyzetnek úgy kell felépítenie '
            'az átadandó anyagot, ahogy egy tanuló, az emberi agy be tudja fogadni: lépésről lépésre, '
            'egymásra épülve; nem ugrálhat a témák között.') in text
    retry = next(s for s in prompt("figure-review", grade=9).splitlines() if '/in/format-error.json' in s)
    for role in ("reader-1", "reader-2", "recheck"):
        assert retry in prompt(role, grade=9)


def test_context_verdict_is_ignored_but_finding_survives_one_call(setup, monkeypatch):
    ctx, task, page = setup
    other = "wiki/m/summary.md"
    safefs.write_text(ctx.notes_path, other, "---\ntype: summary\n---\n# Összefoglaló\n\n[Topic](topic.md)\n")
    view = task.dir / "view"
    inputs.preview(ctx.notes_path, view, [])
    unit = units.collect(ctx.notes_path, [page])[0]
    folder = task.dir / "input"
    inputs.prepare(ctx.notes_path, view, unit, folder, lambda _: "")
    assert safefs.read_json(folder, "assigned.json") == {"pages": [{"file": page, "key": unit["keys"][page]}]}
    assert [(p["file"], p["role"]) for p in safefs.read_json(folder, "pages.json")] == [
        (page, "assigned"), (other, "context")]
    invoked = []
    def invoke(role, **kwargs):
        from types import SimpleNamespace
        invoked.append(1)
        supplied = safefs.read_json(role.mounts.in_dir, "assigned.json")
        assert supplied == {"pages": [{"file": page, "key": unit["keys"][page]}]}
        assert {p["file"] for p in safefs.read_json(role.mounts.in_dir, "pages.json")
                if p["role"] == "context"} == {other}
        extra = {**finding(other), "quote": "Összefoglaló"}
        return SimpleNamespace(output={"pages": pass1(page)["pages"] + pass1(other, [extra])["pages"],
                                       "findings": [extra], "owner_notes": []})
    monkeypatch.setattr(calls.launch, "run_headless", invoke)
    inspection.prepare(ctx, task)
    inspection.inspect(ctx, task)
    assert invoked == [1]
    assert verdicts.valid(ctx.notes_path, page) is not None
    assert verdicts.valid(ctx.notes_path, other) is None
    record = next(iter(relations.inventory(ctx.notes_path)["items"].values()))
    assert record["file"] == other and not record["unlocated"] and record["status"] == "open"
    assert record["outside_assignment"]
    assert correction.assigned(ctx, task) == []
    assert record["quote"] == "Összefoglaló"
    for pages in ([], pass1(page)["pages"] * 2):
        with pytest.raises(ValueError, match="exactly one"):
            contracts.check({"pages": pages, "findings": [], "owner_notes": []},
                            "reader-1", {"pages": [{"file": page}]})


@pytest.mark.parametrize("damage", ["marker", "commission", "page"])
def test_pending_contract_checked_in_p1_and_failed_in_p2(setup, monkeypatch, damage):
    ctx, task, page = setup
    brief, _ = figure(ctx, task, page)
    entry = pending.record(ctx.notes_path, brief, "previous", [])
    task.update(pending_figures=[entry], inspection_result={"status": "done"})
    if damage == "marker":
        safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page).replace("<!-- figure: f -->", ""))
    else:
        safefs.unlink(ctx.notes_path, page if damage == "page" else ".school-notes/figures/f.json")
    fetch = {"packages": [], "pages": [], "pending_figures": [entry]}
    assert check_result(ctx.notes_path, {"status": "done"}, fetch, set())
    install_reader(monkeypatch, page)
    review_phases.advance(ctx, task, lambda _: None)
    assert task.phase == "finishing" and task.data["needs_owner"] is None
    assert task.get("inspection_figures")[0]["candidate"]["state"] == "failed"
    assert pending.load(ctx.notes_path)[0]["defects"]
    review_phases.finalize(ctx, phase.load(task.dir))
    assert pending.load(ctx.notes_path)[0]["runs"] == 2


def test_figure_key_reuses_reader_and_figure_review_until_changed(setup, monkeypatch):
    ctx, task, page = setup
    brief, candidate = figure(ctx, task, page)
    invoked = install_reader(monkeypatch, page)
    figures = []
    def review(*args):
        figures.append(1)
        return acceptance(ctx, brief, candidate)
    monkeypatch.setattr(inspection, "figures", review)
    for attempt in (1, 2):
        task.update(attempt=attempt)
        inspection.prepare(ctx, task)
        inspection.inspect(ctx, task)
    assert invoked == ["reader-1"] and figures == [1]
    candidate["alt"] = "Megváltozott irány"
    safefs.write_json(ctx.notes_path, ".school-notes/figures/f/figure.json", candidate)
    task.update(attempt=3)
    inspection.prepare(ctx, task)
    inspection.inspect(ctx, task)
    assert invoked == ["reader-1", "reader-1"] and figures == [1, 1]
