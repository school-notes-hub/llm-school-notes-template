"""A small synthetic learner repo in the v2 format (after migration)."""

import json
import hashlib
from pathlib import Path

import pytest

from school_notes2.wiki import markers

INDEX = """---
description: A próba tantárgy témakörei.
chapters:
  - {id: alapok, title: '9. évfolyam: Alapok'}
  - {id: halado, title: '9. évfolyam: Haladó'}
---

# Próba

[⬅️ Vissza a kezdőlapra](../index.md)

<br />

""" + markers.wrap("chapters", "") + """
<br />

# 🗓️ Órák

A legújabb óra van legfelül.

""" + markers.wrap("lessons", "") + """
<br />

""" + markers.wrap("review", "") + markers.wrap("notes", "")

ROOT = """---
okf_version: "0.2"
---

# Jegyzetek

# 📚 Tantárgyak

""" + markers.wrap("subjects", "") + """
<br />
"""


LESSON_BODY = ("\n# Mit tanultunk ezen az órán\n\n"
               "* [Első fogalom](elso.md#elso-fogalom)\n"
               "* [Második fogalom](elso.md#masodik-fogalom)\n"
               "* [Alkalmazás](elso.md#alkalmazas)\n")


def page(meta: str, body: str = "\n# Cím\n") -> str:
    return f"---\n{meta}\n---\n{body}"


def write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path) -> Path:
    r = tmp_path / "repo"
    write(r, "wiki/index.md", ROOT)
    write(r, "wiki/a-projektrol.md", "# A projektről\n")
    write(r, "wiki/log.md", "# Napló\n")
    write(r, "wiki/proba/index.md", INDEX)
    write(r, "wiki/proba/osszefoglalo-alapok.md", page(
        "type: chapter-summary\ntitle: 'Összefoglaló: Alapok'\ndescription: Rövid.\nchapter: alapok\norder: 5"))
    write(r, "wiki/proba/elso.md", page(
        "type: topic\ntitle: Első\ndescription: Az első téma.\nchapter: alapok\norder: 10",
        "\n![ábra](../assets/abra.svg)\n\nForrás: [fotó](../../sources/proba/csomag/01.jpg)\n"))
    write(r, "wiki/proba/masodik.md", page(
        "type: topic\ntitle: Második\ndescription: A második téma.\nchapter: halado\norder: 10"))
    write(r, "wiki/proba/2026-09-10-elso-jegyzet.md", page(
        "type: lesson-notes\ntitle: Első óra\ndescription: Jegyzet.\nlessons:\n"
        "  - {date: '2026-09-03', title: Bevezetés, topics: [elso.md]}\n"
        "  - {date_note: 'legkésőbb 2026-09-10', title: Folytatás, topics: [elso.md, masodik.md#resz]}", LESSON_BODY))
    write(r, "wiki/proba/2026-09-20-dolgozat.md", page(
        "type: review\ntitle: Dolgozatra\ndescription: Ismétlés."))
    write(r, "wiki/assets/abra.svg", "<svg/>")
    write(r, "sources/proba/csomag/01.jpg", "jpeg")
    write(r, "tools/subjects.json", json.dumps(
        {"subjects": {"proba": {"name": "Próba", "emoji": "🧪"}}}, ensure_ascii=False))
    write(r, "publication/public.json", json.dumps(
        {"version": 1, "mode": "public", "title": "T", "base": "/t/", "publicationApproved": True,
         "assets": [{"path": "wiki/assets/abra.svg", "sha256": hashlib.sha256(b"<svg/>").hexdigest(), "rights": "authored",
                     "publicationReviewed": True}]}))
    return r
