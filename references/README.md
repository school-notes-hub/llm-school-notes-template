# References (textbooks)

(This file is directory documentation, not a source - it is never ingested.)

This directory is **not part of the wiki and not a source** under the wiki's rules. It holds the textbooks the user hands over, converted into an LLM-friendly form (text, image descriptions, provenance). They are not ours: they are used only to

* process the student's notes accurately (check readings, names, dates),
* complete notes that are incomplete,
* put textbook references (lesson, page number) on the topic pages,
* write synthesis pages connected to the notes, in moderation.

The wiki pages are built from the student's notes; facts from a textbook come over only in our own words and with a citation, never as a verbatim passage or a copied figure. This directory is a private working copy: **never share or publish it** (just like `sources/`).

Layout: `references/<subject>/<book-id>/` - one subdirectory per book, holding `README.md` (bibliographic data, page numbering, lesson table, hashes), `document.md` (the book's text), `provenance.json` (elements, pages, citation strings), and the generated `index.md` map (lesson and page -> line range in `document.md`; `uv run tools/book_index.py references/<subject>/<book-id>`). A book is always read through its map, never whole. Full reference rules live in [Sources and evidence](../instructions/sources-and-evidence.md).

A book that may not be converted (for example because its publisher forbids processing it with AI systems) is *index-only*: its directory holds only a `README.md` with a hand-made index - table of contents and subject index, numbers and titles only. See *Index-only books* in [Sources and evidence](../instructions/sources-and-evidence.md).

Optional curriculum requirements are a separate reference collection; follow [curriculum navigation](curriculum/README.md) and the learner profile. The public template includes guidance and tools, not private requirements or textbook copies.

## Local navigation and checks

When local references exist, their `index.md` lists the installed books and collections. Keep bibliographic facts and checked navigation overrides beside the relevant book, rather than editing this shared README. `tools/book-index.json` holds the local navigation language. A checked README lesson table can override an incomplete converted contents table with `<!-- book-index: readme -->` or `--readme`; the general indexer retains both English and Hungarian page-offset recognition.

Apply *Visual evidence checks* in [Sources and evidence](../instructions/sources-and-evidence.md) to relevant images and conversion metadata. A crop may be incomplete even without a warning; an available `manifest.json` or `provenance.json` is diagnostic, not proof of accuracy. Read the local evidence index when it exists. A textbook image without a description is not opened by default; *Inspect available evidence* there says when it may be.
