import pytest

from school_notes2.review import files, relations
from school_notes2.schemas import SchemaError, validate
from school_notes2.wiki import frontmatter
from school_notes2.wiki.check_result import check_result

PAGE = "wiki/proba/tema.md"
QUESTION = "# Nyitott kérdések\n\n<!-- q: tema-datum -->\n1. Melyik nap volt? Addig a fogalmakat tanuld.\n"


@pytest.fixture
def report(tmp_path):
    page = tmp_path / PAGE
    page.parent.mkdir(parents=True)
    page.write_text(frontmatter.set_keys(QUESTION, {"decisions": [
        {"id": "tema-nev", "claim": "Név", "answer": "Válasz", "by": "owner", "on": "2026-10-04"}]}))
    path = files.write_review(tmp_path, "2026-10-04", {"verdict": "changes", "findings": [
        {"id": "R1", "file": PAGE, "problem": "Hiány."}]}, "reviewer", "a", "b")
    return path, path.relative_to(tmp_path).as_posix()


@pytest.mark.parametrize("status,field,key", [("question", "question_id", "tema-datum"),
    ("settled", "question_id", "tema-datum"), ("settled", "decision_id", "tema-nev")])
def test_reference_closure_and_same_run_resume(tmp_path, report, status, field, key):
    path, rel = report
    listed = files.open_items(tmp_path, "cron")
    closure = {"file": rel, "item_id": "R1", "status": status, field: key}
    assert not relations.closure_problems(tmp_path, closure)
    files.apply_closure(tmp_path, "run", [closure], listed)
    before = path.read_bytes()
    files.apply_closure(tmp_path, "run", [closure], listed)
    assert path.read_bytes() == before
    assert frontmatter.split(path.read_text()).meta["items"]["R1"] == status
    assert key in path.read_text()


@pytest.mark.parametrize("closure", [
    {"status": "disagree"}, {"status": "disagree", "note": " \n "},
    {"status": "question", "question_id": "unknown"},
    {"status": "question", "question_id": "tema-nev"},
    {"status": "settled", "decision_id": "unknown"},
])
def test_invalid_closures_report_check_errors(tmp_path, report, closure):
    _, rel = report
    result = {"status": "done", "review_closure": [{"file": rel, "item_id": "R1", **closure}]}
    assert check_result(tmp_path, result, {"packages": [], "pages": []}, {(rel, "R1")})


def test_question_on_another_page_or_in_code_does_not_close(tmp_path, report):
    _, rel = report
    (tmp_path / PAGE).write_text("```md\n" + QUESTION + "```\n")
    (tmp_path / "wiki/proba/masik.md").write_text(QUESTION)
    assert relations.closure_problems(tmp_path, {"file": rel, "item_id": "R1", "status": "question",
                                                 "question_id": "tema-datum"})


@pytest.mark.parametrize("verdict", ["accept", "keep"])
def test_disagreement_reply_exactly_once_and_resume(tmp_path, report, verdict):
    path, rel = report
    files.apply_closure(tmp_path, "first", [{"file": rel, "item_id": "R1", "status": "disagree", "note": "Indok."}], [])
    key = f"{rel}#R1"
    relations.reply(tmp_path, key, verdict, "Szakmai válasz.")
    before = path.read_bytes()
    relations.reply(tmp_path, key, verdict, "Szakmai válasz.")
    assert path.read_bytes() == before
    meta = frontmatter.split(path.read_text()).meta
    assert meta["items"]["R1"] == ("open" if verdict == "keep" else "disagree")
    with pytest.raises(files.ClosureError):
        relations.reply(tmp_path, key, verdict, "Második válasz.")
    if verdict == "keep":
        assert files.open_items(tmp_path, "cron") == [{"file": rel, "item_id": "R1", "key": key, "round": 2}]
        for status in ("disagree", "settled"):
            assert relations.closure_problems(tmp_path, {"file": rel, "item_id": "R1", "status": status,
                                                       "note": "Indok.", "question_id": "tema-datum"})
        files.apply_closure(tmp_path, "second", [{"file": rel, "item_id": "R1", "status": "question",
                                               "question_id": "tema-datum"}], [])
        assert frontmatter.split(path.read_text()).meta["items"]["R1"] == "question"


def test_full_key_routes_to_correct_report_and_unknown_is_unlocated(tmp_path, report):
    _, rel = report
    review = {"verdict": "changes", "findings": [
        {"id": "R1", "file": PAGE, "problem": "Ugyanaz.", "relates_to": f"{rel}#R1"},
        {"id": "R2", "file": PAGE, "problem": "Kérdés.", "relates_to": "tema-datum"},
        {"id": "R3", "file": PAGE, "problem": "Döntés.", "relates_to": "tema-nev", "new_evidence": "Új adat."},
        {"id": "R4", "file": PAGE, "problem": "Ismeretlen.", "relates_to": "docs/review/missing.md#R1"},
    ]}
    validate("review", review)
    path = files.write_review(tmp_path, "2026-10-05", review, "r", "b", "c")
    meta = frontmatter.split(path.read_text()).meta
    assert meta["items"] == {"R3": "owner", "R4": "open"}
    assert meta["item_details"]["R4"]["unlocated"]
    assert "## Függő (nyitott kérdésre vár)" in path.read_text()
    assert "### R1" not in path.read_text()
    assert f"{rel}#R1" in relations.inventory(tmp_path)["items"]
    with pytest.raises(SchemaError):
        validate("review", {"verdict": "changes", "findings": [
            {"id": "R1", "file": PAGE, "problem": "P", "relates_to": "R1"}]})


@pytest.mark.parametrize("note", [None, "", " \n "])
def test_disagree_schema_requires_substantive_note(note):
    c = {"file": "docs/review/a.md", "item_id": "R1", "status": "disagree"}
    if note is not None:
        c["note"] = note
    with pytest.raises(SchemaError):
        validate("result", {"status": "done", "review_closure": [c]})


@pytest.mark.parametrize("when", ["before", "after"])
def test_reply_crash_resume(tmp_path, report, monkeypatch, when):
    from school_notes2.state import safefs
    path, rel = report
    files.apply_closure(tmp_path, "run", [{"file": rel, "item_id": "R1", "status": "disagree", "note": "Indok."}], [])
    real_write = safefs.write_text
    def interrupted(*args, **kwargs):
        if when == "after":
            real_write(*args, **kwargs)
        raise RuntimeError("power loss")
    with monkeypatch.context() as m:
        m.setattr(safefs, "write_text", interrupted)
        with pytest.raises(RuntimeError):
            relations.reply(tmp_path, f"{rel}#R1", "keep", "Indokolt válasz.")
    relations.reply(tmp_path, f"{rel}#R1", "keep", "Indokolt válasz.")
    assert relations.details(path.read_text(), "R1")["round"] == 2
    assert path.read_text().count("## Válasz (R1)") == 1


def test_new_review_requires_relates_to_and_no_direct_family_questions():
    with pytest.raises(SchemaError):
        validate("review", {"verdict": "changes", "findings": [
            {"id": "R1", "file": PAGE, "problem": "Hiány."}]})
    with pytest.raises(SchemaError):
        validate("review", {"verdict": "ok", "findings": [], "family_questions": []})


def test_saved_legacy_review_is_still_resumable(tmp_path):
    from school_notes2.review import nightly
    from school_notes2.state import phase
    from school_notes2.state.files import write_json
    task = phase.create(tmp_path, "tester", "review", "cron", "reviewed")
    write_json(task.dir / "review.json", {"verdict": "changes", "findings": [
        {"id": "R1", "file": PAGE, "problem": "Régi tétel."}], "family_questions": ["Régi kérdés."]})
    saved = nightly.load_review(task)
    assert saved["findings"][0]["relates_to"] is None
    assert saved["family_questions"] == ["Régi kérdés."]
