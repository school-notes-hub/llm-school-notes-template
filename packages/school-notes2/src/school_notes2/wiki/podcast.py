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
* **Podcast page** `wiki/podcast.md`: the show's name and description, the speakers, then every
  episode newest first (by first release, then subject and page): title, subject, a link to the
  topic page, length, release day, the one-sentence summary and the player. It exists only while
  there is an episode; the site's menu shows it right under the home page (`public.page_order`)."""

import json
from pathlib import Path

from ..schemas import validate
from ..state import safefs
from . import frontmatter, generate, hu_dates, markers
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


def order(found: list[dict]) -> list[dict]:
    """Newest first: by first release day (descending), then subject and page (ascending)."""
    ordered = sorted(found, key=lambda r: (r["subject"], r["page"]))
    return sorted(ordered, key=lambda r: r["first_released"], reverse=True)


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
             "készítette a jegyzetből; a zene a sorozat saját zenéje."]
    if guests:
        lines.append("Vendégek: " + ", ".join(f"{name} ({subject.lower()})" for subject, name in guests) + ".")
    return "\n\n".join(lines) + "\n"


def list_block(repo: Path, found: list[dict]) -> str:
    parts = [intro(repo, found)]
    days = [r["first_released"] for r in found]
    year = hu_dates.school_year(days)
    for r in order(found):
        subject = subject_name(repo, r["subject"])
        topic = page_title(repo, r["page"])
        day = hu_dates.meta(hu_dates.short(r["first_released"], year))
        parts.append(
            f"## {r['title']}\n\n"
            f"{subject} · [{topic}]({relative(PAGE, r['page'])}) · {length(r['duration_s'])} {day}\n\n"
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


def drive_name(subject_name: str, page_title: str) -> str:
    """`<Tantárgy> – <lapcím>.mp3`, accents kept; no path separator or control character."""
    clean = "".join(c for c in f"{subject_name} – {page_title}" if c >= " ").replace("/", "-").replace("\\", "-")
    return " ".join(clean.split()) + ".mp3"


def drive_names(wanted: dict[str, tuple[str, str, str]]) -> dict[str, str]:
    """{episode ident: Drive file name} (`wanted`: ident → (subject name, page title, first
    release day)). Equal names are told apart deterministically: the episode released first (then
    the ident) keeps the name, the next get ` (2)`, ` (3)` before the extension – so a file already
    on Drive never changes its name because a later episode got the same one."""
    out, seen = {}, {}
    for ident in sorted(wanted, key=lambda i: (wanted[i][2], i)):
        base = drive_name(wanted[ident][0], wanted[ident][1])
        n = seen.get(base.casefold(), 0) + 1
        seen[base.casefold()] = n
        out[ident] = base if n == 1 else f"{base[:-4]} ({n}).mp3"
    return out


def dumps(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
