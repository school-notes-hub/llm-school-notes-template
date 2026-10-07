"""Fix-47 (védelmek-review 2, 3, 5): tool blocks at a readable fixed place in canonical
order, required index blocks come back, and one shared notion of the tool's own lines."""

import itertools

import pytest

from school_notes2.state import safefs
from school_notes2.wiki import author, generate, markers

BODIES = {"lesson-banner": "![Banner](../assets/b.svg)\n", "lesson-sources": "📎 Füzet: 2026. 09. 01.\n",
          "pending": "⏳ Ezt az oldalt még ellenőrizzük.\n"}
TITLED = "---\ntype: lesson-notes\n---\n\n# Mit tanultunk ezen az órán\n\n* [Pont](elso.md#pont)\n"
UNTITLED = "---\ntype: topic\n---\nBevezető mondat.\n\n# Első rész\n"


@pytest.mark.parametrize("order", list(itertools.permutations(BODIES)))
@pytest.mark.parametrize("start", [TITLED, UNTITLED])
def test_tool_blocks_go_below_the_title_in_canonical_order(order, start):
    """Whatever order they are created in: banner → 📎 → ⏳, below the H1 (or right after the
    frontmatter when the body does not start with one); adding a block never changes the
    author text."""
    text = start
    for name in order:
        new = markers.at_fixed_place(text, name, BODIES[name])
        assert author.part(new) == author.part(text)
        assert author.part(new, legacy_notices=True) == author.part(text, legacy_notices=True)
        text = new
    markers.check(text)
    assert [n for _, _, n in markers.spans(text)] == list(BODIES)
    if start == TITLED:
        assert text.index("# Mit tanultunk") < text.index("<!-- school-notes:generated lesson-banner")
    else:
        assert text.index("<!-- school-notes:generated lesson-banner") < text.index("Bevezető mondat.")


@pytest.mark.parametrize("name", generate.REQUIRED_SUBJECT_BLOCKS)
def test_removed_subject_index_block_comes_back(repo, name):
    """Védelmek-review 2: the author may delete a tool index block; generation restores it."""
    rel = "wiki/proba/index.md"
    full = generate.subject_index(repo, "proba")
    safefs.write_text(repo, rel, markers.remove(full, {name}))
    generate.write_indexes(repo)
    text = safefs.read_text(repo, rel)
    assert markers.names(text).count(name) == 1 and markers.read(text, name) == markers.read(full, name)
    assert generate.write_indexes(repo) == []  # deterministic: nothing more to do


def test_root_subjects_block_comes_back_only_once_there_are_subjects(repo, tmp_path):
    safefs.write_text(repo, "wiki/index.md", markers.remove(safefs.read_text(repo, "wiki/index.md"), {"subjects"}))
    generate.write_indexes(repo)
    assert "subjects" in markers.names(safefs.read_text(repo, "wiki/index.md"))
    empty = tmp_path / "empty"
    empty.mkdir()
    safefs.write_text(empty, "wiki/index.md", "# School notes wiki (not initialized)\n")
    assert generate.write_indexes(empty) == []
