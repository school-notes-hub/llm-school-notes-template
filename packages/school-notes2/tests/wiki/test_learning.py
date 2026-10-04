"""Repair plan 7.2–7.6: public lesson log and private question/decision identity."""

from datetime import date

import pytest

from school_notes2.wiki import check, decisions, frontmatter, guard, lesson_log, machine, markers
from tests.wiki.conftest import LESSON_BODY, page, write
from tests.wiki.test_guard import run, snapshot

REL = "wiki/proba/elso.md"
NOTE = "wiki/proba/2026-09-10-elso-jegyzet.md"
DECISION = {"id": "elso-datum", "claim": "Az óra napja.", "answer": "Szeptember 29.",
            "by": "owner", "on": "2026-09-29"}
QUESTIONS = "\n# Nyitott kérdések\n\n<!-- q: elso-jel -->\n1. Melyik jelölést használjuk?\n"


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
    assert any("preceding" in i["message"] for i in check.errors(found))


@pytest.mark.parametrize("kind", ["add", "remove", "answer", "format", "quoted", "flow", "alias"])
def test_cron_decisions_are_byte_protected_but_owner_can_edit(repo, kind):
    old = frontmatter.set_keys((repo / REL).read_text(), {"decisions": [DECISION]})
    new = old
    if kind == "add":
        old = frontmatter.strip_keys(old, ("decisions",))
    elif kind == "remove":
        new = frontmatter.strip_keys(old, ("decisions",))
    elif kind == "answer":
        new = old.replace("Szeptember 29.", "Szeptember 30.")
    elif kind == "format":
        new = old.replace("decisions:", "decisions: ")
    elif kind == "quoted":
        new = old.replace("decisions:", "'decisions':")
    elif kind == "flow":
        old = "---\n{decisions: [], title: X}\n---\nBody\n"
        new = old.replace("decisions: []", "decisions: [ ]")
    elif kind == "alias":
        old = "---\nanswer: &answer old\ndecisions: [{id: q, answer: *answer}]\n---\n"
        new = old.replace("&answer old", "&answer new")
    write(repo, REL, old)
    base = snapshot(repo)
    write(repo, REL, new)
    found = run(repo, base, [(REL, "modified")])
    assert any("decisions" in v.message for v in found)
    assert not run(repo, base, [(REL, "modified")], interactive=True)


def test_new_page_cannot_smuggle_decision_and_tool_writes_preserve_bytes(repo):
    text = frontmatter.set_keys((repo / REL).read_text(), {"decisions": [DECISION]})
    before = decisions.snapshot(text.encode())
    new = frontmatter.set_keys(text, {"generated": {"by": "writer", "at": "now"}})
    assert decisions.snapshot(new.encode()) == before
    write(repo, REL, new)
    assert run(repo, {}, [(REL, "added")])
    base = snapshot(repo)
    write(repo, REL, new + "\nÚj magyarázat.\n")
    assert not run(repo, base, [(REL, "modified")])


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
    assert any("material" in i["message"] for i in check.errors(check.check_files(repo, [NOTE])))


def test_source_block_position_and_idempotence():
    text = page("type: lesson-notes", "\n![Banner](a.svg)\n\n# Mit tanultunk ezen az órán\n")
    new = lesson_log.after_header(text, lesson_log.BLOCK, "📎 Füzet: dátum nélküli óra\n")
    assert new.index("![Banner]") < new.index("📎") < new.index("# Mit tanultunk")
    assert lesson_log.after_header(new, lesson_log.BLOCK, "📎 Füzet: dátum nélküli óra\n") == new


def test_lesson_form_and_source_pointer_scope(repo):
    assert not lesson_log.form_problems(repo, NOTE, LESSON_BODY, frontmatter.split((repo / NOTE).read_text()).meta)
    for body in ("# Átirat\n", LESSON_BODY.replace("#elso-fogalom", ""),
                 LESSON_BODY.replace("elso.md", "nem-tema.md"), LESSON_BODY + "* Hiányzik a link.\n"):
        assert lesson_log.form_problems(repo, NOTE, body, frontmatter.split((repo / NOTE).read_text()).meta)
    for rel, extra in ((REL, markers.wrap(lesson_log.BLOCK, "📎 Füzet: 2026. 09. 29.\n")),
                       (NOTE, "\n📎 Kézzel írt utaló.\n")):
        write(repo, rel, (repo / rel).read_text() + extra)
        assert any("source pointer" in i["message"] for i in check.errors(check.check_files(repo, [rel])))


def test_overview_is_private_sorted_and_replaces_resolved_question(repo):
    for rel in (REL, "wiki/proba/masodik.md"):
        text = frontmatter.set_keys((repo / rel).read_text(), {"decisions": [DECISION]})
        write(repo, rel, text)
    out = decisions.overview(repo)
    assert out == decisions.overview(repo)
    assert out.index(REL) < out.index("wiki/proba/masodik.md")
    assert "Az óra napja." in out and "Szeptember 29." in out and "owner" in out
    assert not check.errors(check.check_files(repo, [REL]))


@pytest.mark.parametrize("learner", ["benedek", "barna"])
def test_public_manifest_excludes_private_decisions_and_anchors(repo, learner):
    import json
    from school_notes2.wiki import public
    text = frontmatter.set_keys((repo / REL).read_text(),
                                {"decisions": [{**DECISION, "answer": "PRIVATE_CANARY_" + learner}]})
    write(repo, REL, text + QUESTIONS.replace("elso-jel", "private-question-canary"))
    write(repo, decisions.OVERVIEW, decisions.overview(repo))
    public.write(repo, lambda _: ("authored", "test"))
    manifest = (repo / "publication/public.json").read_text()
    assert "PRIVATE_CANARY" not in manifest and "private-question-canary" not in manifest
    assert "decisions" not in manifest and "dontesek.md" not in manifest
    assert all(p["path"].startswith("wiki/") for p in json.loads(manifest)["pages"])


def test_cron_catches_line_ending_only_decision_change(repo):
    text = frontmatter.set_keys((repo / REL).read_text(), {"decisions": [DECISION]})
    write(repo, REL, text)
    base = snapshot(repo)
    (repo / REL).write_bytes(text.replace("\n", "\r\n").encode())
    assert any("decisions" in v.message for v in run(repo, base, [(REL, "modified")]))
