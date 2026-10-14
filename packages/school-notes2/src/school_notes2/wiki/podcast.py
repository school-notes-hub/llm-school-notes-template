"""The published podcast in the wiki: the episode receipts, the topic page's player block and
the generated Podcast page (owner, 2026-10-08: "lehet egy podcast menüpont"; "A podcast neve,
témája kint lehet").

* **Receipt** `docs/evidence/podcast/<subject>/<page>.json` (`sn podcast` writes it, schema
  `podcast-episode`): the episode's title and summary, speakers, the MP3's path and SHA-256,
  length, the review key and the reviewer's verdict, the speech requests, the mix, the name
  check (every listed name, verified or not, with the moment it is heard), the rights, the Drive
  file name and the release dates. It is the MP3's only rights evidence and the Podcast page's
  only input.
* **Topic page block** `podcast` (a generated block at the page's fixed place, after the title
  and the banner): the show's name and the episode title, the player, a machine-voice line with
  a link to the Podcast page. On paper the player is left out; the line stays.
* **Podcast page** `wiki/podcast.md`: the show's name and description, the speakers, then the
  episodes by subject (the home page's subject order), inside a subject by chapter and page in
  the subject index's order (the order the class took them: `generate.chapter_pages` over the
  index's `chapters`), counted 1., 2., 3. per subject (owner, 2026-10-14: "tantárgyanként";
  "nem érthetetlen hézagos számokkal" – the file names' gapped number never shows here). An
  episode whose page stands in no listed chapter (or is gone) closes its subject under
  *Egyéb*, by page. Each: number and title, a link to the topic page, length, release day, the
  one-sentence summary and the player. It exists only while there is an episode; the site's menu
  shows it right under the home page (`public.page_order`)."""

import json
from pathlib import Path

from ..schemas import validate
from ..state import safefs
from . import frontmatter, generate, hu_dates, markers, teaching_order
from .pages import relative

PAGE = "wiki/podcast.md"
BLOCK = "podcast"
LIST_BLOCK = "podcast-episodes"
RECORDS = "docs/evidence/podcast"
SHOW = "Képben vagy?"
NAV_LABEL = "🎧 Podcast"
TITLE = "Podcast"
DESCRIPTION = f"{SHOW} – rövid beszélgetős adások a jegyzet témáiról."
RIGHTS = {"class": "generated",
          "speech": "gépi hang (Google Gemini TTS az OpenRouteren át), a tulajdonos fiókjával",
          "music": "a tulajdonos saját zenéje (Suno, fizetős csomag)",
          "text": "a jegyzet saját tartalma, a jegyzet licence szerint"}


def records(repo: Path) -> list[dict]:
    """Every episode receipt, in path order (unreadable ones are left out; `sn check` reports
    the MP3 link that has none)."""
    out = []
    for rel in safefs.glob(repo, RECORDS, f"{RECORDS}/*/*.json"):
        try:
            value = safefs.read_json(repo, rel, None)
            validate("podcast-episode", value)
        except (ValueError, OSError):
            continue
        out.append(value)
    return out


def by_asset(repo: Path) -> dict[str, dict]:
    return {r["asset"]: r for r in records(repo)}


def length(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _alt(record: dict) -> str:
    return f"{SHOW} – {record['title']}"


def page_block(record: dict) -> str:
    """The topic page's block body (the page is `record['page']`)."""
    page = record["page"]
    return (f"🎧 **{SHOW}** · *{record['title']}* ({length(record['duration_s'])})\n\n"
            f"![{_alt(record)}]({relative(page, record['asset'])})\n\n"
            f"<sub>🤖 Gépi hang a jegyzetből · [Minden adás]({relative(page, PAGE)})</sub>\n")


def with_block(text: str, record: dict) -> str:
    body = page_block(record)
    if BLOCK in markers.names(text):
        return markers.replace(text, BLOCK, body)
    return markers.at_fixed_place(text, BLOCK, body)


OTHER = "Egyéb"


def grouped(repo: Path, found: list[dict]) -> list[tuple[str, list[tuple[str, list[dict]]]]]:
    """[(subject slug, [(chapter title, episodes)])] in the teaching order: subjects as on the
    home page (`generate.subject_order`, then any other by slug), chapters in the index's
    `chapters` order, episodes by their page's place there; the rest under `OTHER`, by page.
    Total and deterministic: every episode exactly once, ties by page path."""
    by_subject: dict[str, list[dict]] = {}
    for r in sorted(found, key=lambda r: (r["subject"], r["page"])):
        by_subject.setdefault(r["subject"], []).append(r)
    known = generate.subject_order(repo)
    out = []
    for slug in known + sorted(set(by_subject) - set(known)):
        episodes = by_subject.get(slug)
        if not episodes:
            continue
        sections, placed = [], set()
        if slug in known:
            subject = generate.load_subject(repo, slug)
            listed = subject.index_meta.get("chapters")
            for chapter in listed if isinstance(listed, list) else []:
                if not isinstance(chapter, dict) or "id" not in chapter:
                    continue
                files = [f"wiki/{slug}/{p.file}" for p in generate.chapter_pages(subject, chapter["id"])]
                inside = sorted((r for r in episodes if r["page"] in files and r["page"] not in placed),
                                key=lambda r: files.index(r["page"]))
                placed |= {r["page"] for r in inside}
                if inside:
                    sections.append((teaching_order.plain_title(str(chapter.get("title") or chapter["id"])),
                                     inside))
        rest = [r for r in episodes if r["page"] not in placed]
        if rest:
            sections.append((OTHER, rest))
        out.append((slug, sections))
    return out


def subject_name(repo: Path, slug: str) -> str:
    return generate.load_subjects_json(repo).get("subjects", {}).get(slug, {}).get("name", slug)


def page_title(repo: Path, rel: str) -> str:
    try:
        return str(frontmatter.split(safefs.read_text(repo, rel)).meta.get("title") or rel)
    except (OSError, ValueError):
        return rel


def intro(repo: Path, found: list[dict]) -> str:
    hosts = sorted({s["name"] for r in found for s in r["speakers"] if s["role"] == "host"})
    guests = sorted({(subject_name(repo, r["subject"]), s["name"]) for r in found
                     for s in r["speakers"] if s["role"] == "guest"})
    host = " és ".join(hosts) or "a műsorvezető"
    lines = [f"**{SHOW}** – rövid beszélgetés a jegyzet egy-egy témájáról. {host}, a műsorvezető, minden "
             "adásban egy vendéggel beszélget, aki keni-vágja a tárgyát. Egy adás egy témát dolgoz fel néhány "
             "percben, és a végén elhangzik, mit kell biztosan tudni belőle a dolgozatra. A hangot gép "
             "készítette a jegyzetből; a zene a sorozat saját zenéje.",
             "Az adások tantárgyanként és fejezetenként abban a sorrendben állnak, ahogy az órán vettük az "
             "anyagot: elölről hátrafelé haladva sorban meghallgathatók."]
    if guests:
        lines.append("Vendégek: " + ", ".join(f"{name} ({subject.lower()})" for subject, name in guests) + ".")
    return "\n\n".join(lines) + "\n"


def list_block(repo: Path, found: list[dict]) -> str:
    parts = [intro(repo, found)]
    days = [r["first_released"] for r in found]
    year = hu_dates.school_year(days)
    for slug, sections in grouped(repo, found):
        parts.append(f"## {generate.subject_label(repo, slug)}\n")
        n = 0
        for chapter, episodes in sections:
            parts.append(f"### 📘 {chapter}\n")
            for r in episodes:
                n += 1
                topic = page_title(repo, r["page"])
                day = hu_dates.meta(hu_dates.short(r["first_released"], year))
                parts.append(
                    f"#### {n}. {r['title']}\n\n"
                    f"[{topic}]({relative(PAGE, r['page'])}) · {length(r['duration_s'])} {day}\n\n"
                    f"{r['summary']}\n\n"
                    f"![{_alt(r)}]({relative(PAGE, r['asset'])})\n")
    return "\n".join(parts)


def podcast_page(repo: Path) -> str | None:
    """The Podcast page's text, or None when there is no episode."""
    found = records(repo)
    if not found:
        return None
    head = frontmatter.set_keys("", {"title": TITLE, "description": DESCRIPTION})
    text = safefs.read_text(repo, PAGE) if safefs.is_file(repo, PAGE) else head + f"\n# {TITLE}\n\n" + \
        markers.wrap(LIST_BLOCK, "")
    if LIST_BLOCK not in markers.names(text):
        text = text.rstrip("\n") + "\n\n" + markers.wrap(LIST_BLOCK, "")
    return markers.replace(text, LIST_BLOCK, list_block(repo, found))


def write_page(repo: Path) -> bool:
    """Refresh the Podcast page (create it with the first episode); True if it changed."""
    text = podcast_page(repo)
    if text is None or (safefs.is_file(repo, PAGE) and safefs.read_text(repo, PAGE) == text):
        return False
    safefs.write_text(repo, PAGE, text)
    return True


def missing_blocks(repo: Path) -> list[str]:
    """Episodes whose topic page has lost its player block (or is gone)."""
    out = []
    for r in records(repo):
        if not safefs.is_file(repo, r["page"]) or BLOCK not in markers.names(safefs.read_text(repo, r["page"])):
            out.append(f"{r['page']} ({r['asset']})")
    return sorted(out)


def drive_name(subject_name: str, page_title: str, number: int) -> str:
    """`<Tantárgy> – 00100_<lapcím>.mp3` (`media_order`): the subject first, because the one
    `Podcast/` folder holds every subject and a leading number would interleave them; then the
    subject's five-digit order number, so the folder's alphabetical order is the teaching order.
    Accents kept; no path separator or control character."""
    from . import media_order
    title = "".join(c for c in page_title if c >= " ").replace("/", "-").replace("\\", "-")
    subject = "".join(c for c in subject_name if c >= " ").replace("/", "-").replace("\\", "-")
    return " ".join(f"{subject} – {media_order.numbered(number, ' '.join(title.split()))}".split()) + ".mp3"


def drive_names(wanted: dict[str, tuple[str, str, str, int]]) -> dict[str, str]:
    """{episode ident: Drive file name} (`wanted`: ident → (subject name, page title, first
    release day, order number)). The number makes the names of one subject distinct; two
    subjects with the same name are still told apart deterministically: the episode released
    first (then the ident) keeps the name, the next get ` (2)`, ` (3)` before the extension."""
    out, seen = {}, {}
    for ident in sorted(wanted, key=lambda i: (wanted[i][2], i)):
        base = drive_name(wanted[ident][0], wanted[ident][1], wanted[ident][3])
        n = seen.get(base.casefold(), 0) + 1
        seen[base.casefold()] = n
        out[ident] = base if n == 1 else f"{base[:-4]} ({n}).mp3"
    return out


def dumps(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
