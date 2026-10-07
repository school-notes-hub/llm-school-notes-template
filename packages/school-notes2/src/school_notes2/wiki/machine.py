"""Machine-written wiki data (plan 4.9, 5.2, 5.4/3): lesson-notes frontmatter,
`generated` stamps, subjects.json entries and the new-subject index skeleton.

The LLM decides which pages belong to which lesson-notes page (`result.notes[].pages`);
everything derivable from that and from fetch.json is written here, never by the LLM.
"""

from pathlib import Path

from ..state import safefs
from . import frontmatter, generate, markers

LESSON_KEYS = ("type", "grade", "sources", "source_file", "content_sha256", "original_sha256",
               "drive_folder", "generated")
LESSONS_LEGEND = ("A legújabb óra van legfelül. A `?` dátum azt jelenti, hogy a füzetben nincs "
                  "dátum; ilyenkor a zárójel azt az időszakot adja meg, amelybe az óra esik.")


def machine_keys(meta: dict) -> tuple[str, ...]:
    """Keys only the tool may write on a page of this kind (the path guard cuts these)."""
    keys = LESSON_KEYS if meta.get("type") == "lesson-notes" else ("generated",)
    return keys + ("draft_tracking",)


def subject_skeleton(name: str, banner_id: str) -> str:
    """wiki/<subject>/index.md for a new subject: hand-written frame, empty generated blocks."""
    head = frontmatter.set_keys("", {"description": generate.subject_sentence(name),
                                     "chapters": []})
    return (head + f"\n# {name}\n\n<!-- image: {banner_id} -->\n\n"
            "[⬅️ Vissza a kezdőlapra](../index.md)\n\n<br />\n\n"
            + markers.wrap("chapters", "")
            + "\n<br />\n\n# 🗓️ Órák\n\n" + LESSONS_LEGEND + "\n\n"
            + markers.wrap("lessons", generate.TABLE_HEAD)
            + "\n<br />\n\n" + markers.wrap("review", "") + markers.wrap("notes", ""))


def create_subject(repo: Path, slug: str, name: str, banner_id: str) -> str | None:
    """Write the skeleton if the subject index does not exist yet; returns its path."""
    rel = f"wiki/{slug}/index.md"
    if safefs.exists(repo, rel):
        return None
    safefs.write_text(repo, rel, subject_skeleton(name, banner_id))
    return rel
