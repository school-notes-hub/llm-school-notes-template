"""Fixed warning corpus: public surfaces, structural exceptions and content identity."""

from pathlib import Path

import pytest

from school_notes2.review import warnings
from school_notes2.wiki import source_refs as refs

PAGE = "wiki/proba/tema.md"
CORPUS = [
    (PAGE, "A 9. dia felirata.", True),
    (PAGE, "# 1-3. dia: az átmeneti korszak", True),
    (PAGE, "A **9. dia** példája.", True),
    (PAGE, "A 3. fotón látható.", True),
    (PAGE, "Az 5. oldalon olvasható.", True),
    (PAGE, "A diák megértik a témát.", False),
    (PAGE, "A fenti fotón látható a beágyazott kép.", False),
    (PAGE, "![A 3. fotó](../assets/kep.png)", True),
    (PAGE, "<details>\n<summary>Kérdés</summary>\nA 2. dia.\n</details>", True),
    (PAGE, "<footer>A 2. dia.</footer>", True),
    (PAGE, '```mermaid\nflowchart TD\nA["A 2. dia"] --> B\n```', True),
    (PAGE, "```python\n# A 2. dia\n```", False),
    (PAGE, "~~~text\nA 2. dia\n~~~", False),
    (PAGE, "<!-- A 2. dia -->\nTananyag.", False),
    (PAGE, "[^hely]: A 2. dia.\n\n    Folytatás: 3. fotó.\n\nTananyag.", False),
    (PAGE, "🔖 Tankönyv: A város, 5. oldal.", False),
    (PAGE, "# Nyitott kérdések\n\n1. Mi a 2. dia dátuma?", False),
    (PAGE, "# Nyitott kérdések\n\n1. Mi a dátum?\n\n# Tananyag\nA 2. dia.", True),
    (PAGE, "<!-- school-notes:generated lesson-sources -->\n📎 A 2. dia\n<!-- /school-notes:generated -->", False),
    ("wiki/log.md", "A 2. dia.", False),
    (PAGE, '---\ntitle: "A 2. dia"\ndescription: Téma\n---\nTartalom.', True),
    (PAGE, '---\ntitle: Téma\n"description": >\n  A 2. dia.\n---\nTartalom.', True),
    (PAGE, '---\ntitle: Téma\nsource: A 2. dia\n---\nTartalom.', False),
    ("wiki/assets/a.svg", '<svg><text>A 2. <tspan>dia</tspan></text></svg>', True),
    ("wiki/assets/a.svg", '<svg><title>A 2. dia</title><desc>3. fotó</desc></svg>', True),
    ("wiki/assets/a.svg", '<svg><!-- 2. dia --><path id="3. fotó"/></svg>', False),
]


@pytest.mark.parametrize("file,text,hit", CORPUS)
def test_corpus(file, text, hit):
    found = refs.scan(file, text)
    assert bool(found) == hit
    assert all(i["severity"] == "warning" for i in found)


def test_changed_lines_repair_and_identical_occurrences():
    old = "A 2. dia.\nTananyag.\n"
    new = "A 2. dia.\nÚj tananyag.\nA 2. dia.\n"
    found = refs.scan(PAGE, new, old)
    assert len(found) == 1 and found[0]["line"] == 3 and found[0]["occurrence"] == 2
    assert len(refs.scan(PAGE, new, old, full=True)) == 2
    shifted = refs.scan(PAGE, "Bevezetés.\n" + new, full=True)
    assert found[0]["id"] == shifted[1]["id"]
    assert refs.line_hash(" A  2. dia. ") == refs.line_hash("A 2. dia.")


def test_verdicts_persist_by_content_not_line_number(tmp_path):
    found = refs.scan(PAGE, "A 2. dia.\nA 2. dia.")
    verdicts = [{"id": i["id"], "verdict": "téves", "reason": "Tárgyi példa."} for i in found]
    assert warnings.record(tmp_path, found, verdicts) == []
    before = (tmp_path / warnings.PATH).read_bytes()
    warnings.record(tmp_path, list(reversed(found)), list(reversed(verdicts)))
    assert (tmp_path / warnings.PATH).read_bytes() == before
    assert warnings.pending(tmp_path, refs.scan(PAGE, "Bevezetés\nA 2. dia.\nA 2. dia.")) == []
    assert len(warnings.pending(tmp_path, refs.scan(PAGE, "A 3. dia.\nA 2. dia."))) == 1
    assert warnings.record(tmp_path, found[:1], [{**verdicts[0], "verdict": "hiba"}])[0]["id"] == found[0]["id"]
    assert warnings.pending(tmp_path, found) == found[:1]
    assert warnings.pending(tmp_path, found, [found[0]["id"]]) == []
    with pytest.raises(ValueError):
        warnings.record(tmp_path, found, verdicts[:1])


@pytest.mark.parametrize("learner", ["benedek", "barna"])
def test_corpus_and_read_only_scan_on_both_local_wikis(learner):
    repo = Path(__file__).resolve().parents[5] / f"school-notes-{learner}-active"
    if not repo.is_dir():
        pytest.skip("optional local learner checkout is unavailable")
    found = []
    for path in sorted((repo / "wiki").rglob("*")):
        if path.suffix not in (".md", ".svg"):
            continue
        text = path.read_text()
        rel = path.relative_to(repo).as_posix()
        hits = refs.scan(rel, text, full=True)
        assert hits == refs.scan(rel, text, full=True)
        assert not refs.scan(rel, text, text)
        found.extend(hits)
    assert all(i["severity"] == "warning" for i in found)
    if learner == "benedek":
        assert any("polisz" in i["file"] and "9. dia" in i["message"] for i in found)
    # Exactly the same fixed corpus applies to both learners.
    for file, text, hit in CORPUS:
        assert bool(refs.scan(file, text)) == hit


@pytest.mark.parametrize("when", ["before", "after"])
def test_verdict_atomic_write_crash_resume(tmp_path, monkeypatch, when):
    from school_notes2.state import safefs
    assigned = refs.scan(PAGE, "A 2. dia.")
    verdicts = [{"id": assigned[0]["id"], "verdict": "megengedett", "reason": "Példa."}]
    real_write = safefs.write_json
    def interrupted(*args, **kwargs):
        if when == "after":
            real_write(*args, **kwargs)
        raise RuntimeError("power loss")
    with monkeypatch.context() as m:
        m.setattr(safefs, "write_json", interrupted)
        with pytest.raises(RuntimeError):
            warnings.record(tmp_path, assigned, verdicts)
    warnings.record(tmp_path, assigned, verdicts)
    stored = warnings.load(tmp_path)
    assert len(stored) == 1 and not warnings.pending(tmp_path, assigned)


@pytest.mark.parametrize("text,hit", [
    ('<img src="a.svg" alt="A 2. dia">', True),
    ("    A 2. dia.\n", False),
    ("* Példa:\n\n    A 2. dia.\n", True),
    ("---\ndescription: >\n    A 2. dia.\n---\n", True),
    ('```mermaid\n%% A 2. dia\nA["Tananyag"]\n```', False),
    ('# Nyitott kérdések\n```mermaid\nA["A 2. dia"]\n```', False),
])
def test_visible_labels_and_code_boundaries(text, hit):
    assert bool(refs.scan(PAGE, text)) == hit
