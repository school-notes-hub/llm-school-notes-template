"""Generated index blocks (plan 4.10): subject indexes and the root index.

Single source of truth: the pages' frontmatter (`chapters` in the subject index,
`chapter`/`order` on pages, `lessons` on lesson-notes pages) and tools/subjects.json.
Output is a pure function of those inputs, so generation is idempotent and byte-stable.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..state import safefs
from . import catch_up, hu_dates, markers, teaching_order
from .pages import md_files, read_page, read_text
from .pages import subjects as subject_slugs

ISO = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass
class SubjectPage:
    file: str            # file name inside the subject folder
    meta: dict


@dataclass
class Subject:
    slug: str
    index_meta: dict
    index_title: str     # the index's first `# ` heading
    pages: list[SubjectPage] = field(default_factory=list)
    notebooks: set[str] = field(default_factory=set)   # source folders that hold one notebook
    repo: Path | None = None

    def by_type(self, kind: str) -> list[SubjectPage]:
        return [p for p in self.pages if p.meta.get("type") == kind]

    def page(self, file: str) -> SubjectPage | None:
        return next((p for p in self.pages if p.file == file), None)


def load_subject(repo: Path, slug: str) -> Subject:
    index = read_page(repo, f"wiki/{slug}/index.md")
    heading = next((ln[2:].strip() for ln in index.body.splitlines() if ln.startswith("# ")), slug)
    subject = Subject(slug, index.meta, heading, repo=repo)
    for rel in md_files(repo, f"wiki/{slug}/*.md"):
        name = rel.rsplit("/", 1)[1]
        if name != "index.md":
            subject.pages.append(SubjectPage(name, read_page(repo, rel).meta))
    subject.notebooks = notebook_folders(repo, {teaching_order.first_folder(p.meta)
                                                for p in subject.by_type("lesson-notes")} - {""})
    return subject


NOTEBOOK_PAGE = re.compile(r"^(?:p\d{4}|page-\d+)\.(?:jpe?g|png|webp)$", re.I)


def notebook_folders(repo: Path, folders: set[str]) -> set[str]:
    """The source folders whose page order is the order of one notebook (teaching-order
    evidence): every stored page split from one PDF (its manifest), or, for a folder without a
    manifest, exactly one PDF with or without its page images, or only PDF-page images
    (`p0001.jpg`, `page-07.jpeg`). Two PDFs, or a catch-up folder of separate photos, may mix
    notebooks: their order is no evidence. The same folder gets the same answer with or without
    a manifest (older learner folders have none)."""
    out = set()
    for folder in sorted(folders):
        base = f"sources/{folder}"
        if safefs.is_file(repo, f"{base}/sn-fetch.json"):
            try:
                pages = [p for p in json.loads(read_text(repo, f"{base}/sn-fetch.json")).get("pages", [])
                         if not p.get("duplicate_of")]
            except ValueError:
                continue
            if pages and all(p.get("page") for p in pages) and len({p.get("file") for p in pages}) == 1:
                out.add(folder)
        elif safefs.is_dir(repo, base):
            files = [n for n in safefs.listdir(repo, base) if not n.startswith(".")]
            pdfs = [n for n in files if n.lower().endswith(".pdf")]
            pages = [n for n in files if NOTEBOOK_PAGE.match(n)]
            # one PDF (with or without its page images), or only PDF-page images; two PDFs may
            # be two notebooks, so their order is no evidence
            if len(pdfs) <= 1 and (pdfs or pages) and len(pdfs) + len(pages) == len(files):
                out.add(folder)
    return out


def chapter_pages(subject: Subject, chapter_id: str) -> list[SubjectPage]:
    inside = [p for p in subject.pages if p.meta.get("chapter") == chapter_id]
    return sorted(inside, key=lambda p: (_order(p.meta), p.file))


def chapter_sections(subject: Subject) -> list[tuple[dict, list[SubjectPage]]]:
    """The teaching order of a subject's pages: the index's `chapters` list (the order the class
    started them) with each chapter's pages (`chapter_pages`); a malformed entry is left out, a
    page stands only under the first chapter that has it. The Podcast page, the media order
    numbers and the video order all walk this."""
    listed = subject.index_meta.get("chapters")
    out, seen = [], set()
    for chapter in listed if isinstance(listed, list) else []:
        if not isinstance(chapter, dict) or "id" not in chapter:
            continue
        pages = [p for p in chapter_pages(subject, chapter["id"]) if p.file not in seen]
        seen |= {p.file for p in pages}
        out.append((chapter, pages))
    return out


def _order(meta: dict) -> int:
    """A missing or non-integer `order` sorts last; the check reports it on topic pages."""
    order = meta.get("order", 0)
    return order if isinstance(order, int) and not isinstance(order, bool) else 10**9


def anchor_id(text: str) -> str:
    """A jump-target id the renderer keeps as written (study-site `isJumpTarget`): lower-case
    letters, digits and hyphens; anything else becomes a hyphen."""
    return "".join(ch if ch.isdigit() or (ch.isalpha() and ch.islower()) or ch == "-" else "-"
                   for ch in text.lower())


def chapter_anchor(chapter_id: str) -> str:
    """The jump target in front of a chapter heading (the 🧭 box and the page breadcrumbs)."""
    return anchor_id(f"fejezet-{chapter_id}")


SUMMARY_NOTE = "A fejezet röviden, ismétléshez és dolgozat előtt."
HERE = "◀ itt tartunk"


def desc(text: str) -> str:
    """A list line's description: smaller and grey under the title (the stylesheet)."""
    return f' <span class="study-desc">{text}</span>' if text else ""


def list_line(page: SubjectPage) -> str:
    return f"* [{page.meta.get('title', page.file)}]({page.file}){desc(page.meta.get('description', ''))}"


def topic_line(number: int, page: SubjectPage, here: bool) -> str:
    """A worked lesson (topic page) in its chapter: 📄, its number in the teaching order, its
    title and description; `◀ itt tartunk` when the latest lesson covered it."""
    mark = f" {HERE}" if here else ""
    return (f"* 📄 {number}. [{page.meta.get('title', page.file)}]({page.file}){mark}"
            f"{desc(page.meta.get('description', ''))}")


def summary_line(page: SubjectPage) -> str:
    """The chapter summary, last in its chapter, with the fixed note of what it is for."""
    return f"* ⚡ [{page.meta.get('title', page.file)}]({page.file}){desc(SUMMARY_NOTE)}"


@dataclass
class Progress:
    """Where the class is (`teaching_order`): the chapter started last (`now`), the chapters
    started before it (`done`), and the pages the latest lesson covered (`latest`)."""
    now: str | None
    done: set[str]
    latest: list[str]
    spans: dict[str, str]


def progress(subject: Subject, found: list[teaching_order.Lesson] | None = None) -> Progress:
    found = ordered_lessons(subject) if found is None else found
    chapters_ = subject_chapters(subject, found)
    started = teaching_order.by_start(chapters_)
    latest = [str(t) for t in (found[-1].data.get("topics") or [])] if found else []
    return Progress(started[-1].id if started else None, {c.id for c in started[:-1]}, latest,
                    teaching_order.spans(chapters_, teaching_order.year_of(found)))


def listed_chapters(subject: Subject) -> list[dict]:
    listed = subject.index_meta.get("chapters")
    return [c for c in listed if isinstance(c, dict) and "id" in c] if isinstance(listed, list) else []


def chapter_mark(state: Progress, chapter_id: str) -> str:
    return " ✓" if chapter_id in state.done else " ◉ most" if chapter_id == state.now else ""


def chapters_block(subject: Subject) -> str:
    """The chapters in the `chapters` list order (the writer keeps it in the order the class
    started them; `sn check` warns otherwise), numbered, each with a jump target, its ✓ (started
    before the current one) or ◉ (the current one) mark and when it was taught (🗓️); inside, the
    worked lessons numbered in teaching order (`order`), the summary last."""
    state = progress(subject)
    latest = {t.split("#", 1)[0] for t in state.latest}
    sections = []
    for number, chapter in enumerate(listed_chapters(subject), 1):
        cid = str(chapter["id"])
        pages = [p for p in chapter_pages(subject, cid) if p.meta.get("type") != "lesson-notes"]
        topics = [p for p in pages if p.meta.get("type") != "chapter-summary"]
        lines = [topic_line(n, p, p.file in latest) for n, p in enumerate(topics, 1)]
        lines += [summary_line(p) for p in pages if p.meta.get("type") == "chapter-summary"]
        head = (f'# <a id="{chapter_anchor(cid)}"></a>📘 {number}. fejezet: '
                f"{teaching_order.plain_title(str(chapter['title']))}{chapter_mark(state, cid)}\n")
        when = f"\n{state.spans[cid]}\n" if cid in state.spans else ""
        sections.append(head + when + ("\n" + "\n".join(lines) + "\n" if lines else ""))
    return "\n<br />\n\n".join(sections)


PARTIAL_DATE = re.compile(r"^\d{4}-\d{2}-(?:\d\?|\?\d|\?\?)")


def lesson_date(lesson: dict) -> str:
    """The table's Dátum cell: the notebook date, or `?` with the range it must fall in."""
    date, note = lesson.get("date"), lesson.get("date_note")
    if date:
        return f"{date}; {note}" if note else str(date)
    if note and PARTIAL_DATE.match(note):
        return note          # a partly legible date ("2026-09-1? (levágva …)") stands as written
    return f"? ({note})" if note else "?"


notebook_position = teaching_order.notebook_position


def ordered_lessons(subject: Subject) -> list[teaching_order.Lesson]:
    """Every lesson of the subject, oldest first (`teaching_order`: an undated lesson by the lower
    bound of its range), with its `uncertain` mark."""
    return teaching_order.ordered([(p.file, p.meta) for p in subject.by_type("lesson-notes")], subject.notebooks)


def lessons(subject: Subject) -> list[tuple[SubjectPage, dict]]:
    """Every lesson of the subject, newest first."""
    return [(subject.page(lesson.file), lesson.data) for lesson in reversed(ordered_lessons(subject))]


def subject_chapters(subject: Subject, found: list[teaching_order.Lesson]) -> list[teaching_order.Chapter]:
    pages = {p.file: str(p.meta.get("chapter")) for p in subject.pages if p.meta.get("chapter")}
    return teaching_order.chapters(subject.index_meta, pages, found)


def topic_link(subject: Subject, topic: str) -> str:
    """`[title](file.md#anchor)`; the title always comes from the page itself."""
    target = subject.page(topic.split("#", 1)[0])
    title = target.meta.get("title", topic) if target else topic
    return f"[{title}]({topic})"


PARTLY = re.compile(r"\d{4}-\d{2}-(?:\d\?|\?\d|\?\?)|\bvagy\b|részben olvasható")


def when(lesson: teaching_order.Lesson, year: int) -> str:
    """The lesson's day as a quiet date item (`hu_dates.meta`): `okt. 6.` (a note on a dated
    lesson as its tooltip); an undated lesson `~` + its approximate day (`hu_dates.approximate`),
    the range only in the tooltip – `Bizonytalan dátum: …` for a partly legible date or two
    possible days, `Dátum nélküli óra: …` otherwise."""
    note = str(lesson.data.get("date_note") or "")
    if lesson.dated:
        return hu_dates.meta(hu_dates.short(lesson.lo, year), hu_dates.in_text(note, year))
    what = "Bizonytalan dátum" if PARTLY.search(note) else "Dátum nélküli óra"
    title = f"{what}: {hu_dates.range_text(lesson.lo, lesson.hi, year)}" + (
        "; a helye a sorban nem biztos" if lesson.uncertain else "")
    return hu_dates.meta(hu_dates.approximate(lesson.lo, lesson.hi, year), title, unsure=True)


LESSONS_HEAD = "# 🗓️ Órák – melyik órán mit vettünk"
LESSONS_LEGEND = ("A legújabb óra van legfelül. A `~` bizonytalan dátumot jelöl; az időszakot az "
                  "egér rávitelekor vagy koppintásra látod.")
LEADING_MARK = re.compile(r"^(\d+)([.)])|^([#>+*-])")


def plain_line(text: str) -> str:
    """A lesson title as plain text at the start of a list line: a leading `1.`, `#`, `>`, `+`,
    `*` or `-` would start Markdown structure, so it is escaped."""
    return LEADING_MARK.sub(lambda m: f"{m[1]}\\{m[2]}" if m[1] else f"\\{m[3]}", text.strip())


def lesson_rows(subject: Subject, found: list[teaching_order.Lesson] | None = None) -> list[tuple[teaching_order.Lesson, list[str]]]:
    """Every lesson, newest first, with the jump targets of its row: `ora-<lesson log>` on the
    newest row of each lesson log, `ora-<lesson log>-<anchor>` on a row whose lesson names an
    `anchor` (the first such row when two name the same)."""
    found = ordered_lessons(subject) if found is None else found
    rows, seen = [], set()
    for item in reversed(found):
        stem = item.file[:-3] if item.file.endswith(".md") else item.file
        ids = [anchor_id(f"ora-{stem}")]
        if item.data.get("anchor"):
            ids.append(anchor_id(f"ora-{stem}-{item.data['anchor']}"))
        ids = [i for i in ids if i not in seen]
        seen.update(ids)
        rows.append((item, ids))
    return rows


def lessons_block(subject: Subject) -> str:
    """🗓️ Órák: one line per lesson, newest first – the lesson's title, its quiet date, then
    `→` its worked lessons (topic pages); never a link to the lesson log itself."""
    found = ordered_lessons(subject)
    if not found:
        return ""
    year = teaching_order.year_of(found)
    lines = [LESSONS_HEAD, "", LESSONS_LEGEND, ""]
    for item, ids in lesson_rows(subject, found):
        targets = "".join(f'<a id="{i}"></a>' for i in ids)
        topics = " · ".join(topic_link(subject, t) for t in item.data.get("topics") or [])
        lines.append(f"* {targets}{plain_line(str(item.data.get('title', '')))} {when(item, year)}"
                     + (f"<br />→ {topics}" if topics else ""))
    return "\n".join(lines) + "\n"


def lesson_links(subject: Subject) -> dict[str, dict[str, str]]:
    """Where a link to a lesson log goes on the public site (it is not published there): for each
    lesson log of the subject, fragment → the jump target of its row in the 🗓️ Órák list. `""`
    (no or an unknown fragment) is the log's newest row; a lesson's `anchor` its own row; every
    other jump target written on the same line as a lesson's anchor in the log that lesson's row."""
    from .pages import read_text
    rows: dict[str, dict[str, str]] = {}
    for item, ids in reversed(lesson_rows(subject)):
        stem = item.file[:-3]
        page = rows.setdefault(item.file, {})
        if anchor_id(f"ora-{stem}") in ids:
            page[""] = anchor_id(f"ora-{stem}")
        anchor = item.data.get("anchor")
        own = anchor_id(f"ora-{stem}-{anchor}") if anchor else ""
        if anchor and own in ids:
            page[str(anchor)] = own
    for file, page in rows.items():
        try:
            text = read_text(subject.repo, f"wiki/{subject.slug}/{file}") if subject.repo else ""
        except OSError:
            text = ""
        for line in text.splitlines():
            found_ids = JUMP_ID.findall(line)
            owner = next((page[i] for i in found_ids if i in page and i), None)
            for i in found_ids:
                if owner and i not in page:
                    page[i] = owner
    return {file: dict(sorted(page.items())) for file, page in sorted(rows.items())}


JUMP_ID = re.compile(r'<a id="([^"]+)"></a>')


def now_block(subject: Subject) -> str:
    """🧭 Hol tartunk, a box without a heading: the chapters in the `chapters` list order on one
    line (✓ started before the current one, ◉ the current one, with when it was taught), the
    worked lessons of the latest lesson, and the current chapter's summary for revision. Only
    topic pages and summaries are linked, never a lesson log."""
    found = ordered_lessons(subject)
    if not found:
        return ""
    state = progress(subject, found)
    steps = []
    for chapter in listed_chapters(subject):
        cid = str(chapter["id"])
        kind = " class=\"study-path-done\"" if cid in state.done else \
            " class=\"study-path-now\"" if cid == state.now else ""
        mark = " ✓" if cid in state.done else " ◉" if cid == state.now else ""
        when_ = f" {state.spans[cid]}" if cid in state.spans and kind else ""
        steps.append(f'<li{kind}><a href="#{chapter_anchor(cid)}">'
                     f"{teaching_order.plain_title(str(chapter['title']))}</a>{mark}{when_}</li>")
    lines = ["> [!TIP]", "> 🧭 **Hol tartunk**", ">", '> <ol class="study-path">' + "".join(steps) + "</ol>"]
    pages = [t for t in state.latest
             if (subject.page(t.split("#", 1)[0]) or SubjectPage("", {})).meta.get("type") in ("topic", "chapter-summary")]
    if pages:
        lines += [">", "> **Most:** " + " · ".join("📄 " + topic_link(subject, t) for t in pages)]
    summary = next((p for p in chapter_pages(subject, state.now)
                    if p.meta.get("type") == "chapter-summary"), None) if state.now else None
    if summary:
        lines += [">", f"> **Ismétléshez:** ⚡ [{summary.meta.get('title', summary.file)}]({summary.file})"]
    return "\n".join(lines) + "\n"


def by_date_desc(pages: list[SubjectPage]) -> list[SubjectPage]:
    ordered = sorted(pages, key=lambda p: p.file)
    return sorted(ordered, key=lambda p: p.file[:10], reverse=True)


def review_block(subject: Subject) -> str:
    pages = by_date_desc(subject.by_type("review"))
    if not pages:
        return ""
    lines = "\n".join(list_line(p) for p in pages)
    return f"# 🔁 Ismétlés\n\n{lines}\n\n<br />\n\n"


def notes_block(subject: Subject) -> str:
    """Empty: the lesson logs are the writer's tool and not on the public site; the 🗓️ Órák list
    says which lesson covered what. The block stays, so its name keeps its place."""
    return ""


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


HAND_LESSONS_HEAD = re.compile(r"^# 🗓️ Órák[ \t]*\n", re.M)


def move_lessons_head(text: str) -> str:
    """The one-time sweep of the hand-written `# 🗓️ Órák` heading and its sentence in front of
    the lessons block (the block writes both now): from the heading to the block, when nothing
    but text stands between them (no other heading, block or spacer); otherwise unchanged."""
    head = HAND_LESSONS_HEAD.search(text)
    if not head or any(start <= head.start() < end for start, end, _ in markers.spans(text)):
        return text
    block = text.find("<!-- school-notes:generated lessons -->", head.end())
    between = text[head.end():block] if block >= 0 else ""
    if block < 0 or re.search(r"^(?:#|<!--|<br)", between, re.M):
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


GUIDE_ANCHOR = "hogyan-hasznald"
GUIDE = [
    "* 📚 **Tantárgyoldal**: a tantárgy fejezetei a tanítás sorrendjében, bennük a kidolgozott "
    "leckék. Felül a 🧭 **Hol tartunk** doboz: ✓ a már elkezdett, ◉ a mostani fejezet; alul az "
    "🗓️ **Órák**: melyik órán mit vettünk.",
    "* 📄 **Kidolgozott lecke** (témalap): a teljes tananyag: ⚡ Röviden, magyarázat, ábrák, "
    "🧠 Kérdezd ki magad. Tanuláshoz, házihoz, dolgozatra készüléshez.",
    "* ⚡ **Összefoglaló**: a fejezet rövid változata, a fejezet végén; ismétléshez és dolgozat "
    "előtt. Minden pontja a kidolgozott leckére visz.",
    "* 🗓️ **Órák**: a tantárgyoldal alján, a legújabb óra felül. A dátum kicsi; a `~` azt jelenti, "
    "hogy nem biztos – koppints rá, vagy vidd rá az egeret, és látod az időszakot.",
]
GUIDE_PODCAST = ("* 🎧 **Podcast**: rövid beszélgetés egy-egy kidolgozott leckéről; a lecke ⚡ Röviden "
                 "doboza alatt és a 🎧 Podcast oldalon hallgathatod.")
LEGEND = [
    "A jelöletlen szöveg az órán tanult anyag. Ami ehhez hozzá van téve, azt kis címke jelöli "
    "közvetlenül a hozzá tartozó tartalom alatt; a címkére koppintva vagy az egeret rávive a "
    "jelentését is látod. A 🤖 gépi szerzőséget mutat, nem hitelesítést.",
    "",
    "* 💡 **Magyarázat** (<sub>💡 🤖 gépi magyarázat</sub>): kifejti, amit az órai anyag csak röviden "
    "ír le: miért van így, hogyan jutunk az eredményhez.",
    "* ➕ **Kiegészítés** (<sub>➕ 🤖 gépi kiegészítés</sub>): kitölt egy, a megértéshez fontos hiányt.",
    "* ⚠️ **Javítás** (<sub>⚠️ 🤖 gépi javítás</sub>): a helyes változat ott, ahol az órai jegyzetben "
    "hiba volt; ilyenkor javítsd a füzetedet is.",
    "* 📗 **A tankönyv alapján**: a tankönyvből vett rész, amely az órai jegyzetben nem szerepelt.",
    "* 🗓️ **Óra**: melyik órán tanultátok az adott részt; ha nincs pontos dátum, `~` jelzi, az "
    "időszakot az egér rávitelekor vagy koppintásra látod.",
    "* 🔖 **Tankönyv**: a kapcsolódó lecke és oldal, vagy az, hogy a tankönyv ezt nem tárgyalja.",
    "* ⚡ **Röviden**: a kidolgozott lecke elején a legfontosabb tudnivalók; ezt nézd át dolgozat "
    "előtt. A fejezet ⚡ **Összefoglaló** oldala ezekből áll össze.",
    "* 🧠 **Kérdezd ki magad**: kérdések a kidolgozott lecke végén; a választ lenyitva "
    "ellenőrizheted magad.",
]


def guide_block(repo: Path) -> str:
    """🧭 Hogyan használd: the page kinds and the parts of a subject page, the same text for every
    learner (the 🎧 line while there is a Podcast page)."""
    from . import podcast
    lines = GUIDE + ([GUIDE_PODCAST] if safefs.is_file(repo, podcast.PAGE) else [])
    # no closing `<br />`: a raw HTML line would swallow the legend block's heading after it
    return f'# <a id="{GUIDE_ANCHOR}"></a>🧭 Hogyan használd\n\n' + "\n".join(lines) + "\n"


def legend_block() -> str:
    return "# 🔎 Jelmagyarázat\n\n" + "\n".join(LEGEND) + "\n"


HAND_LEGEND = re.compile(r"^# 🔎 Jelmagyarázat[ \t]*\n", re.M)
SECTION_END = re.compile(r"^(?:#{1,6} |<!-- school-notes:generated |<br\s*/?>)", re.M)


def place_home_blocks(text: str) -> str:
    """The guide and legend blocks' place on the home page, once: the hand-written
    `# 🔎 Jelmagyarázat` section (to the next heading, block or spacer) becomes the two blocks;
    without one they go right after the subjects block; a guide missing beside an existing
    legend goes in front of it."""
    names = markers.names(text)
    if "guide" in names and "legend" in names:
        return text
    if "legend" in names:
        start = next(s for s, _, n in markers.spans(text) if n == "legend")
        return text[:start] + markers.wrap("guide", "") + text[start:]
    old = HAND_LEGEND.search(text)
    if old and not any(s <= old.start() < e for s, e, _ in markers.spans(text)):
        end = SECTION_END.search(text, old.end())
        stop = end.start() if end else len(text)
        return text[:old.start()] + markers.wrap("guide", "") + markers.wrap("legend", "") + "\n" + text[stop:]
    after = next((e for _, e, n in markers.spans(text) if n == "subjects"), None)
    if after is None:
        return text
    return (text[:after].rstrip("\n") + "\n\n<br />\n\n" + markers.wrap("guide", "")
            + markers.wrap("legend", "") + "\n" + text[after:].lstrip("\n"))


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
