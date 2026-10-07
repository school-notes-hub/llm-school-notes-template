import pytest

from school_notes2.state import safefs
from school_notes2.wiki import banners, frontmatter, lesson_log, markers
from school_notes2.wiki.author import page_key

LESSON = "wiki/proba/2026-09-10-elso-jegyzet.md"


def reuse(repo):
    text = safefs.read_text(repo, LESSON)
    return frontmatter.set_keys(text, {"banner_from": "elso.md"})


def test_banner_follows_topic_and_notices_stay_outside_block(repo):
    text = reuse(repo)
    text = banners.update(repo, LESSON, text)
    text = lesson_log.after_header(text, "pending", "⏳ Ezt az oldalt még ellenőrizzük.\n")
    markers.check(text)
    assert "../assets/abra.svg" in markers.read(text, banners.BLOCK)
    assert "⏳" not in markers.read(text, banners.BLOCK)
    assert banners.update(repo, LESSON, text) == text
    safefs.write_text(repo, LESSON, text)
    key = page_key(repo, LESSON)
    safefs.write_bytes(repo, "wiki/assets/abra.svg", b"changed")
    assert page_key(repo, LESSON) == key  # R1: a banner change is not an author change.
    topic = safefs.read_text(repo, "wiki/proba/elso.md").replace("abra.svg", "other.svg")
    safefs.write_text(repo, "wiki/proba/elso.md", topic)
    updated = banners.update(repo, LESSON, text)
    assert "other.svg" in updated and "abra.svg" not in updated


@pytest.mark.parametrize("target", ["missing.md", "../index.md", "elso.md#resz", "https://example.test/a.md"])
def test_invalid_banner_target_is_refused(repo, target):
    text = frontmatter.set_keys(reuse(repo), {"banner_from": target})
    with pytest.raises((ValueError, OSError)):
        banners.update(repo, LESSON, text)


def test_writer_header_is_never_replaced_and_no_later_figure_used(repo):
    """E7: the tool never edits the writer's lines; its block goes to the fixed place."""
    text = reuse(repo).replace("# Mit tanultunk", "![Old](../assets/old.png)\n\n# Mit tanultunk")
    updated = banners.update(repo, LESSON, text)
    assert "![Old](../assets/old.png)" in updated and updated.count("abra.svg") == 1
    assert updated.index("abra.svg") < updated.index("old.png")
    safefs.write_text(repo, "wiki/proba/elso.md", "---\ntype: topic\n---\n# Téma\n\nTananyag.\n\n![Ábra](a.png)\n")
    assert banners.body(repo, LESSON, frontmatter.split(text).meta) == ""


def test_nested_notice_cleanup_preserves_reused_banner_author_key(repo):
    from school_notes2.wiki import author
    text = reuse(repo).replace("# Mit tanultunk", "![Old](../assets/old.png)\n\n# Mit tanultunk")
    updated = banners.update(repo, LESSON, text)
    banner = markers.read(updated, banners.BLOCK)
    nested = markers.replace(updated, banners.BLOCK, markers.wrap("pending", "Pending\n") + banner)
    assert author.part(nested) == author.part(updated) == author.part(text)
