"""sn 0.3.10 (rules 1.22.8), the fix round of the 0.3.9 review: only a complete lesson or textbook
line leaves the verdict key; one order graph for `after`, notebook order and dates; a folder with
two PDFs is no notebook; hand-written date spans as generated. Each test fails on ce7d7a5."""

import json

from school_notes2.figures import context
from school_notes2.wiki import date_spans, generate, markers, teaching_order
from tests.wiki.conftest import write
from tests.wiki.test_release_039 import base, titles
from tests.wiki.test_teaching_order import lesson_log


def section(lines):
    return context.canonical("# T\n\nSzöveg.\n\n" + lines + "\n", "wiki/p/t.md", {})


def test_only_a_complete_closed_lesson_line_leaves_the_key():
    plain = section("")
    assert section("<sub>🗓️ Óra: szept. 3.</sub>") == plain
    assert section("<sub>🗓️ Órák: szept. 3., 4.</sub>[^a][^b]") == plain
    assert section("<sub>🔖 Tankönyv: 2. lecke, 12. oldal</sub>") == plain
    # text after </sub> and a 🗓️ line without <sub> are content: they stay in the key
    assert section("<sub>🗓️ Óra: szept. 3.</sub> A gyorsulás 2 m/s².") != plain
    assert section("<sub>🗓️ Óra: szept. 3.</sub> A gyorsulás 20 m/s².") != section(
        "<sub>🗓️ Óra: szept. 3.</sub> A gyorsulás 2 m/s².")
    assert section("🗓️ Óra: szept. 3.") != plain
    assert section("<sub>🗓️ Óra: szept. 3.</sub> x <sub>y</sub>") != plain


def test_after_and_notebook_order_share_one_graph(tmp_path):
    repo = base(tmp_path)
    note = "date_note: '2026-09-04 után, legkésőbb 2026-09-10'"
    # A3: a.md holds A1 then A2; A1 comes after C of z.md; equal ranges
    lesson_log(repo, "a-jegyzet.md", "proba/a", [f"{{{note}, title: A1, topics: [alap.md], after: z-jegyzet.md}}",
                                                f"{{{note}, title: A2, topics: [alap.md]}}"])
    lesson_log(repo, "z-jegyzet.md", "proba/z", [f"{{{note}, title: C, topics: [alap.md]}}"])
    assert titles(repo) == ["A2", "A1", "C"]                                  # newest first: C, A1, A2
    # notebook page 1 explicitly after notebook page 2: a circle with the page order
    for name, first, row in (("p1-jegyzet.md", "p0001.jpg", f"{{{note}, title: P1, topics: [uj.md], after: p2-jegyzet.md}}"),
                             ("p2-jegyzet.md", "p0002.jpg", f"{{{note}, title: P2, topics: [uj.md]}}")):
        write(repo, f"wiki/proba/{name}", f"---\ntype: lesson-notes\ntitle: x\ndescription: d\nsource_file: proba/fuzet/\n"
                                          f"content_sha256: {{{first}: x}}\nlessons:\n  - {row}\n---\n")
    write(repo, "sources/proba/fuzet/p0001.jpg", "x")
    write(repo, "sources/proba/fuzet/p0002.jpg", "x")
    found = teaching_order.order_warnings(repo, ["wiki/proba/p1-jegyzet.md"])
    assert any("closes a circle" in w["message"] and w["severity"] == "error" for w in found)
    # an `after` against certain dates
    lesson_log(repo, "d-jegyzet.md", "proba/d", ["{date: '2026-09-01', title: D, topics: [alap.md], after: e-jegyzet.md}"])
    lesson_log(repo, "e-jegyzet.md", "proba/e", ["{date: '2026-09-20', title: E, topics: [alap.md]}"])
    found = teaching_order.order_warnings(repo, ["wiki/proba/d-jegyzet.md"])
    assert any("contradicts the dates" in w["message"] and w["severity"] == "error" for w in found)


def test_a_folder_with_two_pdfs_is_no_notebook(tmp_path):
    repo = tmp_path / "repo"
    for rel in ("sources/a/x.pdf", "sources/a/y.pdf", "sources/a/p0001.jpg", "sources/b/x.pdf",
                "sources/b/p0001.jpg", "sources/b/p0002.jpg", "sources/c/fuzet.pdf", "sources/d/page-01.jpeg"):
        write(repo, rel, "x")
    assert generate.notebook_folders(repo, {"a", "b", "c", "d"}) == {"b", "c", "d"}


def test_hand_written_date_spans_become_the_generated_ones(tmp_path):
    repo = base(tmp_path)
    lesson_log(repo, "a-jegyzet.md", "proba/a", ["{date_note: '2026-09-10 után, legkésőbb 2026-09-19', title: A, topics: [alap.md]}"])
    old = '<span class="study-when study-when-unsure" title="Dátum nélküli óra: szept. 11. – 19.">~szept. közepe</span>'
    write(repo, "wiki/proba/alap.md", "---\ntype: topic\ntitle: Alap\ndescription: d\nchapter: elso\norder: 10\n---\n"
          f"# Alap\n\n<sub>🗓️ Óra: [{old}](a-jegyzet.md) · 🔖 Tankönyv: 2. lecke</sub>\n\nSzöveg {old} marad.\n")
    [warning] = date_spans.warnings(repo, ["wiki/proba/alap.md"])
    assert warning["severity"] == "warning" and warning["line"] == 10
    changes = date_spans.apply(repo)
    text = (repo / "wiki/proba/alap.md").read_text()
    new = '<span class="study-when study-when-unsure" title="Dátum nélküli óra: szept. 11–19.">~szept. közepe</span>'
    assert f"<sub>🗓️ Óra: [{new}](a-jegyzet.md) · 🔖 Tankönyv: 2. lecke</sub>" in text
    assert f"Szöveg {old} marad." in text                     # outside a lesson line: untouched
    assert ("wiki/proba/alap.md", 1) in changes
    index = (repo / "wiki/proba/index.md").read_text()
    assert "# 🗓️ Órák\n\nA legújabb óra van legfelül. A `~` bizonytalan dátumot jelöl" in index
    assert date_spans.apply(repo) == []                       # idempotent
    assert date_spans.warnings(repo, ["wiki/proba/alap.md"]) == []
