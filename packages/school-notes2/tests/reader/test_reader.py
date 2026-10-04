from dataclasses import replace
from types import SimpleNamespace

import pytest

from school_notes2.flows import inspection
from school_notes2.llm import launch
from school_notes2.reader import calls, contracts, inputs, report, units, verdicts
from school_notes2.state import safefs
from school_notes2.state.errors import BadWork, Transient, WaitingQuota
from school_notes2.wiki import frontmatter, markers


def pass1(page, findings=None):
    return {"pages": [{"file": page, "verdict": "changes" if findings else "ok", "first_glance": "Téma"}],
            "findings": findings or [], "owner_notes": []}


def test_blind_input_physical_allowlist_and_final_candidate(setup):
    ctx, task, page = setup
    repo = ctx.notes_path
    safefs.write_text(repo, "sources/secret.md", "source-secret")
    safefs.write_text(repo, "references/secret.md", "reference-secret")
    safefs.write_text(repo, "docs/evidence/secret.md", "evidence-secret")
    safefs.write_json(repo, ".school-notes/check.json", [{"secret-list": True}])
    safefs.write_text(repo, page, safefs.read_text(repo, page) + "\n<!-- figure: f -->\n")
    safefs.write_bytes(repo, "wiki/assets/m/f.png", b"candidate")
    brief = {"id": "f", "page": page, "kind": "figure"}
    candidate = {"state": "candidate", "asset": "wiki/assets/m/f.png", "alt": "Lefelé", "caption": "Gyorsulás",
                 "form": "image", "tool": "test", "elements": [], "visible_text": [], "attempt": 1}
    safefs.write_json(repo, ".school-notes/figures/f/figure.json", candidate)
    view = task.dir / "view"
    inputs.preview(repo, view, [brief])
    unit = units.collect(repo, [page])[0]
    folder = task.dir / "blind/in"
    inputs.prepare(repo, view, unit, folder, lambda _: "old")
    assert safefs.walk_files(folder) == ["assigned.json", "pages.json"]
    assert all(p.startswith("wiki/") for p in safefs.walk_files(view))
    text = safefs.read_text(folder, "pages.json")
    assert "Lefelé" in text and "Gyorsulás" in text and "figure: f" not in text
    assert not any(secret in text for secret in ("source-secret", "reference-secret", "secret-list", "evidence-secret"))


@pytest.mark.parametrize("kind,count", [("timeout", 1), ("format", 2), ("crash", 2)])
def test_bounded_failures_and_durable_fallback(setup, kind, count):
    ctx, task, page = setup
    folder = task.dir / "reader"
    folder.mkdir()
    configured = inspection.role(ctx, task)
    attempts = []
    def fail(*a, **kw):
        attempts.append(1)
        raise {"timeout": launch.TimedOut, "format": BadWork, "crash": Transient}[kind]("failure")
    args = (ctx.notes_path, ctx.notes_path, folder, "reader-1", {"pages": [{"file": page}]}, configured)
    assert calls.run(*args, log=ctx.log, invoke=fail)["status"] == "not_checked"
    assert calls.run(*args, log=ctx.log, invoke=fail)["status"] == "not_checked"
    assert len(attempts) == count


def test_recovers_completed_output_without_relaunch(setup):
    ctx, task, page = setup
    folder = task.dir / "reader"
    folder.mkdir()
    safefs.write_json(folder, "state.json", {"status": "ready", "attempts": ["running"]})
    safefs.write_json(folder, "out/review.json", pass1(page))
    def forbidden(*a, **kw):
        pytest.fail("completed call repeated")
    result = calls.run(ctx.notes_path, ctx.notes_path, folder, "reader-1", {"pages": [{"file": page}]},
                       inspection.role(ctx, task), log=ctx.log, invoke=forbidden)
    assert result["review"] == pass1(page)


def test_quota_wait_does_not_consume_retry(setup):
    ctx, task, page = setup
    folder = task.dir / "reader"
    folder.mkdir()
    def quota(*a, **kw):
        raise WaitingQuota("weekly quota")
    with pytest.raises(WaitingQuota):
        calls.run(ctx.notes_path, ctx.notes_path, folder, "reader-1", {"pages": [{"file": page}]},
                  inspection.role(ctx, task), log=ctx.log, invoke=quota)
    assert safefs.read_json(folder, "state.json")["attempts"] == []


def test_exact_coverage_and_no_family_questions(setup):
    _, _, page = setup
    with pytest.raises(ValueError):
        contracts.check({**pass1(page), "family_questions": []}, "reader-1", {"pages": [{"file": page}]})
    with pytest.raises(ValueError):
        contracts.check(pass1(page), "reader-1", {"pages": []})
    hit = {"hit_id": "H1", "verdict": "hiba", "covered_by": "F-2", "reason": "hiba"}
    with pytest.raises(ValueError, match="covered_by"):
        contracts.check({"hits": [hit], "owner_notes": []}, "reader-2", {"hits": ["H1"], "findings": ["F-1"]})
    with pytest.raises(ValueError):
        contracts.check({"items": [], "hits": [], "pages": [], "owner_notes": []}, "recheck", {"items": [], "hits": []})


def test_quote_whitespace_unlocated_and_generated_hash(setup):
    ctx, task, page = setup
    located = report.locate(ctx.notes_path, {"file": page, "quote": "A test\nlefelé   gyorsul."})
    assert not located["unlocated"]
    assert report.locate(ctx.notes_path, {"file": page, "quote": "nincs"})["unlocated"]
    key = units.page_key(ctx.notes_path, page)
    text = safefs.read_text(ctx.notes_path, page)
    safefs.write_text(ctx.notes_path, page, text + "\n" + markers.wrap("pending", "notice"))
    assert units.page_key(ctx.notes_path, page) == key
    verdicts.record(ctx.notes_path, [{"file": page, "verdict": "ok"}], {page: key}, "model", "today")
    assert verdicts.invalidate(ctx.notes_path) == []
    safefs.write_text(ctx.notes_path, page, text.replace("lefelé", "felfelé"))
    assert len(verdicts.invalidate(ctx.notes_path)) == 1
    assert verdicts.valid(ctx.notes_path, page) is None


def test_unit_routing_first_lesson_topic_and_source_only(setup):
    ctx, task, page = setup
    other = "wiki/m/other.md"
    safefs.write_text(ctx.notes_path, other, "---\ntype: topic\ntitle: Más\n---\n# Más\n")
    lesson = "wiki/m/lesson.md"
    safefs.write_text(ctx.notes_path, lesson, "---\ntype: lesson-notes\nlessons:\n  - topics: [topic.md, other.md]\n---\n# Óra\n")
    result = units.collect(ctx.notes_path, [lesson])
    assert [u["topic"] for u in result] == [page]
    assert result[0]["pages"] == sorted([lesson, page])
    assert units.collect(ctx.notes_path, ["sources/a.png", "docs/tool.json"]) == []


def test_reader_prompts_include_verbatim_plan_sentences():
    from school_notes2.llm.argv import prompt
    assert "Olvasd végig az egész oldalt úgy, mint a 14 éves olvasó, aki a forrást nem látja. Gépi listát most nem kapsz: mindent magad találj meg – a forrásról szóló mondatot diaszámmal vagy anélkül is." in prompt("reader-1")
    assert "Itt a gépi találatok. Mindegyikre egy ítélet és egy mondat indok; ha már jelezted, írd oda az F-azonosítót. A lista nem teljes, és amit az előbb találtál, az akkor is érvényes, ha itt nincs találat." in prompt("reader-2")
    assert "Ez nem teljes review. Tételenként ítélj: a javítás megoldotta-e (`ok`/`not-ok`); a vitatott tételnél fogadd el az indokot (`accept`), vagy egyszer, röviden válaszolj (`keep`). Az új találatokról ítélj." in prompt("recheck")


def test_mermaid_candidate_is_rendered_in_reader_view(setup):
    ctx, task, page = setup
    safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) +
                      "\n<!-- figure: flow -->\n\n```mermaid\ngraph LR; A-->B\n```\n")
    candidate = {"state": "candidate", "mermaid": 1, "alt": "Folyamat", "caption": "A után B.",
                 "form": "diagram", "tool": "mermaid", "elements": [], "visible_text": [], "attempt": 1}
    safefs.write_json(ctx.notes_path, ".school-notes/figures/flow/figure.json", candidate)
    brief = {"id": "flow", "page": page, "kind": "figure"}
    rendered = []
    def render(kind, data, fid):
        rendered.append((kind, data, fid))
        return b"rendered-png"
    view = task.dir / "view"
    inputs.preview(ctx.notes_path, view, [brief], render)
    text = safefs.read_text(view, page)
    assert "```mermaid" not in text and "figure: flow" not in text
    assert "flow.png" in text and "Folyamat" in text
    assert rendered == [("mermaid", b"graph LR; A-->B\n", "flow")]
    assert safefs.read_bytes(view, "wiki/assets/reader-preview/flow.png") == b"rendered-png"
