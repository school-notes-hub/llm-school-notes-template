"""One shared link/image recognition (wiki/pages.py `LABEL`, `find_links`; sn-helyi 0.3.5): the
alt texts `sn close` inserts escape interval brackets, and every image-specific check sees them."""

from school_notes2.local import guard, places
from school_notes2.local.figure_close import direct_svgs
from school_notes2.state import safefs
from school_notes2.wiki import banners, heading_ids, pages, web_footnote

# The real alt form on Benedek's wiki/matematika/intervallumok.md (unbalanced `\]` inside).
ALT = "Öt számegyenes. \\]−1; 3\\]: −1-nél üres karika. \\[0; 5\\[: 0-nál teli pont. Metszetük \\[0; 3\\]"
IMG = f"![{ALT}](<../assets/matematika/muveletek.svg>)"
PNG = f"![{ALT}](<../assets/matematika/muveletek.png>)"


def test_an_escaped_bracket_alt_is_one_image():
    found = pages.links(f"Szöveg.\n\n{IMG}\n")
    assert [(l.image, l.target, l.line) for l in found] == [(True, "../assets/matematika/muveletek.svg", 3)]
    assert found[0].text == ALT


def test_escapes_nesting_and_paragraphs():
    assert [l.image for l in pages.links("\\![x](a.md)")] == [False]            # an escaped `!`
    assert [l.image for l in pages.links("\\\\![x](a.svg)")] == [True]          # an escaped backslash
    assert pages.links("\\[x](a.md)") == []                                     # an escaped `[`
    assert [l.target for l in pages.links("![a ![b [c [d]]](b.svg) e](a.svg)")] == ["a.svg"]
    assert pages.links("![a\n\nb](a.svg)") == []                                # no paragraph crossing
    assert [l.target for l in pages.links("![a\nb](a.svg)")] == ["a.svg"]       # a line break is fine
    assert pages.links("![a](<a\nb.svg>)") == []


def test_a_replaced_figure_block_with_such_an_alt_is_removed():
    from school_notes2.figures import context
    block = f"<!-- school-notes:generated figure-muveletek -->\n{IMG}\n\nKép.\n<!-- /school-notes:generated -->\n"
    text = f"# T\n\nSzöveg.\n\n{block}\nTovább.\n"
    from school_notes2.wiki import markers
    assert markers.read(text, "figure-muveletek") is not None
    result = context.without_replaced(text, "wiki/matematika/t.md", "wiki/assets/matematika/muveletek.svg")
    assert "muveletek.svg" not in result and "Tovább." in result


def test_the_raster_guard_sees_such_an_image():
    found = guard._raster_links("wiki/matematika/t.md", f"# T\n\n{PNG}\n", "# T\n")
    assert found and "wiki/assets/matematika/muveletek.png" in found[0]


def test_a_broken_image_with_such_an_alt_is_counted(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    safefs.write_text(repo, "wiki/matematika/t.md", f"---\ntitle: T\n---\n# T\n\n{IMG}\n")
    assert places.missing_parts(repo)[1] == {"wiki/assets/matematika/muveletek.svg"}


def test_a_direct_svg_with_such_an_alt_needs_a_receipt(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    safefs.write_text(repo, "wiki/matematika/t.md", f"# T\n\n{IMG}\n")
    safefs.write_text(repo, "wiki/assets/matematika/muveletek.svg", "<svg/>")
    assert direct_svgs(repo, ["wiki/matematika/t.md"], {"wiki/assets/matematika/muveletek.svg"}) == [
        "wiki/assets/matematika/muveletek.svg"]


def test_a_use_on_another_page_with_such_an_alt_is_in_the_usage_keys(tmp_path):
    from school_notes2.figures import context
    repo = tmp_path / "repo"
    repo.mkdir()
    safefs.write_text(repo, "wiki/matematika/t.md", "---\ntitle: T\ntype: topic\n---\n# T\n\nSzöveg.\n")
    safefs.write_text(repo, "wiki/matematika/u.md", f"---\ntitle: U\ntype: topic\n---\n# U\n\nMásik.\n\n{IMG}\n")
    keys = context.usage_keys(repo, {"page": "wiki/matematika/t.md", "id": "muveletek"},
                              {"asset": "wiki/assets/matematika/muveletek.svg"})
    assert [(k["page"], k["alt"]) for k in keys] == [("wiki/matematika/u.md", ALT)]


def test_a_banner_line_with_such_an_alt_is_a_header():
    assert banners.leading(f"\n{IMG}\n\nSzöveg.\n") == IMG


def test_heading_and_web_footnote_labels_share_the_pattern():
    # A deeper-nested image drops out of the heading text whole (the renderer shows only its alt
    # nowhere in the id); a web footnote title with an escaped bracket is still one link.
    assert heading_ids.heading_text("A ![x [y [z]]](a.svg) B", {}, False).split() == ["A", "B"]
    body = "[Intervallum \\] jelölés](https://example.org/a) (ellenőrizve: 2026-10-07)."
    assert web_footnote.problems(body) == []
