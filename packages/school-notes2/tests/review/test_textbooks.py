from school_notes2.review import textbooks, topic_input
from school_notes2.state import safefs
from school_notes2.wiki import frontmatter
from tests.review.test_topics import prepare


BOOK = "references/s/book"


def seed(repo):
    safefs.write_text(repo, BOOK + "/README.md", "# Book\n")
    safefs.write_text(repo, BOOK + "/index.md", "# Map\n\n* 10: 2 · 11: 4 · 12: 6\n")
    safefs.write_text(repo, BOOK + "/document.md", "Private preface\nPage ten\nTen text\nPage eleven\nEleven text\nPage twelve\n")


def test_exact_printed_ranges_multiple_references_and_last_page(tmp_path):
    seed(tmp_path)
    safefs.write_text(tmp_path, "wiki/s/a.md", "# A\n<sub>🔖 Tankönyv: 3. lecke, 10-11. oldal; 4. lecke, 12. oldal.</sub>\n")
    rows = textbooks.collect(tmp_path, ["wiki/s/a.md"])
    assert [e["page"] for e in rows[0]["excerpts"]] == [10, 11, 12]
    assert [e["text"] for e in rows[0]["excerpts"]] == ["Page ten\nTen text\n", "Page eleven\nEleven text\n", "Page twelve\n"]
    assert all("Private preface" not in e["text"] for e in rows[0]["excerpts"])


def test_ambiguous_or_unavailable_book_is_explicit(tmp_path):
    seed(tmp_path)
    safefs.write_text(tmp_path, "references/s/other/README.md", "# Index only\n")
    path = "wiki/s/a.md"
    body = "# A\n🔖 Tankönyv: 10. oldal.\n"
    safefs.write_text(tmp_path, path, body)
    row = textbooks.collect(tmp_path, [path])[0]
    assert row["status"] == "unresolved-book" and row["excerpts"] == []
    safefs.write_text(tmp_path, path, frontmatter.set_keys(body, {"sources": [{"resource": "../../references/s/other/README.md"}]}))
    assert textbooks.collect(tmp_path, [path])[0]["excerpts"] == [{"status": "index-only", "book": "references/s/other"}]
    safefs.write_text(tmp_path, path, body.replace("Tankönyv", "[Tankönyv](../../references/s/book/document.md)"))
    assert textbooks.collect(tmp_path, [path])[0]["excerpts"][0]["text"] == "Page ten\nTen text\n"


def test_topic_input_contains_book_content(tmp_path, repos):
    seed(repos.laptop)
    repos.commit({"wiki/s/a.md": "# A\n🔖 Tankönyv: 10. oldal.\n"})
    task = prepare(tmp_path, repos)
    folder = task.dir / "input"
    topic_input.prepare(repos.repo, repos.wt_path, task, task.get("units")[0], folder)
    assert safefs.read_json(folder, "input.json")["textbooks"][0]["excerpts"][0]["text"] == "Page ten\nTen text\n"


def test_reviewer_checklist_literal():
    from school_notes2.llm.argv import prompt
    assert "7. A nyitott tételek ítélete." in prompt("reviewer", grade=9)
