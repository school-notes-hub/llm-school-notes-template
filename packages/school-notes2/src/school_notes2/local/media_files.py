"""The learner's own copies of the episodes and the videos, in the teaching order (owner,
2026-10-14: "legyen biztosítva egy sorrend a videókban, podcastekben, ahogy sorban vették a
tananyagot"): the order number in the file name (`wiki.media_order`) and the standard tags.
`sn publish` runs it after the site (`sync`); `sn podcast` uses `podcast_bytes` for the Drive
copy of the episode it releases and `site_tags` for the site's MP3.

**Where.** The episode's Drive copy, `Podcast/<Tantárgy> – 00100_<lapcím>.mp3`; the finished
video and its sound, `~/jegyzet/video-kesz/<t>/<tantárgy>/00100_<lap>-<n>.mp4` and `.opus`. A
video file without a number is always `video.py`'s fresh output (it writes `<lap>-<n>.mp4`): it
wins over a numbered copy, which is removed only after the fresh one stands in its place.

**Tags** (ffmpeg, `-c copy`: no re-encoding; `-map_metadata -1` and `bitexact`, so the same input
and tags give the same bytes, and tagging a tagged file again changes nothing): `title` – the
episode's title, or the video's topic page title with `(n. rész)` when the page has more than one
video; `album` – `School Notes – <Tantárgy>`; `artist`, `album_artist` – `School Notes`; `genre` –
`Podcast` or `Oktatóvideó`; `comment` (MP4 also `description`) – the stored description: an
episode's `summary` (the podcast writer's sentence, in the receipt), a video's
`docs/evidence/video/<tantárgy>/<videó>/leiras.txt` (the video writer's 1–2 sentences, copied by
`video.py --vegleges`); `track` – the stored order number itself (00150 → 150): stable and
increasing in the teaching order, so a player sorts right and nothing is uploaded again when a
later item comes (MP4's track field holds at most 65535: above it the MP4 has no track). The
site's MP3 gets every tag but `track` when `sn podcast` mixes it (`site_tags`; its bytes are what
the receipt names), the Drive copy all of them. A missing description stays empty, and one line
names the items that lack it. A video receipt's SHA-256 is that of the untagged render. No LLM
call."""

import filecmp
import os
import re
import subprocess
import tempfile
from pathlib import Path

from ..state import safefs
from ..state.errors import SnError, Transient
from ..wiki import frontmatter, generate, media_order
from ..wiki import podcast as wiki_podcast

VIDEO_DONE = Path.home() / "jegyzet" / "video-kesz"
ARTIST = "School Notes"
VIDEOS = "docs/evidence/video"
DESCRIPTION = "leiras.txt"
PODCAST_GENRE = "Podcast"
VIDEO_GENRE = "Oktatóvideó"
MP4_TRACK_MAX = 65535


def album(subject_name: str) -> str:
    return f"{ARTIST} – {subject_name}"


def _one_line(text: str) -> str:
    return " ".join(str(text or "").split())


def site_tags(subject_name: str, title: str, summary: str) -> dict[str, str]:
    """The tags of an episode's MP3 that never change with the order (the site's copy)."""
    return {"title": title, "album": album(subject_name), "artist": ARTIST, "album_artist": ARTIST,
            "genre": PODCAST_GENRE, "comment": _one_line(summary)}


def _with_track(tags: dict, number: int | None) -> dict:
    return {**tags, "track": str(number)} if number is not None else dict(tags)


# --- what there is, in the teaching order ------------------------------------------------------

def podcast_items(repo: Path, numbers: dict | None = None) -> list[dict]:
    """Every released episode in the teaching order (`wiki.podcast.grouped`), with its order
    number (None: its page has none), Drive name and tags."""
    numbers = media_order.load(repo) if numbers is None else numbers
    items = []
    for slug, sections in wiki_podcast.grouped(repo, wiki_podcast.records(repo)):
        subject = wiki_podcast.subject_name(repo, slug)
        for _, episodes in sections:
            for r in episodes:
                stem = r["page"].rsplit("/", 1)[1][:-3]
                number = numbers.get(slug, {}).get(stem)
                items.append({"ident": f"{slug}/{stem}", "subject": slug, "record": r, "number": number,
                              "subject_name": subject, "page_title": wiki_podcast.page_title(repo, r["page"]),
                              "tags": _with_track(site_tags(subject, r["title"], r.get("summary", "")), number)})
    names = wiki_podcast.drive_names({i["ident"]: (i["subject_name"], i["page_title"], i["record"]["first_released"],
                                                   i["number"]) for i in items if i["number"] is not None})
    for item in items:
        item["name"] = names.get(item["ident"])
    return items


def _video_receipts(repo: Path) -> dict[str, list[str]]:
    """{subject: [video]} from the receipts `docs/evidence/video/<tantárgy>/<lap>-<n>.json`."""
    out: dict[str, list[str]] = {}
    for rel in safefs.glob(repo, VIDEOS, f"{VIDEOS}/*/*.json"):
        _, _, _, slug, name = rel.split("/")
        out.setdefault(slug, []).append(name[:-5])
    return out


def _in_order(repo: Path, slug: str, videos: list[str], known: bool) -> list[str]:
    """By the page's place in the subject index, then the part as a number, then the name."""
    place = {stem: i for i, stem in enumerate(media_order.teaching_pages(repo, slug))} if known else {}
    return sorted(videos, key=lambda v: (place.get(media_order.video_page(v), len(place)), media_order.video_page(v),
                                         media_order.video_part(v), v))


def _video_title(repo: Path, slug: str, video: str, parts: int) -> str:
    page = media_order.video_page(video)
    try:
        meta = frontmatter.split(safefs.read_text(repo, f"wiki/{slug}/{page}.md")).meta
    except (OSError, ValueError):
        meta = {}
    title = str(meta.get("title") or page)
    return f"{title} ({media_order.video_part(video)}. rész)" if parts > 1 else title


def _video_tags(repo: Path, slug: str, subject: str, video: str, parts: int) -> dict:
    desc = f"{VIDEOS}/{slug}/{video}/{DESCRIPTION}"
    return {"title": _video_title(repo, slug, video, parts), "album": album(subject), "artist": ARTIST,
            "album_artist": ARTIST, "genre": VIDEO_GENRE,
            "comment": _one_line(safefs.read_text(repo, desc)) if safefs.is_file(repo, desc) else ""}


def video_items(repo: Path, numbers: dict | None = None) -> list[dict]:
    """Every finished video in the teaching order (subjects as on the home page), with its order
    number (its page's) and tags."""
    numbers = media_order.load(repo) if numbers is None else numbers
    receipts = _video_receipts(repo)
    known = generate.subject_order(repo)
    items = []
    for slug in known + sorted(set(receipts) - set(known)):
        videos = receipts.get(slug, [])
        pages = [media_order.video_page(v) for v in videos]
        subject = wiki_podcast.subject_name(repo, slug) if videos else ""
        for video in _in_order(repo, slug, videos, slug in known):
            page = media_order.video_page(video)
            number = numbers.get(slug, {}).get(page)
            items.append({"ident": f"{slug}/{video}", "subject": slug, "video": video, "number": number,
                          "tags": _with_track(_video_tags(repo, slug, subject, video, pages.count(page)), number)})
    return items


def missing_descriptions(items: list[dict]) -> list[str]:
    return [i["ident"] for i in items if not i["tags"].get("comment")]


# --- tagging -----------------------------------------------------------------------------------

def ffmpeg_args(src: Path, dst: Path, tags: dict) -> list[str]:
    """Copy every stream, drop every old tag, write these (`bitexact`: byte-stable)."""
    ext = dst.suffix.lower()
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-map", "0", "-c", "copy",
            "-map_metadata", "-1", "-map_chapters", "-1", "-fflags", "+bitexact", "-flags:a", "+bitexact"]
    values = {k: v for k, v in tags.items() if v}
    if ext == ".mp4":
        args += ["-flags:v", "+bitexact", "-movflags", "+faststart"]
        if values.get("comment"):
            values["description"] = values["comment"]
        if int(values.get("track") or 0) > MP4_TRACK_MAX:
            values.pop("track")
    if ext == ".mp3":
        args += ["-id3v2_version", "3", "-write_id3v1", "0"]
    for key in sorted(values):
        args += ["-metadata", f"{key}={values[key]}"]
    return args + ["-f", {".mp3": "mp3", ".mp4": "mp4", ".opus": "opus"}[ext], str(dst)]


def tag(src: Path, dst: Path, tags: dict) -> None:
    """Write the tagged copy; an ffmpeg failure is `Transient` (a re-run may pass)."""
    try:
        proc = subprocess.run(ffmpeg_args(src, dst, tags), capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Transient(f"ffmpeg: {src.name}: {exc}", todo="nézd meg az ffmpeg-et, azután futtasd újra") from None
    if proc.returncode != 0:
        raise Transient(f"ffmpeg: {src.name}: {proc.stderr.strip()[-300:]}",
                        todo="nézd meg a fájlt és az ffmpeg-et, azután futtasd újra")


def podcast_bytes(repo: Path, item: dict) -> bytes:
    """The Drive copy of an episode: the site's MP3 with every tag (the track too)."""
    with tempfile.TemporaryDirectory(prefix="sn-tag-") as tmp:
        dst = Path(tmp) / "adas.mp3"
        tag(repo / item["record"]["asset"], dst, item["tags"])
        return dst.read_bytes()


# --- the videos in video-kesz ------------------------------------------------------------------

def _copies(folder: Path, video: str, ext: str) -> tuple[Path | None, list[Path]]:
    """(the unnumbered file – `video.py`'s fresh output –, the numbered copies)."""
    if not folder.is_dir():
        return None, []
    fresh = folder / f"{video}{ext}"
    pattern = re.compile(r"^\d{5}_" + re.escape(video) + re.escape(ext) + "$")
    numbered = sorted(p for p in folder.iterdir() if p.is_file() and pattern.match(p.name))
    return (fresh if fresh.is_file() else None), numbered


def _source(fresh: Path | None, numbered: list[Path], dst: Path) -> Path | str:
    """The file to tag: the fresh one; else the target (an interrupted run); else the one copy."""
    if fresh is not None:
        return fresh
    if dst in numbered:
        return dst
    if len(numbered) == 1:
        return numbered[0]
    if not numbered:
        return "absent"
    return f"{len(numbered)} számozott példány ({', '.join(p.name for p in numbered)}) – hagyj meg egyet"


def sync_video_file(folder: Path, item: dict, ext: str) -> str:
    """One file of a video in place: `absent`, `unchanged`, `tagged`, `renamed`, or a problem.
    The fresh unnumbered file wins; the other copies go only after the target stands in place
    (an interrupted run leaves the target and an old copy: the target wins the next time)."""
    fresh, numbered = _copies(folder, item["video"], ext)
    dst = folder / (media_order.numbered(item["number"], item["video"]) + ext)
    src = _source(fresh, numbered, dst)
    if isinstance(src, str):
        return src
    tmp = folder / f".{dst.stem}.sn-tmp{ext}"
    try:
        tag(src, tmp, item["tags"])
        if src == dst and filecmp.cmp(src, tmp, shallow=False):
            state = "unchanged"
        else:
            os.replace(tmp, dst)
            state = "tagged" if src == dst else "renamed"
    finally:
        tmp.unlink(missing_ok=True)
    for old in [p for p in [fresh, *numbered] if p is not None and p != dst]:
        old.unlink(missing_ok=True)
    return state


def sync_videos(repo: Path, learner: str, out, base: Path | None = None, numbers: dict | None = None) -> list[str]:
    """Rename and tag the finished videos (and their `.opus`) in `video-kesz`; returns the
    problems, one line each."""
    base = VIDEO_DONE if base is None else base
    problems, counts = [], {"renamed": 0, "tagged": 0, "unchanged": 0}
    for item in video_items(repo, numbers):
        if item["number"] is None:
            problems.append(f"{item['ident']}: a videó lapjának nincs sorszáma (nem áll a tantárgyi index egyik "
                            "fejezetében sem)")
            continue
        for ext in (".mp4", ".opus"):
            try:
                state = sync_video_file(base / learner / item["subject"], item, ext)
            except (SnError, OSError) as exc:
                state = f"hiba: {exc}"
            if state in counts:
                counts[state] += 1
            elif state != "absent":
                problems.append(f"{item['ident']}{ext}: {state}")
    out(f"videók: {counts['renamed']} átnevezve, {counts['tagged']} címkézve, {counts['unchanged']} változatlan")
    return problems


# --- sn publish's step ---------------------------------------------------------------------------

def sync_podcasts(local, items: list[dict], out) -> list[str]:
    """The Drive copies: each episode tagged and uploaded one by one (one MP3 in memory)."""
    from ..drive import upload as drive_upload
    problems = [f"{i['ident']}: az adás lapjának nincs sorszáma – a Drive-fájl neve marad" for i in items
                if i["name"] is None]
    wanted = {i["ident"]: (i["name"], lambda i=i: podcast_bytes(local.repo, i)) for i in items if i["name"]}
    if not wanted:
        return problems
    states = drive_upload.sync(local.drive(), local.student.drive_root, wanted)
    tally = {"created": 0, "updated": 0, "unchanged": 0}
    for ident, state in states:
        if state in tally:
            tally[state] += 1
        else:
            problems.append(f"{ident}: {state}")
    out(f"Drive {drive_upload.PODCAST}/: {tally['created']} új, {tally['updated']} frissítve, "
        f"{tally['unchanged']} változatlan")
    return problems


def _stored(repo: Path) -> tuple[dict, list[str]]:
    """The stored numbers, and a problem when they are not those of the current order."""
    numbers, _ = media_order.compute(repo)
    stored = media_order.load(repo)
    if {s: p for s, p in numbers.items() if p} != {s: p for s, p in stored.items() if p}:
        return stored, [f"{media_order.STORE} nem friss (a lapok sorrendje változott az utolsó sn close óta); a "
                        "tárolt számokkal nevezem el – futtasd az sn close-t, és add ki újra"]
    return stored, []


def sync(local, out, base: Path | None = None) -> int:
    """`sn publish`'s step after the site: the Drive copies of the episodes and the finished
    videos get the order number in their name and the tags. 0, or 1 with the problems listed
    (never an exception: a Drive, ffmpeg or file error is a problem line)."""
    repo, problems = local.repo, []
    try:
        stored, problems = _stored(repo)
        items = podcast_items(repo, stored)
        try:
            problems += sync_podcasts(local, items, out)
        except (SnError, OSError) as exc:
            problems.append(f"Drive: {exc}")
        videos = video_items(repo, stored)
        problems += sync_videos(repo, local.name, out, base, stored)
        lacking = missing_descriptions(items) + missing_descriptions(videos)
        if lacking:
            out(f"leírás nélkül ({len(lacking)}): {', '.join(lacking)}")
    except (SnError, OSError, media_order.MediaOrderError) as exc:
        problems.append(f"sorszám és fájlok: {exc}")
    for line in problems:
        out(f"  {line}")
    return 1 if problems else 0
