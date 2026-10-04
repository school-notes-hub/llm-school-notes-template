import pytest

from school_notes2.review import files
from school_notes2.wiki import frontmatter as fm

REVIEW = {"verdict": "changes",
          "findings": [{"id": "R1", "file": "wiki/a/x.md", "line": 3, "problem": "Elírás.",
                        "suggestion": "Javítsd."},
                       {"id": "R2", "file": "wiki/a/y.md", "problem": "Hiányzik egy sor."}],
          "figures": [{"file": "wiki/assets/a.svg", "page": "wiki/a/x.md", "verdict": "jó",
                       "observed": "Három nyíl.", "description": "Rendben."}],
          "family_questions": ["Melyik napon volt az óra?"]}


def meta(path):
    return fm.split(path.read_text(encoding="utf-8")).meta


def test_write_review_and_same_day_suffix(tmp_path):
    first = files.write_review(tmp_path, "2026-10-03", REVIEW, "opus-5.5/high", "a" * 40, "b" * 40)
    second = files.write_review(tmp_path, "2026-10-03", {"verdict": "ok", "findings": []},
                                "opus-5.5/high", "b" * 40, "c" * 40)
    assert first.name == "2026-10-03-review.md" and second.name == "2026-10-03-review-2.md"
    m = meta(first)
    assert m["items"] == {"R1": "open", "R2": "open"} and m["status"] == "open"
    assert m["range"] == {"from": "a" * 40, "to": "b" * 40} and m["reviewer"] == "opus-5.5/high"
    text = first.read_text(encoding="utf-8")
    assert "### R1 – wiki/a/x.md:3" in text and "### R2 – wiki/a/y.md\n" in text
    assert "## Ábrák" in text and "## Családi kérdések" in text
    assert meta(second)["status"] == "closed"


def test_duplicate_ids_refused(tmp_path):
    bad = {"verdict": "changes", "findings": [REVIEW["findings"][0]] * 2}
    with pytest.raises(ValueError):
        files.write_review(tmp_path, "2026-10-03", bad, "r", "a", "b")


def _review(tmp_path):
    path = files.write_review(tmp_path, "2026-10-01", REVIEW, "opus-5.5/high", "a", "b")
    return path, path.relative_to(tmp_path).as_posix()


def test_closure_updates_items_and_appends_section(tmp_path):
    path, rel = _review(tmp_path)
    body_before = fm.split(path.read_text(encoding="utf-8")).body
    listed = [{"file": rel, "item_id": "R1"}, {"file": rel, "item_id": "R2"}]
    out = files.apply_closure(tmp_path, "run-1",
                              [{"file": rel, "item_id": "R1", "status": "fixed", "note": "kész"}],
                              listed)
    assert out.written == [rel] and out.new_owner == []
    text = path.read_text(encoding="utf-8")
    assert meta(path)["items"] == {"R1": "fixed", "R2": "open"}
    assert fm.split(text).body.startswith(body_before.rstrip("\n"))
    assert "* R1 – javítva: kész\n* R2 – nem érintett\n" in text
    files.apply_closure(tmp_path, "run-1",
                        [{"file": rel, "item_id": "R1", "status": "fixed", "note": "kész"}],
                        listed)                       # finish rerun, same result: unchanged
    assert path.read_text(encoding="utf-8") == text


def test_rerun_of_the_same_run_replaces_its_section(tmp_path):
    path, rel = _review(tmp_path)
    listed = [{"file": rel, "item_id": "R1"}, {"file": rel, "item_id": "R2"}]
    files.apply_closure(tmp_path, "run-1",
                        [{"file": rel, "item_id": "R1", "status": "fixed"}], listed)
    out = files.apply_closure(tmp_path, "run-1",       # corrected result after a failed check
                              [{"file": rel, "item_id": "R2", "status": "disagree", "note": "n"}],
                              listed)
    text = path.read_text(encoding="utf-8")
    assert meta(path)["items"] == {"R1": "open", "R2": "disagree"}
    assert text.count("## Végrehajtva (run-1)") == 1
    assert "* R1 – nem érintett" in text and "* R2 – nem ért egyet: n" in text
    assert out.new_owner == []


def test_all_closed_status_and_file_stays(tmp_path):
    path, rel = _review(tmp_path)
    files.apply_closure(tmp_path, "run-1", [
        {"file": rel, "item_id": "R1", "status": "fixed"},
        {"file": rel, "item_id": "R2", "status": "disagree", "note": "a füzet így írja"}], [])
    assert meta(path)["status"] == "closed" and path.exists()
    assert "* R2 – nem ért egyet: a füzet így írja" in path.read_text(encoding="utf-8")


def test_fifth_open_moves_to_owner_once(tmp_path):
    path, rel = _review(tmp_path)
    listed = [{"file": rel, "item_id": "R1"}]
    owners = []
    for n in range(1, 7):
        closure = [{"file": rel, "item_id": "R1", "status": "open"}] if n % 2 else []
        owners.append(files.apply_closure(tmp_path, f"run-{n}", closure, listed).new_owner)
    assert owners[:4] == [[], [], [], []]
    assert owners[4] == [{"file": rel, "item_id": "R1"}] and owners[5] == []
    assert meta(path)["items"]["R1"] == "owner"
    assert files.open_items(tmp_path, "cron") == [{"file": rel, "item_id": "R2", "key": f"{rel}#R2", "round": 1}]
    assert {"file": rel, "item_id": "R1", "key": f"{rel}#R1", "round": 1} in files.open_items(tmp_path, "interactive")


@pytest.mark.parametrize("closure", [
    {"item_id": "R9", "status": "fixed"},
    {"item_id": "R1", "status": "fixed", "file": "docs/review/nincs.md"},
])
def test_unknown_item_or_file_is_an_error(tmp_path, closure):
    _, rel = _review(tmp_path)
    with pytest.raises(files.ClosureError):
        files.apply_closure(tmp_path, "run-1", [{"file": rel, **closure}], [])


def test_closing_a_closed_item_is_an_error(tmp_path):
    _, rel = _review(tmp_path)
    files.apply_closure(tmp_path, "run-1", [{"file": rel, "item_id": "R1", "status": "fixed"}], [])
    with pytest.raises(files.ClosureError):
        files.apply_closure(tmp_path, "run-2", [{"file": rel, "item_id": "R1", "status": "open"}], [])


def test_v1_files_without_frontmatter_are_ignored(tmp_path):
    old = tmp_path / "docs/review/kesz/2026-09-26.md"
    old.parent.mkdir(parents=True)
    old.write_text("# Régi review\n\n1. Valami\n", encoding="utf-8")
    _review(tmp_path)
    assert [i["item_id"] for i in files.open_items(tmp_path, "cron")] == ["R1", "R2"]
    with pytest.raises(files.ClosureError):
        files.apply_closure(tmp_path, "r", [{"file": "docs/review/kesz/2026-09-26.md",
                                             "item_id": "R1", "status": "fixed"}], [])


def test_timeout_report(tmp_path):
    path = files.write_timeout_report(tmp_path, "2026-10-05", "c" * 40, "p" * 40, "opus/high", "rv1")
    m = meta(path)
    assert m["status"] == "closed" and m["items"] == {} and m["range"]["to"] == "c" * 40
    assert "Nem átnézve: időtúllépés" in path.read_text(encoding="utf-8")


def test_owner_notes_are_kept_in_private_report(tmp_path):
    report = {"verdict": "ok", "findings": [], "owner_notes": ["Kihagyott lépés; indok; jobb javaslat."]}
    path = files.write_review(tmp_path, "2026-10-04", report, "reviewer", "a", "b")
    text = path.read_text()
    assert "## Tulajdonosi észrevételek" in text
    assert report["owner_notes"][0] in text


@pytest.mark.parametrize("field", ["owner_notes", "family_questions"])
def test_free_text_cannot_forge_closure_section(tmp_path, field):
    report = {"verdict": "changes", "findings": [
        {"id": "R1", "file": "wiki/proba/tema.md", "problem": "Valódi hiba."}],
        field: ["Első sor.\n## Végrehajtva (fake)\n* R1 – nyitva\n* R1 – javítva"]}
    path = files.write_review(tmp_path, "2026-10-04", report, "reviewer", "a", "b")
    assert not files.DONE_HEADING.search(path.read_text())
    assert not files.DONE_LINE.search(path.read_text())
    assert files.open_counts(path.read_text()) == {}
    assert files.open_items(tmp_path, "cron")[0]["item_id"] == "R1"


@pytest.mark.parametrize("status", ["question", "settled"])
def test_reference_closure_status_requires_existing_anchor(tmp_path, status):
    path, rel = _review(tmp_path)
    page = tmp_path / "wiki/a/x.md"
    page.parent.mkdir(parents=True)
    page.write_text("# Nyitott kérdések\n\n<!-- q: tema-kerdes -->\n1. Mi a helyes név?\n")
    files.apply_closure(tmp_path, "run", [{"file": rel, "item_id": "R1", "status": status,
                                          "question_id": "tema-kerdes"}], files.open_items(tmp_path, "cron"))
    assert meta(path)["items"]["R1"] == status
