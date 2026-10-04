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
    # Even at the escalation threshold a reference closure does not stay open.
    for n in range(4):
        files.apply_closure(tmp_path, f"earlier-{n}", [], listed)
    assert files.open_counts(path.read_text()) == {"R1": 4}
    outcome = files.apply_closure(tmp_path, "run", [closure], listed)
    before = path.read_bytes()
    files.apply_closure(tmp_path, "run", [closure], listed)
    assert path.read_bytes() == before
    assert frontmatter.split(path.read_text()).meta["items"]["R1"] == status
    assert key in path.read_text()
    assert not outcome.new_owner
    assert files.open_counts(path.read_text()) == {"R1": 4}
    assert not files.open_items(tmp_path, "cron")
    own_section = path.read_text().split("## Végrehajtva (run)")[1]
    assert "nem érintett" not in own_section
    assert files.WORDS[status] in own_section and key in own_section
    for n in range(6):
        outcome = files.apply_closure(tmp_path, f"later-{n}", [], files.open_items(tmp_path, "cron"))
        assert not outcome.new_owner
    assert path.read_bytes() == before


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
        assert files.open_items(tmp_path, "cron") == [{"file": rel, "item_id": "R1", "key": key, "round": 2, "status": "open"}]
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


@pytest.mark.parametrize("status", ["disagree", "fixed", "settled"])
@pytest.mark.parametrize("chain", [0, 1])
def test_related_dispute_never_reborn_and_chain_is_tool_owned(tmp_path, report, status, chain):
    path, rel = report
    record = {**relations.details(path.read_text(), "R1"), "chain": chain}
    path.write_text(frontmatter.set_keys(path.read_text(), {"items": {"R1": status}, "item_details": {"R1": record}}))
    finding = {"id": "R1", "file": PAGE, "problem": "Ismételt.", "relates_to": f"{rel}#R1"}
    new = files.write_review(tmp_path, "2026-10-05", {"verdict": "changes", "findings": [finding]}, "r", "b", "c")
    meta = frontmatter.split(new.read_text()).meta
    if status == "disagree":
        assert meta["items"] == {} and "## Függő" in new.read_text()
    else:
        assert meta["items"] == {"R1": "owner"}
        assert meta["item_details"]["R1"]["chain"] == 1
        assert meta["item_details"]["R1"]["origin"] == "nightly"
    for key, value in [("origin", "reader"), ("chain", 0), ("unlocated", True)]:
        with pytest.raises(SchemaError):
            validate("review", {"verdict": "changes", "findings": [{**finding, key: value}]})


def test_asset_round_two_question_on_embedding_page(tmp_path, report):
    path, rel = report
    record = {"file": "wiki/assets/a.svg", "round": 2}
    path.write_text(frontmatter.set_keys(path.read_text(), {"item_details": {"R1": record}}))
    page = tmp_path / PAGE
    page.write_text(page.read_text() + '\n![Ábra](../assets/a.svg)\n')
    closure = {"file": rel, "item_id": "R1", "status": "question", "question_id": "tema-datum"}
    assert not relations.closure_problems(tmp_path, closure)
    files.apply_closure(tmp_path, "second", [closure], [])
    assert frontmatter.split(path.read_text()).meta["items"]["R1"] == "question"
    page.write_text(QUESTION + '\n```md\n![Ábra](../assets/a.svg)\n```\n')
    assert relations.closure_problems(tmp_path, closure)


def test_reviewer_inventory_is_grouped_filtered_and_deterministic(tmp_path, report):
    path, rel = report
    states = ["open", "owner", "disagree", "fixed", "settled", "question"]
    items = {f"R{n}": s for n, s in enumerate(states, 1)}
    records = {key: {"file": PAGE, "round": 1} for key in items}
    path.write_text(frontmatter.set_keys(path.read_text(), {"items": items, "item_details": records}))
    actual = relations.reviewer_inventory(tmp_path)
    page = actual["pages"][PAGE]
    assert page["questions"] == ["tema-datum"] and page["decisions"] == ["tema-nev"]
    assert list(page["items"]) == [f"{rel}#R{n}" for n in (1, 2, 3)]
    assert "items" not in actual
    path.write_text(frontmatter.set_keys(path.read_text(), {"items": dict(reversed(list(items.items())))}))
    assert relations.reviewer_inventory(tmp_path) == actual


@pytest.mark.parametrize("target", [PAGE, "wiki/assets/a.svg"])
def test_missing_decision_evidence_is_invalid_output_not_unlocated(tmp_path, report, target):
    from school_notes2.review import nightly
    from school_notes2.state import phase
    from school_notes2.state.errors import BadWork
    task = phase.create(tmp_path / "tasks", "tester", "review", "cron", "reviewing")
    page = tmp_path / PAGE
    page.write_text(page.read_text() + '\n![Ábra](../assets/a.svg)\n')
    finding = {"id": "R1", "file": target, "problem": "Más adat.", "relates_to": "tema-nev"}
    with pytest.raises(BadWork, match="requires new_evidence"):
        nightly.record_review(task, {"verdict": "changes", "findings": [finding]}, tmp_path)
    assert task.phase == "reviewing" and not (task.dir / "review.json").exists()
    nightly.record_review(task, {"verdict": "changes", "findings": [{**finding, "new_evidence": "Új bizonyíték."}]}, tmp_path)
    assert task.phase == "reviewed"


@pytest.mark.parametrize("embedded", [True, False])
def test_asset_routes_using_embedding_page_questions_and_decisions(tmp_path, report, embedded):
    from school_notes2.review import nightly
    from school_notes2.state import phase
    page = tmp_path / PAGE
    image = '\n![Ábra](../assets/a.svg)\n'
    page.write_text(page.read_text() + (image if embedded else '\n```md\n' + image + '```\n'))
    other = tmp_path / "wiki/proba/masik.md"
    other.write_text(QUESTION.replace("tema-datum", "masik-datum") + image)
    asset = "wiki/assets/a.svg"
    known = relations.inventory(tmp_path)["pages"][asset]
    q, d = relations.related_ids(tmp_path, asset)
    assert known == {"questions": sorted(q), "decisions": sorted(d)}
    assert known["questions"] == (["masik-datum", "tema-datum"] if embedded else ["masik-datum"])
    assert relations.reviewer_inventory(tmp_path)["pages"][asset] == {**known, "items": {}}
    review = {"verdict": "changes", "findings": [
        {"id": "R1", "file": asset, "problem": "Kérdés.", "relates_to": "tema-datum"},
        {"id": "R2", "file": asset, "problem": "Döntés.", "relates_to": "tema-nev", "new_evidence": "Új adat."}]}
    task = phase.create(tmp_path / "tasks", "tester", "review", "cron", "reviewing")
    nightly.record_review(task, review, tmp_path)
    path = files.write_review(tmp_path, "2026-10-05", nightly.load_review(task), "r", "b", "c")
    meta = frontmatter.split(path.read_text()).meta
    assert meta["items"] == ({"R2": "owner"} if embedded else {"R1": "open", "R2": "open"})
    assert meta["item_details"]["R2"]["unlocated"] is not embedded
    assert ("## Függő" in path.read_text()) is embedded
    assert ("### R1" not in path.read_text()) is embedded
    if embedded:
        assert not any(i["file"] == path.relative_to(tmp_path).as_posix()
                       for i in files.open_items(tmp_path, "cron"))


def test_duplicate_responses_drop_both_without_choosing_a_verdict(tmp_path, report):
    path, rel = report
    files.apply_closure(tmp_path, "writer", [{"file": rel, "item_id": "R1", "status": "disagree", "note": "Indok."}], [])
    responses = [{"key": f"{rel}#R1", "verdict": verdict, "answer": "Indok."} for verdict in ("keep", "accept")]
    kept, dropped = relations.valid_responses(responses, relations.inventory(tmp_path))
    assert not kept and len(dropped) == 2
    assert all(i["reason"] == "duplicate response key" for i in dropped)
    assert relations.valid_responses(list(reversed(responses)), relations.inventory(tmp_path)) == (kept, dropped)
