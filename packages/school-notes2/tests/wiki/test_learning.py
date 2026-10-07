"""Repair plan 7.2–7.6: public lesson log and private question/decision identity."""

from datetime import date

import pytest

from school_notes2.wiki import check, decisions, frontmatter, lesson_log, markers
from tests.wiki.conftest import LESSON_BODY, page, write

REL = "wiki/proba/elso.md"
NOTE = "wiki/proba/2026-09-10-elso-jegyzet.md"
DECISION = {"id": "elso-datum", "claim": "Az óra napja.", "answer": "Szeptember 29.",
            "by": "owner", "on": "2026-09-29"}
QUESTIONS = "\n# Nyitott kérdések\n\n<!-- q: elso-jel -->\n1. Melyik jelölést használjuk?\n"


@pytest.mark.parametrize("dates,expected", [
    ([None] * 4, "dátum nélküli óra"),
    (["2026-09-01"] * 3, "2026. 09. 01."),
    ([None, None, "2026-09-01", "2026-09-01", None, None],
     "dátum nélküli óra, 2026. 09. 01., dátum nélküli óra"),
    (["2026-09-01", "2026-09-02", "2026-09-01"],
     "2026. 09. 01., 2026. 09. 02., 2026. 09. 01."),
])
def test_source_line_collapses_only_consecutive_dates(dates, expected):
    meta = {"lessons": [{"date": value} for value in dates]}
    meta["lessons"][-1]["materials"] = ["Mérés (prezentáció)"]
    assert lesson_log.source_line(meta) == f"📎 Füzet: {expected} · Tanári anyag: Mérés (prezentáció)\n"


def test_yaml_on_is_a_key_and_real_booleans_still_work():
    meta = frontmatter.split("---\non: 2026-09-29\nflag: true\nother: false\n---\n").meta
    assert meta == {"on": date(2026, 9, 29), "flag": True, "other": False}
    assert not decisions.decision_problems({"decisions": [{**DECISION, "on": meta["on"]}]})


@pytest.mark.parametrize("field,value", [("id", "Ékezet"), ("claim", " "), ("answer", 2),
                                         ("by", "agent"), ("on", "2026-02-30"), ("on", True)])
def test_decision_fields_checked(field, value):
    assert decisions.decision_problems({"decisions": [{**DECISION, field: value}]})


def test_decision_shape_sort_and_uniqueness():
    for value in (None, {}, ["x"], [DECISION, DECISION], [{"id": "x"}],
                  [{**DECISION, "id": "z"}, DECISION]):
        assert decisions.decision_problems({"decisions": value})
    assert not decisions.decision_problems({"decisions": [DECISION]})


def test_questions_have_stable_unique_disjoint_ids():
    assert not decisions.question_problems(QUESTIONS, {"decisions": [DECISION]})
    for body in (QUESTIONS.replace("<!-- q: elso-jel -->\n", ""),
                 QUESTIONS + "\n<!-- q: elso-jel -->\n2. Másik?\n",
                 QUESTIONS.replace("elso-jel", "elso-datum"),
                 QUESTIONS.replace("elso-jel", "Bad_ID"),
                 "# Nyitott kérdések\n", QUESTIONS.replace("1.", "*"),
                 QUESTIONS.replace("1.", "2."), "<!-- q: stray -->\n# Példa\n1. Nem kérdés.\n"):
        assert decisions.question_problems(body, {"decisions": [DECISION]})
    # Nested alternatives, a quiz, and a code example are not question items.
    body = QUESTIONS + "\n   Magyarázat.\n\n   1. Egy lehetőség.\n\n# Kvíz\n\n1. Feladat.\n"
    body += "\n```md\n# Nyitott kérdések\n1. Példa.\n<!-- q: invalid_ID -->\n```\n"
    assert not decisions.question_problems(body, {})


def test_question_anchor_check_is_wired_to_check_files(repo):
    write(repo, REL, (repo / REL).read_text() + QUESTIONS.replace("<!-- q: elso-jel -->\n", ""))
    found = check.check_files(repo, [REL])
    # Fable 13: question form is a warning; it never fails a writer call.
    assert any("preceding" in i["message"] and i["severity"] == "warning" for i in found)
    assert not check.errors(found)


def test_source_line_uses_only_explicit_lesson_data():
    meta = {"lessons": [{"date": date(2026, 9, 29), "materials": ["A polisz (prezentáció)"]},
                        {"date_note": "valamikor", "materials": ["A polisz (prezentáció)", "Hellász (lap)"]}]}
    assert lesson_log.source_line(meta) == (
        "📎 Füzet: 2026. 09. 29., dátum nélküli óra · Tanári anyag: A polisz (prezentáció); Hellász (lap)\n")
    assert lesson_log.source_line({"lessons": [{}]}) == "📎 Füzet: dátum nélküli óra\n"
    assert lesson_log.source_line({"lessons": [{"materials": ["<script> (lap)"]}]}).count("<script>") == 0


@pytest.mark.parametrize("materials", ["x", None, [""], ["A cím"], ["a.pdf (lap)"],
                                      ["A cím\n (lap)"], [1]])
def test_materials_schema_rejects_bad_values(repo, materials):
    text = (repo / NOTE).read_text()
    lessons = frontmatter.split(text).meta["lessons"]
    lessons[0]["materials"] = materials
    write(repo, NOTE, frontmatter.set_keys(text, {"lessons": lessons}))
    found = check.check_files(repo, [NOTE])
    assert any("material" in i["message"] for i in found)
    # #16: a badly formed material name is a warning; only a non-list breaks the source line.
    assert bool(check.errors(found)) == (not isinstance(materials, list))


def test_source_block_position_and_idempotence():
    """I6: the tool block goes to the fixed place after the frontmatter, or where the writer
    left its marker; the writer's own lines are never searched or moved."""
    text = page("type: lesson-notes", "\n![Banner](a.svg)\n\n# Mit tanultunk ezen az órán\n")
    new = lesson_log.after_header(text, lesson_log.BLOCK, "📎 Füzet: dátum nélküli óra\n")
    assert new.index("---\n\n<!-- school-notes:generated lesson-sources -->") >= 0
    assert new.index("📎") < new.index("![Banner]") < new.index("# Mit tanultunk")
    assert lesson_log.after_header(new, lesson_log.BLOCK, "📎 Füzet: dátum nélküli óra\n") == new
    left = text.replace("# Mit", markers.wrap(lesson_log.BLOCK, "") + "\n# Mit")
    placed = lesson_log.after_header(left, lesson_log.BLOCK, "📎 Füzet: dátum nélküli óra\n")
    assert placed.index("![Banner]") < placed.index("📎") < placed.index("# Mit tanultunk")


def test_lesson_form_and_source_pointer_scope(repo):
    assert not lesson_log.form_problems(repo, NOTE, LESSON_BODY, frontmatter.split((repo / NOTE).read_text()).meta)
    for body in ("# Átirat\n", LESSON_BODY.replace("#elso-fogalom", ""),
                 LESSON_BODY.replace("elso.md", "nem-tema.md"), LESSON_BODY + "* Hiányzik a link.\n"):
        assert lesson_log.form_problems(repo, NOTE, body, frontmatter.split((repo / NOTE).read_text()).meta)
    for rel, extra in ((REL, markers.wrap(lesson_log.BLOCK, "📎 Füzet: 2026. 09. 29.\n")),
                       (NOTE, "\n📎 Kézzel írt utaló.\n")):
        write(repo, rel, (repo / rel).read_text() + extra)
        assert any("source pointer" in i["message"] and i["severity"] == "warning"
                   for i in check.check_files(repo, [rel]))


def test_overview_is_private_sorted_and_replaces_resolved_question(repo):
    for rel in (REL, "wiki/proba/masodik.md"):
        text = frontmatter.set_keys((repo / rel).read_text(), {"decisions": [DECISION]})
        write(repo, rel, text)
    out = decisions.overview(repo)
    assert out == decisions.overview(repo)
    assert out.index(REL) < out.index("wiki/proba/masodik.md")
    assert "Az óra napja." in out and "Szeptember 29." in out and "owner" in out
    assert not check.errors(check.check_files(repo, [REL]))


def test_public_manifest_excludes_private_decisions_and_anchors(repo):
    import json
    from school_notes2.wiki import public
    text = frontmatter.set_keys((repo / REL).read_text(),
                                {"decisions": [{**DECISION, "answer": "PRIVATE_CANARY"}]})
    write(repo, REL, text + QUESTIONS.replace("elso-jel", "private-question-canary"))
    write(repo, decisions.OVERVIEW, decisions.overview(repo))
    public.write(repo, lambda _: ("authored", "test"))
    manifest = (repo / "publication/public.json").read_text()
    assert "PRIVATE_CANARY" not in manifest and "private-question-canary" not in manifest
    assert "decisions" not in manifest and "dontesek.md" not in manifest
    assert all(p["path"].startswith("wiki/") for p in json.loads(manifest)["pages"])


@pytest.mark.parametrize("extension", ["doc", "docx", "xls", "xlsx", "odp", "ods", "key"])
def test_material_rejects_office_filenames(extension):
    assert lesson_log.material_problems({"materials": [f"Munkalap.{extension} (feladatlap)"]})


def test_material_rejects_date_slug_but_accepts_public_title():
    assert lesson_log.material_problems({"materials": [
        "2026-10-03-A-polisz-szuletese-1-resz (prezentáció)"]})
    assert not lesson_log.material_problems({"materials": ["A polisz születése (prezentáció)"]})


@pytest.mark.parametrize("prefix", ["./", "../proba/"])
def test_lesson_form_resolves_paths_and_groups_nested_points(repo, prefix):
    meta = frontmatter.split((repo / NOTE).read_text()).meta
    body = LESSON_BODY.replace("elso.md#", prefix + "elso.md#")
    body = body.replace("* [", " * [")
    body += "\n   - Alpont link nélkül.\n" * 9
    assert not lesson_log.form_problems(repo, NOTE, body, meta)
    for lesson in meta["lessons"]:
        lesson["topics"] = [prefix + t for t in lesson["topics"]]
    assert not lesson_log.form_problems(repo, NOTE, LESSON_BODY, meta)


def test_numbered_learning_points_explain_required_bullets(repo):
    meta = frontmatter.split((repo / NOTE).read_text()).meta
    errors = lesson_log.form_problems(repo, NOTE, LESSON_BODY.replace("* ", "1. "), meta)
    assert any("top-level `*`/`-` bullets" in error for error in errors)


def test_question_sections_and_nested_lists_are_independent():
    body = QUESTIONS + "  - Első lehetőség.\n  - Második lehetőség.\n"
    body += "\n## Háttér\nMagyarázat.\n<!-- q: next -->\n2. Következő?\n"
    body += "\n# Másik rész\n1. Nem kérdés.\n"
    assert not decisions.question_problems(body, {})
    assert decisions.question_problems(body + "\n# Open questions\n", {})


@pytest.mark.parametrize("consumer", ["overview", "lesson_keys", "warnings", "indexes"])
def test_whole_wiki_readers_report_yaml_error_with_page(repo, consumer):
    from school_notes2.wiki import drafts, generate
    from school_notes2.wiki.pages import PageError
    write(repo, REL, "---\nprivate: [PRIVATE_VALUE\n---\n")
    readers = {"overview": decisions.overview, "lesson_keys": drafts.lesson_keys,
               "warnings": lambda r: drafts.warnings(r, date(2026, 10, 4)),
               "indexes": generate.write_indexes}
    with pytest.raises(PageError) as failure:
        readers[consumer](repo)
    assert failure.value.page == REL
    assert "PRIVATE_VALUE" not in str(failure.value)
