"""Regression tests for the findings of the first Opus code review (wiki part)."""

import hashlib

from school_notes2.figures.insert import comment_safe
from school_notes2.wiki import check, frontmatter, public


def test_lesson_page_needs_no_type_from_the_writer(repo):
    rel = "wiki/proba/2026-10-02-uj-jegyzet.md"
    (repo / rel).write_text("---\ntitle: Új\ndescription: d\nlessons:\n  - {date: '2026-10-02', "
                            "title: Óra, topics: [elso.md]}\n---\n\n# Új\n")
    found = [i["message"] for i in check.check_files(repo, [rel])]
    assert not any("'type'" in m for m in found), found


def test_check_judges_only_writer_files(repo):
    for rel in ("docs/review/x.md", "sources/proba/csomag/document.md"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("$$ [törött](nincs.md)\n")
    (repo / "references/proba").mkdir(parents=True)
    (repo / "references/proba/k.md").write_text("ghp_" + "a" * 36 + "\n")
    found = check.check_files(repo, ["docs/review/x.md", "sources/proba/csomag/document.md",
                                     "references/proba/k.md"])
    assert [i["file"] for i in found] == ["references/proba/k.md"]


def test_comment_safe_cannot_close_the_html_comment():
    assert "--" not in comment_safe("szép --> kép ---- vége")


def test_public_refuses_a_copied_source_photo_and_knows_generated_receipts(repo):
    rel = "wiki/proba/2026-09-10-elso-jegyzet.md"
    photo = b"source page bytes"
    page = repo / rel     # the lesson page records its source photo's hash (machine frontmatter)
    page.write_text(frontmatter.set_keys(page.read_text(), {"content_sha256": hashlib.sha256(photo).hexdigest()}))
    (repo / "wiki/assets/copy.jpg").write_bytes(photo)
    elso = repo / "wiki/proba/elso.md"
    elso.write_text(elso.read_text() + "\n![x](../assets/copy.jpg)\n")
    try:
        public.build(repo, lambda r: ("authored", "x"))
        raise AssertionError("expected PublicError")
    except public.PublicError as exc:
        assert exc.paths == ["wiki/assets/copy.jpg"] and "source photo" in exc.reason
    (repo / "docs/evidence/media/banner-1").mkdir(parents=True)
    (repo / "wiki/assets/banner").mkdir()
    (repo / "wiki/assets/banner/banner-1.webp").write_bytes(b"image")
    assert public.media_receipt_rights(repo)("wiki/assets/banner/banner-1.webp") is None
