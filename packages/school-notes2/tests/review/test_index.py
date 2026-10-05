from school_notes2.review import files, index


def test_index_block_on_top_and_hand_text_kept(tmp_path):
    idx = tmp_path / "docs/review/index.md"
    idx.parent.mkdir(parents=True)
    idx.write_text("# Review-állapot\n\nKézzel írt rész.\n", encoding="utf-8")
    review = {"verdict": "changes", "findings": [{"severity": "hiba", "id": "R1", "file": "w.md", "problem": "x"}]}
    files.write_review(tmp_path, "2026-10-01", review, "r", "a", "b")
    files.write_review(tmp_path, "2026-10-02", {"verdict": "ok", "findings": []}, "r", "b", "c")
    index.update(tmp_path)
    text = idx.read_text(encoding="utf-8")
    assert text.startswith("<!-- school-notes:generated review-index -->\n## Nyitott")
    assert text.endswith("# Review-állapot\n\nKézzel írt rész.\n")
    assert "* [2026-10-01-review](2026-10-01-review.md) – R1" in text
    assert "## Lezárt\n\n* [2026-10-02-review](2026-10-02-review.md)\n" in text
    assert "## Tulajdonosra vár\n\n* nincs" in text
    index.update(tmp_path)
    assert idx.read_text(encoding="utf-8") == text
    files.apply_closure(tmp_path, "run", [{"file": "docs/review/2026-10-01-review.md",
                                           "item_id": "R1", "status": "fixed"}], [])
    index.update(tmp_path)
    new = idx.read_text(encoding="utf-8")
    assert "## Nyitott\n\n* nincs" in new and new.count("<!-- school-notes:generated") == 1
