"""Review K-1, K-5–K-8: explicit scope, usable retries and unchanged figure reuse."""

import io

from PIL import Image

from school_notes2.figures import context
from school_notes2.flows import inspection
from school_notes2.llm.argv import prompt
from school_notes2.state import safefs
from tests.conftest import record_render
from .helpers import install_reader


def figure(ctx, task, page):
    brief = {"id": "f", "page": page, "anchor": "Téma", "kind": "figure", "purpose": "Megértés",
             "must_show": ["erő"], "avoid_misreading": "irány", "taught_conventions": [],
             "text_complete_without_figure": True}
    candidate = {"state": "candidate", "asset": "wiki/assets/f.png", "alt": "Erő", "caption": "",
                 "form": "diagram", "tool": "test", "elements": [], "visible_text": [], "attempt": 1}
    data = io.BytesIO()
    Image.new("RGB", (20, 10), "white").save(data, format="PNG")
    safefs.write_bytes(ctx.notes_path, candidate["asset"], data.getvalue())
    record_render(ctx.notes_path, candidate["asset"])
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
    for role in ("reader-1", "recheck"):
        assert retry in prompt(role, grade=9)


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
