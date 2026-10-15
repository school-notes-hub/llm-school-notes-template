"""Generated index blocks (plan 4.10): subject indexes and the root index.

Single source of truth: the pages' frontmatter (`chapters` in the subject index,
`chapter`/`order` on pages, `lessons` on lesson-notes pages) and tools/subjects.json.
Output is a pure function of those inputs, so generation is idempotent and byte-stable.
"""

import json
import re
from pathlib import Path

from ..state import safefs
from . import catch_up, markers, teaching_order
from .pages import read_page, read_text
from .pages import subjects as subject_slugs

# Existing consumers use generate as the entry point; implementations live in focused modules.
from .subject import Subject, load_subject, notebook_folders, chapter_pages, chapter_sections, lesson_date
from .subject_page import (
    anchor_id, desc, listed_chapters, chapters_block, ordered_lessons,
    lessons, subject_chapters, when, plain_line, lesson_rows, lessons_block,
    lesson_links, now_block, by_date_desc, review_block, notes_block, LESSONS_LEGEND,
)
from .home_page import guide_block, legend_block, place_home_blocks


REQUIRED_SUBJECT_BLOCKS = ("chapters", "lessons", "review", "notes")


def place_now(text: str, body: str) -> str:
    """The 📍 block's one fixed place on every subject index: right after the back link to the
    home page, before the catch-up list (else right before the first generated block, else at
    the end). A block standing elsewhere moves there, so existing pages converge."""
    text = markers.remove(text, {"now"})
    back = catch_up.BACK_LINK.search(text)
    block = markers.BLOCK.search(text)
    pos = back.end() if back else (block.start() if block else len(text))
    head, tail = text[:pos].rstrip("\n"), text[pos:].lstrip("\n")
    return head + "\n\n" + markers.wrap("now", body) + "\n" + tail


def with_blocks(text: str, names: tuple[str, ...]) -> str:
    """A required index block the author removed comes back, empty, at the fixed place:
    the end of the page, in canonical order; the refresh then fills it."""
    missing = [n for n in names if n not in markers.names(text)]
    if not missing:
        return text
    return text.rstrip("\n") + "\n\n" + "".join(markers.wrap(n, "") for n in missing)


def subject_index(repo: Path, slug: str) -> str:
    """The subject index text with every generated block refreshed (and present)."""
    text = with_blocks(markers.clean_nested_notices(read_text(repo, f"wiki/{slug}/index.md")),
                       REQUIRED_SUBJECT_BLOCKS)
    subject = load_subject(repo, slug)
    bodies = {"chapters": chapters_block(subject), "lessons": lessons_block(subject),
              "review": review_block(subject), "notes": notes_block(subject)}
    for name in markers.names(text):
        if name in bodies:
            text = markers.replace(text, name, bodies[name])
    text = catch_up.update(text)
    return place_now(move_lessons_head(text), now_block(subject))


# Exact historical machine sentences only: arbitrary prose and tables are never swept.
LEGACY_LESSONS_LEGENDS = {
    "", "A legújabb óra van legfelül.", LESSONS_LEGEND,
    "A legújabb óra van legfelül. A `?` dátum azt jelenti, hogy a füzetben nincs "
    "dátum; ilyenkor a zárójel azt az időszakot adja meg, amelybe az óra esik.",
}
HAND_LESSONS_HEAD = re.compile(r"^# 🗓️ Órák[ \t]*\n", re.M)


def move_lessons_head(text: str) -> str:
    """The idempotent sweep of the hand-written `# 🗓️ Órák` heading and its sentence in front of
    the lessons block (the block writes both now), only with an exact known legend or blank
    lines between them. Unknown prose, tables or any other content leave the page unchanged."""
    head = HAND_LESSONS_HEAD.search(text)
    if not head or any(start <= head.start() < end for start, end, _ in markers.spans(text)):
        return text
    block = text.find("<!-- school-notes:generated lessons -->", head.end())
    between = text[head.end():block] if block >= 0 else ""
    if block < 0 or between.strip() not in LEGACY_LESSONS_LEGENDS:
        return text
    return text[:head.start()] + text[block:]


def subject_order(repo: Path) -> list[str]:
    """subjects.json order (new subjects are appended), then any other subject folder."""
    known = list(load_subjects_json(repo).get("subjects", {}))
    folders = set(subject_slugs(repo))
    return [s for s in known if s in folders] + sorted(folders - set(known))


def load_subjects_json(repo: Path) -> dict:
    try:
        return json.loads(read_text(repo, "tools/subjects.json"))
    except FileNotFoundError:
        return {"subjects": {}}


def subject_sentence(name: str) -> str:
    article = "Az" if name[:1].lower() in "aáeéiíoóöőuúüű" else "A"
    return f"{article} {name.lower()} tantárgy témakörei és jegyzetei."


def subject_label(repo: Path, slug: str) -> str:
    entry = load_subjects_json(repo).get("subjects", {}).get(slug, {})
    name = entry.get("name", slug)
    return f"{entry['emoji']} {name}" if entry.get("emoji") else name


TEMPLATE_SENTENCE = re.compile(r"^(?:A|Az) .+ tantárgy témakörei(?: és jegyzetei)?(?:, évfolyamonként)?\.$")


def root_block(repo: Path) -> str:
    """One line per subject: its name, its own description (not the template sentence a new
    subject starts with) and, smaller, its chapters."""
    lines = []
    subjects = load_subjects_json(repo).get("subjects", {})
    for slug in subject_order(repo):
        entry = subjects.get(slug, {})
        name = entry.get("name", slug)
        emoji = f"{entry['emoji']} " if entry.get("emoji") else ""
        meta = read_page(repo, f"wiki/{slug}/index.md").meta
        own = str(meta.get("description") or "").strip()
        own = "" if TEMPLATE_SENTENCE.match(own) else own
        chapters = [teaching_order.plain_title(str(c["title"])) for c in listed_chapters(
            Subject(slug, meta, "")) if c.get("title")]
        lines.append(f"* {emoji}[{name}]({slug}/index.md)" + (f" - {own}" if own else "")
                     + (desc("Fejezetek: " + " · ".join(chapters)) if chapters else ""))
    return "".join(ln + "\n" for ln in lines)


def root_index(repo: Path) -> str:
    text = markers.clean_nested_notices(read_text(repo, "wiki/index.md"))
    if subject_order(repo):  # An uninitialized wiki has no subjects and no block yet.
        text = with_blocks(text, ("subjects",))
    if "subjects" in markers.names(text):
        text = markers.replace(text, "subjects", root_block(repo))
        text = place_home_blocks(text)
        text = markers.replace(text, "guide", guide_block(repo))
        text = markers.replace(text, "legend", legend_block())
    return text


def write_indexes(repo: Path) -> list[str]:
    """Refresh every index and the Podcast page (while there is an episode: its list shows the
    topic pages' current titles); returns the repo-relative paths that changed."""
    from . import podcast
    changed = []
    targets = [(f"wiki/{s}/index.md", lambda s=s: subject_index(repo, s)) for s in subject_order(repo)]
    targets.append(("wiki/index.md", lambda: root_index(repo)))
    if podcast.records(repo):
        targets.append((podcast.PAGE, lambda: podcast.podcast_page(repo)))
    for rel, build in targets:
        old = read_text(repo, rel) if safefs.is_file(repo, rel) else None
        new = build()
        if new != old:
            safefs.write_text(repo, rel, new)
            changed.append(rel)
    return changed
