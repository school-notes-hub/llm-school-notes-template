import pytest

from school_notes2.state import safefs
from school_notes2.wiki import banners, frontmatter, lesson_log, markers
from school_notes2.reader import units

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
    key = units.page_key(repo, LESSON)
    safefs.write_bytes(repo, "wiki/assets/abra.svg", b"changed")
    assert units.page_key(repo, LESSON) != key
    topic = safefs.read_text(repo, "wiki/proba/elso.md").replace("abra.svg", "other.svg")
    safefs.write_text(repo, "wiki/proba/elso.md", topic)
    updated = banners.update(repo, LESSON, text)
    assert "other.svg" in updated and "abra.svg" not in updated


@pytest.mark.parametrize("target", ["missing.md", "../index.md", "elso.md#resz", "https://example.test/a.md"])
def test_invalid_banner_target_is_refused(repo, target):
    text = frontmatter.set_keys(reuse(repo), {"banner_from": target})
    with pytest.raises((ValueError, OSError)):
        banners.update(repo, LESSON, text)


def test_existing_header_is_replaced_and_no_later_figure_used(repo):
    text = reuse(repo).replace("# Mit tanultunk", "![Old](../assets/old.png)\n\n# Mit tanultunk")
    updated = banners.update(repo, LESSON, text)
    assert "old.png" not in updated and updated.count("abra.svg") == 1
    safefs.write_text(repo, "wiki/proba/elso.md", "---\ntype: topic\n---\n# Téma\n\nTananyag.\n\n![Ábra](a.png)\n")
    assert banners.body(repo, LESSON, frontmatter.split(text).meta) == ""


def test_banner_reuse_assigns_log_even_when_main_topic_is_not_first(repo):
    text = reuse(repo)
    text = frontmatter.set_keys(text, {"banner_from": "masodik.md"})
    safefs.write_text(repo, LESSON, text)
    grouped = units.collect(repo, ["wiki/proba/masodik.md"])
    assert any(LESSON in u["pages"] for u in grouped)


def test_reusing_old_raw_header_does_not_look_like_an_edit_during_finish(repo):
    from school_notes2.flows.steps import _llm_hash
    text = reuse(repo).replace("# Mit tanultunk", "![Old](../assets/old.png)\n\n# Mit tanultunk")
    updated = banners.update(repo, LESSON, text)
    assert _llm_hash(LESSON, text.encode()) == _llm_hash(LESSON, updated.encode())


def test_candidate_banner_key_matches_final_publication_not_preview_png(repo):
    text = reuse(repo)
    safefs.write_text(repo, LESSON, banners.update(repo, LESSON, text))
    asset = "wiki/assets/new-banner.svg"
    safefs.write_bytes(repo, asset, b"<svg>new</svg>")
    brief = {"id": "new-banner", "page": "wiki/proba/elso.md", "kind": "banner"}
    candidate = {"state": "candidate", "asset": asset, "alt": "New banner", "caption": "",
                 "form": "banner", "tool": "svg", "elements": [], "visible_text": [], "attempt": 1}
    safefs.write_json(repo, ".school-notes/figures/new-banner/figure.json", candidate)
    image = banners.candidate_image(repo, LESSON, [brief])
    key = units.page_key(repo, LESSON, banner_image=image)
    safefs.write_text(repo, brief["page"], '---\ntype: topic\n---\n![New banner](../assets/new-banner.svg)\n')
    safefs.write_text(repo, LESSON, banners.update(repo, LESSON, safefs.read_text(repo, LESSON)))
    assert units.page_key(repo, LESSON) == key


@pytest.mark.parametrize("legacy", [False, True])
def test_banner_preview_key_supports_notice_compatibility(repo, legacy):
    from school_notes2.wiki import author
    from school_notes2.flows import steps
    text = banners.update(repo, LESSON, reuse(repo))
    safefs.write_text(repo, LESSON, text)
    image = "![Preview](<../assets/preview.svg>)"
    safefs.write_bytes(repo, "wiki/assets/preview.svg", b"preview")
    key = units.page_key(repo, LESSON, banner_image=image, legacy_notices=legacy)
    noticed = lesson_log.after_header(text, "pending", "Pending\n")
    safefs.write_text(repo, LESSON, noticed)
    assert steps._llm_part is author.part
    noticed_key = units.page_key(repo, LESSON, banner_image=image, legacy_notices=legacy)
    # Compatibility deliberately retains the old notice-dependent whitespace key.
    assert (noticed_key == key) is not legacy
    safefs.write_bytes(repo, "wiki/assets/preview.svg", b"changed preview")
    assert units.page_key(repo, LESSON, banner_image=image, legacy_notices=legacy) != noticed_key


def test_nested_notice_cleanup_preserves_reused_banner_author_key(repo):
    from school_notes2.wiki import author
    text = reuse(repo).replace("# Mit tanultunk", "![Old](../assets/old.png)\n\n# Mit tanultunk")
    updated = banners.update(repo, LESSON, text)
    banner = markers.read(updated, banners.BLOCK)
    nested = markers.replace(updated, banners.BLOCK, markers.wrap("pending", "Pending\n") + banner)
    assert author.part(nested) == author.part(updated) == author.part(text)
