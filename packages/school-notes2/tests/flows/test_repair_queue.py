"""Repair ordering, dependencies and private source/figure inventory (plan 11)."""

import pytest

from school_notes2.repair import queue
from school_notes2.state import safefs
from school_notes2.state.errors import NeedsOwner
from school_notes2.wiki import frontmatter


def page(repo, name, kind="topic", body="Tananyag.\n", **meta):
    rel = f"wiki/m/{name}.md"
    safefs.write_text(repo, rel, frontmatter.set_keys(body, {"type": kind, "chapter": "c", **meta}))
    return rel


def test_queue_order_is_total_preserves_owner_priority_and_state(tmp_path):
    a = page(tmp_path, "a", body="A 3. dián ez látszik.\n", lessons=[{"date": "2026-09-01"}])
    b = page(tmp_path, "b", body="A 3. dián ez látszik.\n", lessons=[{"date": "2026-09-02"}])
    c = page(tmp_path, "c")
    d = page(tmp_path, "d")
    first = queue.build(tmp_path)
    assert [i["page"] for i in first["items"]] == [b, a, c, d]
    first["items"][1].update(priority=0, status="done")
    rebuilt = queue.build(tmp_path, first)
    assert [i["page"] for i in rebuilt["items"]] == [a, b, c, d]
    assert rebuilt["items"][0]["status"] == "done"
    assert queue.build(tmp_path, rebuilt) == rebuilt
    rebuilt["items"][0]["priority"] = "first"
    with pytest.raises(NeedsOwner, match="priority"):
        queue.build(tmp_path, rebuilt)


def test_dependent_passes_wait_for_every_topic_including_missing(tmp_path):
    a, b = page(tmp_path, "a"), page(tmp_path, "b")
    lesson = page(tmp_path, "2026-10-04-x-jegyzet", "lesson-notes",
                  lessons=[{"date_note": "Nem ismert", "topics": ["a.md", "b.md"]}])
    summary = page(tmp_path, "summary", "chapter-summary")
    review = page(tmp_path, "exam", "review", body="[A](a.md) [B](b.md)")
    data = queue.build(tmp_path)
    for rel in (lesson, summary, review):
        assert next(i for i in data["items"] if i["page"] == rel)["depends_on"] == [a, b]
        with pytest.raises(NeedsOwner, match="dependencies"):
            queue.require_ready(rel, data, queue.inventory(tmp_path))
    assert next(i for i in data["items"] if i["page"] == lesson)["last_lesson"] == ""
    for i in data["items"]:
        if i["page"] in (a, b):
            i["status"] = "done"
    for rel in (lesson, summary, review):
        queue.require_ready(rel, data, queue.inventory(tmp_path))
    assert queue.next_item(data)["page"] in (lesson, summary, review)
    data["items"] = [i for i in data["items"] if i["page"] != b]
    assert queue.next_item(data) is None


def test_full_source_folders_and_svg_inventory_without_copying_sources(tmp_path):
    a = page(tmp_path, "a", body="![Rajz](../assets/a.svg)\n")
    page(tmp_path, "lesson", "lesson-notes", lessons=[{"topics": ["a.md"]}],
         source_file="m/book/", sources=[{"resource": "../../sources/m/book/document.md"}])
    safefs.write_text(tmp_path, "sources/m/book/document.md", "![Ábra](p2.jpg)")
    safefs.write_text(tmp_path, "sources/m/book/p2.jpg", "image")
    safefs.write_text(tmp_path, "wiki/assets/a.svg", '<svg><text>A 3. dián</text></svg>')
    book = queue.inventory(tmp_path)
    assert queue.sources(tmp_path, a, book) == ["sources/m/book/document.md", "sources/m/book/p2.jpg"]
    result = queue.build(tmp_path)
    assert result["figures"][0]["pages"] == [a]
    assert result["figures"][0]["status"] == "pending"
    assert result["figures"][0]["matches"] == 0  # No text heuristic orders the queue (T5).
    result["figures"][0]["status"] = "keep"
    assert queue.build(tmp_path, result)["figures"][0]["status"] == "keep"
    safefs.write_text(tmp_path, "wiki/assets/a.svg", '<svg><text>Új</text></svg>')
    assert queue.build(tmp_path, result)["figures"][0]["status"] == "pending"


@pytest.mark.parametrize("student", ["benedek", "barna"])
def test_urgent_is_owner_data_and_no_text_pattern_reorders(tmp_path, student):
    repo = tmp_path / student
    repo.mkdir()
    a, b = page(repo, "a"), page(repo, "b")
    data = queue.build(repo)
    assert not any(i["urgent"] for i in data["items"])
    data["items"][1]["urgent"] = True
    rebuilt = queue.build(repo, data)
    assert rebuilt["items"][0]["page"] == b
    assert queue.build(repo, rebuilt) == rebuilt
    rebuilt["items"][0]["urgent"] = False
    assert queue.build(repo, rebuilt)["items"][0]["page"] == a
    page(repo, "b", body="A 3. dián ez látszik.\n")
    # No text pattern makes a page urgent (T5): only the owner's field orders the queue.
    assert queue.build(repo)["items"][0]["page"] == a


def test_queue_validation_refuses_ambiguous_or_invalid_state(tmp_path):
    page(tmp_path, "a")
    data = queue.build(tmp_path)
    data["items"].append(dict(data["items"][0]))
    safefs.write_json(tmp_path, queue.PATH, data)
    with pytest.raises(NeedsOwner, match="duplicate page"):
        queue.load(tmp_path)
    data["items"].pop()
    data["items"][0]["status"] = "doen"
    safefs.write_json(tmp_path, queue.PATH, data)
    with pytest.raises(NeedsOwner, match="invalid repair queue"):
        queue.load(tmp_path)
