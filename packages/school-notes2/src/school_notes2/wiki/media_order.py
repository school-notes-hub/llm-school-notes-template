"""The order number in the file names of the podcast episodes and the videos (owner, 2026-10-14:
"legyen biztosítva egy sorrend a videókban, podcastekben, ahogy sorban vették a tananyagot";
"A fájlnévben magában is lehet egy sorszám … 100_ 200_ 300_ -> és akkor még beszúrni is lehet:
150_"; approved: one level per subject, five digits with leading zeros, step 100).

**What is numbered.** Every page of a subject that stands in one of its chapters, in the subject
index's order (`generate.chapter_pages` over the index's `chapters` list – the order the class
started the chapters, the pages inside by `order`): topic pages and chapter summaries, whether
they have an episode or a video yet or not. A page gets its number when it first appears, so a
podcast or a video made later (or backwards through the subject) never needs a number between
two others; only a page inserted into an earlier chapter does.

**Stored, not recomputed.** The numbers live in the learner repo, `docs/evidence/media-order.json`
(next to the podcast and video receipts; `sn close` and `sn podcast` write it, the writer guard
keeps everyone else out). A stored number stays as long as it is in order: of the stored numbers
the longest run that increases along the current order is kept; every other page (new, or moved
by the writer) gets a number between its kept neighbours – the middle of the gap, k pages spread
evenly (100 and 200 → 150) –, after the last one the next hundred. When a gap has no free number,
the whole subject is numbered again, 100, 200, … in the teaching order, and the caller says so in
one line (owner, 2026-10-14: renaming is acceptable while the bulk generation runs). A number is
never wider than five digits and never above `MAX` (99900): beyond that `MediaOrderError`.

**Where it shows.** Only in the file names (`numbered`): the Drive file of an episode,
`<Tantárgy> – 00100_<lapcím>.mp3`, and the finished video, `00100_<lap>-<n>.mp4`. The site never
shows it (owner: "a weblapon jó lenne normálisan látni, nem érthetetlen hézagos számokkal"): the
Podcast page counts 1., 2., 3. itself."""

import json
import re
from pathlib import Path

from ..state import safefs
from . import generate

STORE = "docs/evidence/media-order.json"
WIDTH = 5
STEP = 100
MAX = 99900
PREFIX = re.compile(r"^\d{5}_")


class MediaOrderError(ValueError):
    pass


def teaching_pages(repo: Path, slug: str) -> list[str]:
    """The subject's chapter pages (file stems) in the subject index's order."""
    subject = generate.load_subject(repo, slug)
    listed = subject.index_meta.get("chapters") if isinstance(subject.index_meta.get("chapters"), list) else []
    out: list[str] = []
    for chapter in listed:
        if not isinstance(chapter, dict) or "id" not in chapter:
            continue
        for page in generate.chapter_pages(subject, chapter["id"]):
            stem = page.file[:-3]
            if stem not in out:
                out.append(stem)
    return out


def _kept(order: list[str], stored: dict[str, int]) -> dict[str, int]:
    """The stored numbers to keep: the longest strictly increasing run along `order`
    (deterministic: of equally long runs the one patience sorting finds)."""
    seq = [(stem, stored[stem]) for stem in order if stem in stored]
    tails: list[int] = []          # index into seq of the smallest tail of each length
    prev: list[int] = [-1] * len(seq)
    for i, (_, value) in enumerate(seq):
        lo, hi = 0, len(tails)
        while lo < hi:
            mid = (lo + hi) // 2
            if seq[tails[mid]][1] < value:
                lo = mid + 1
            else:
                hi = mid
        prev[i] = tails[lo - 1] if lo else -1
        if lo == len(tails):
            tails.append(i)
        else:
            tails[lo] = i
    keep, i = {}, tails[-1] if tails else -1
    while i >= 0:
        keep[seq[i][0]] = seq[i][1]
        i = prev[i]
    return keep


def _fill(lo: int, hi: int | None, k: int) -> list[int] | None:
    """k increasing numbers strictly between lo and hi (None: after the last kept one)."""
    if hi is None:
        if lo + k * STEP <= MAX:
            return [lo + STEP * (m + 1) for m in range(k)]
        hi = MAX + 1
    if hi - lo - 1 < k:
        return None
    return [lo + (hi - lo) * (m + 1) // (k + 1) for m in range(k)]


def renumbered(order: list[str]) -> dict[str, int]:
    if len(order) * STEP > MAX:
        raise MediaOrderError(f"{len(order)} lap nem fér el {WIDTH} jegyen {STEP}-as lépéssel (legfeljebb "
                              f"{MAX // STEP}); a sorszám szélesebb nem lehet, mert az a fájlok betűrendjét "
                              "felborítaná – tulajdonosi döntés kell")
    return {stem: STEP * (i + 1) for i, stem in enumerate(order)}


def assign(order: list[str], stored: dict[str, int]) -> tuple[dict[str, int], bool]:
    """({stem: number} for every page of `order`, renumbered whole). Pure and deterministic."""
    valid = {s: v for s, v in stored.items()
             if s in set(order) and type(v) is int and 1 <= v <= MAX}
    result = _kept(order, valid)
    i, n = 0, len(order)
    while i < n:
        if order[i] in result:
            i += 1
            continue
        j = i
        while j < n and order[j] not in result:
            j += 1
        lo = result[order[i - 1]] if i else 0
        hi = result[order[j]] if j < n else None
        numbers = _fill(lo, hi, j - i)
        if numbers is None:
            return renumbered(order), True
        result.update(zip(order[i:j], numbers))
        i = j
    return {stem: result[stem] for stem in order}, False


def load(repo: Path) -> dict[str, dict[str, int]]:
    if not safefs.is_file(repo, STORE):
        return {}
    try:
        value = json.loads(safefs.read_text(repo, STORE))
    except ValueError:
        return {}
    subjects = value.get("subjects") if isinstance(value, dict) else None
    return {s: {k: v for k, v in pages.items() if type(v) is int}
            for s, pages in (subjects or {}).items() if isinstance(pages, dict)}


def dumps(numbers: dict[str, dict[str, int]]) -> str:
    value = {"about": f"Sorszám a podcast- és videófájlok nevében (tantárgyanként, {WIDTH} jegy, {STEP}-as "
                      "lépés); csak az sn írja.",
             "subjects": {s: dict(sorted(pages.items(), key=lambda kv: (kv[1], kv[0])))
                          for s, pages in sorted(numbers.items()) if pages}}
    return json.dumps(value, ensure_ascii=False, indent=1) + "\n"


def compute(repo: Path) -> tuple[dict[str, dict[str, int]], list[str]]:
    """(the numbers every subject should have now, the subjects numbered again whole)."""
    stored = load(repo)
    out, again = {}, []
    for slug in generate.subject_order(repo):
        try:
            numbers, whole = assign(teaching_pages(repo, slug), stored.get(slug, {}))
        except MediaOrderError as exc:
            raise MediaOrderError(f"{slug}: {exc}") from None
        out[slug] = numbers
        if whole and stored.get(slug):
            again.append(slug)
    return out, again


def media_pages(repo: Path) -> dict[str, set[str]]:
    """{subject: page stems with a released episode or a finished video} (from the receipts)."""
    out: dict[str, set[str]] = {}
    for rel in safefs.glob(repo, "docs/evidence/podcast", "docs/evidence/podcast/*/*.json"):
        _, _, _, subject, name = rel.split("/")
        out.setdefault(subject, set()).add(name[:-5])
    for rel in safefs.glob(repo, "docs/evidence/video", "docs/evidence/video/*/*.json"):
        _, _, _, subject, name = rel.split("/")
        out.setdefault(subject, set()).add(video_page(name[:-5]))
    return out


def video_page(video: str) -> str:
    """`forgatonyomatek-1` → `forgatonyomatek` (a video is `<page>-<part>`)."""
    return re.sub(r"-\d+$", "", video)


def update(repo: Path) -> tuple[bool, list[str]]:
    """Write the store when it differs; (changed, report lines). A line only when a file that
    already exists (an episode or a video) will be renamed: per subject one line."""
    numbers, again = compute(repo)
    old = load(repo)
    text = dumps(numbers)
    changed = not safefs.is_file(repo, STORE) or safefs.read_text(repo, STORE) != text
    lines = []
    if changed:
        safefs.write_text(repo, STORE, text)
        media = media_pages(repo)
        for slug in sorted(numbers):
            moved = sorted(p for p in media.get(slug, ()) if p in old.get(slug, {})
                           and old[slug][p] != numbers[slug].get(p))
            if slug in again:
                lines.append(f"sorszám: {slug} újraszámozva {STEP}-as lépéssel (nem volt szabad szám): "
                             f"{len(moved)} adás- vagy videófájl neve változik a következő sn publish-kor")
            elif moved:
                lines.append(f"sorszám: {slug}: {len(moved)} adás- vagy videófájl új sorszámot kapott (a lapja "
                             "máshová került); a neve a következő sn publish-kor változik")
    return changed, lines


def number(repo: Path, subject: str, stem: str, numbers: dict | None = None) -> int | None:
    numbers = load(repo) if numbers is None else numbers
    return numbers.get(subject, {}).get(stem)


def numbered(value: int, name: str) -> str:
    """`00100_<name>` (a name that already starts with a number gets the new one)."""
    if not 1 <= value <= MAX:
        raise MediaOrderError(f"a sorszám ({value}) a megengedett tartományon kívül esik")
    return f"{value:0{WIDTH}d}_{PREFIX.sub('', name)}"
