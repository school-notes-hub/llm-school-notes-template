"""The learner's own copies of the episodes and the videos, in the teaching order (owner,
2026-10-14: "legyen biztosítva egy sorrend a videókban, podcastekben, ahogy sorban vették a
tananyagot"): the order number in the file name (`wiki.media_order`) and the standard tags.
`sn publish` runs it after the site (`sync`); `sn podcast` uses `podcast_bytes` for the Drive
copy of the episode it releases.

**Where.** The episode's Drive copy, `Podcast/<Tantárgy> – 00100_<lapcím>.mp3`; the finished
video and its sound, `~/jegyzet/video-kesz/<t>/<tantárgy>/00100_<lap>-<n>.mp4` and `.opus`. The
site's MP3 (`wiki/assets/…`) is not touched: its bytes are what the receipt names (the public
gate's rights evidence), and the site shows the order itself (`wiki.podcast`).

**Tags** (ffmpeg, `-c copy`: no re-encoding; `-map_metadata -1` and `bitexact`, so the same input
and tags give the same bytes, and tagging a tagged file again changes nothing): `title` – the
topic page's title (an episode) or the video's own title, with `(n. rész)` when the page has
more than one video; `album` – `School Notes – <Tantárgy>`; `artist`, `album_artist` – `School
Notes`; `genre` – `Podcast` or `Oktatóvideó`; `track` – the place in the subject among its
episodes (videos) in the teaching order, 1, 2, 3 (never the gapped file-name number); `comment`
(MP4 also `description`) – the stored description: an episode's `summary` (the podcast writer's
one sentence, in the receipt), a video's `docs/evidence/video/<tantárgy>/<videó>/leiras.txt`.
A missing description stays empty, and one line names the items that lack it. No LLM call."""

import os
import re
import subprocess
import tempfile
from pathlib import Path

from ..state import safefs
from ..wiki import frontmatter, generate, media_order
from ..wiki import podcast as wiki_podcast

VIDEO_DONE = Path.home() / "jegyzet" / "video-kesz"
ARTIST = "School Notes"
VIDEOS = "docs/evidence/video"
DESCRIPTION = "leiras.txt"
PODCAST_GENRE = "Podcast"
VIDEO_GENRE = "Oktatóvideó"


def album(subject_name: str) -> str:
    return f"{ARTIST} – {subject_name}"


def _page_meta(repo: Path, rel: str) -> dict:
    try:
        return frontmatter.split(safefs.read_text(repo, rel)).meta
    except (OSError, ValueError):
        return {}


def podcast_items(repo: Path, numbers: dict | None = None) -> list[dict]:
    """Every released episode in the teaching order (`wiki.podcast.grouped`), with its order
    number (None: its page has none), Drive name and tags."""
    numbers = media_order.load(repo) if numbers is None else numbers
    found = wiki_podcast.records(repo)
    items = []
    for slug, sections in wiki_podcast.grouped(repo, found):
        subject = wiki_podcast.subject_name(repo, slug)
        track = 0
        for _, episodes in sections:
            for r in episodes:
                track += 1
                stem = r["page"].rsplit("/", 1)[1][:-3]
                title = wiki_podcast.page_title(repo, r["page"])
                items.append({"ident": f"{slug}/{stem}", "subject": slug, "record": r, "first": r["first_released"],
                              "number": numbers.get(slug, {}).get(stem), "subject_name": subject,
                              "page_title": title,
                              "tags": {"title": title, "album": album(subject), "artist": ARTIST,
                                       "album_artist": ARTIST, "genre": PODCAST_GENRE, "track": str(track),
                                       "comment": " ".join(str(r.get("summary") or "").split())}})
    wanted = {i["ident"]: (i["subject_name"], i["page_title"], i["first"], i["number"])
              for i in items if i["number"] is not None}
    names = wiki_podcast.drive_names(wanted)
    for item in items:
        item["name"] = names.get(item["ident"])
    return items


def video_items(repo: Path, numbers: dict | None = None) -> list[dict]:
    """Every finished video (its receipt `docs/evidence/video/<tantárgy>/<lap>-<n>.json`) in the
    teaching order: subject as on the home page, then its page's place, then the part."""
    numbers = media_order.load(repo) if numbers is None else numbers
    by_subject: dict[str, list[tuple[str, dict]]] = {}
    for rel in safefs.glob(repo, VIDEOS, f"{VIDEOS}/*/*.json"):
        _, _, _, slug, name = rel.split("/")
        try:
            receipt = safefs.read_json(repo, rel, {}) or {}
        except (OSError, ValueError):
            receipt = {}
        by_subject.setdefault(slug, []).append((name[:-5], receipt))
    known = generate.subject_order(repo)
    items = []
    for slug in known + sorted(set(by_subject) - set(known)):
        videos = by_subject.get(slug)
        if not videos:
            continue
        order = media_order.teaching_pages(repo, slug) if slug in known else []
        place = {stem: i for i, stem in enumerate(order)}

        def key(v, place=place):
            page, part = media_order.video_page(v[0]), _part(v[0])
            return (place.get(page, len(place)), page, part, v[0])

        videos.sort(key=key)
        parts: dict[str, int] = {}
        for video, _ in videos:
            parts[media_order.video_page(video)] = parts.get(media_order.video_page(video), 0) + 1
        subject = wiki_podcast.subject_name(repo, slug)
        track = 0
        for video, receipt in videos:
            page = media_order.video_page(video)
            number = numbers.get(slug, {}).get(page)
            if number is not None:
                track += 1
            rel_page = f"wiki/{slug}/{page}.md"
            title = str((receipt.get("nyitozaro") or {}).get("cim") or _page_meta(repo, rel_page).get("title") or page)
            if parts[page] > 1:
                title += f" ({_part(video)}. rész)"
            desc_rel = f"{VIDEOS}/{slug}/{video}/{DESCRIPTION}"
            description = " ".join(safefs.read_text(repo, desc_rel).split()) if safefs.is_file(repo, desc_rel) else ""
            items.append({"ident": f"{slug}/{video}", "subject": slug, "video": video, "number": number,
                          "tags": {"title": title, "album": album(subject), "artist": ARTIST, "album_artist": ARTIST,
                                   "genre": VIDEO_GENRE, "track": str(track) if number is not None else "",
                                   "comment": description}})
    return items


def _part(video: str) -> int:
    found = re.search(r"-(\d+)$", video)
    return int(found[1]) if found else 0


def ffmpeg_args(src: Path, dst: Path, tags: dict) -> list[str]:
    """Copy every stream, drop every old tag, write these (`bitexact`: byte-stable)."""
    ext = dst.suffix.lower()
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-map", "0", "-c", "copy",
            "-map_metadata", "-1", "-map_chapters", "-1", "-fflags", "+bitexact", "-flags:a", "+bitexact"]
    if ext == ".mp4":
        args += ["-flags:v", "+bitexact", "-movflags", "+faststart"]
    if ext == ".mp3":
        args += ["-id3v2_version", "3", "-write_id3v1", "0"]
    values = dict(tags)
    if ext == ".mp4" and values.get("comment"):
        values["description"] = values["comment"]
    for key in sorted(values):
        if values[key]:
            args += ["-metadata", f"{key}={values[key]}"]
    return args + ["-f", {".mp3": "mp3", ".mp4": "mp4", ".opus": "opus"}[ext], str(dst)]


def tag(src: Path, dst: Path, tags: dict) -> None:
    proc = subprocess.run(ffmpeg_args(src, dst, tags), capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg: {src.name}: {proc.stderr.strip()[-300:]}")


def podcast_bytes(repo: Path, item: dict) -> bytes:
    """The Drive copy of an episode: the site's MP3 with the tags."""
    with tempfile.TemporaryDirectory(prefix="sn-tag-") as tmp:
        dst = Path(tmp) / "adas.mp3"
        tag(repo / item["record"]["asset"], dst, item["tags"])
        return dst.read_bytes()


def _existing(folder: Path, stem: str, ext: str) -> list[Path]:
    if not folder.is_dir():
        return []
    pattern = re.compile(r"^(?:\d{5}_)?" + re.escape(stem) + re.escape(ext) + "$")
    return sorted(p for p in folder.iterdir() if p.is_file() and pattern.match(p.name))


def sync_videos(repo: Path, learner: str, out, base: Path | None = None, numbers: dict | None = None) -> list[str]:
    """Rename and tag the finished videos (and their `.opus`) in `video-kesz`; returns the
    problems (a video with no order number, two copies of one video)."""
    base = VIDEO_DONE if base is None else base
    problems, counts = [], {"átnevezve": 0, "címkézve": 0, "változatlan": 0}
    for item in video_items(repo, numbers):
        folder = base / learner / item["subject"]
        if item["number"] is None:
            problems.append(f"{item['ident']}: a videó lapjának nincs sorszáma (nem áll a tantárgyi index egyik "
                            "fejezetében sem)")
            continue
        for ext in (".mp4", ".opus"):
            found = _existing(folder, item["video"], ext)
            if not found:
                continue
            if len(found) > 1:
                problems.append(f"{item['ident']}{ext}: {len(found)} példány a {folder} mappában "
                                f"({', '.join(p.name for p in found)}) – hagyj meg egyet")
                continue
            src = found[0]
            dst = folder / (media_order.numbered(item["number"], item["video"]) + ext)
            tmp = folder / f".{dst.stem}.sn-tmp{ext}"
            try:
                tag(src, tmp, item["tags"])
                if src == dst and src.read_bytes() == tmp.read_bytes():
                    counts["változatlan"] += 1
                    continue
                os.replace(tmp, dst)
                if src != dst:
                    src.unlink()
                    counts["átnevezve"] += 1
                else:
                    counts["címkézve"] += 1
            finally:
                tmp.unlink(missing_ok=True)
    out("videók: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
    return problems


def missing_descriptions(items: list[dict]) -> list[str]:
    return [i["ident"] for i in items if not i["tags"].get("comment")]


def sync(local, out, base: Path | None = None) -> int:
    """`sn publish`'s step after the site: the Drive copies of the episodes and the finished
    videos get the order number in their name and the tags. 0, or 1 with the problems listed."""
    from ..drive import upload as drive_upload
    from ..state.errors import SnError
    repo = local.repo
    try:
        numbers, _ = media_order.compute(repo)
    except media_order.MediaOrderError as exc:
        out(f"Hiba: sorszám: {exc}")
        return 1
    stored = media_order.load(repo)
    problems = []
    if {s: p for s, p in numbers.items() if p} != {s: p for s, p in stored.items() if p}:
        problems.append(f"{media_order.STORE} nem friss (a lapok sorrendje változott az utolsó sn close óta); "
                        "a tárolt számokkal nevezem el – futtasd az sn close-t, és add ki újra")
    items = podcast_items(repo, stored)
    wanted = {}
    for item in items:
        if item["name"] is None:
            problems.append(f"{item['ident']}: az adás lapjának nincs sorszáma – a Drive-fájl neve marad")
        else:
            wanted[item["ident"]] = (item["name"], podcast_bytes(repo, item))
    if wanted:
        try:
            states = drive_upload.sync(local.drive(), local.student.drive_root, wanted)
        except SnError as exc:
            out(f"Hiba: Drive: {exc}")
            return 1
        tally: dict[str, int] = {}
        for ident, state in states:
            if state in ("created", "updated", "unchanged"):
                tally[state] = tally.get(state, 0) + 1
            else:
                problems.append(f"{ident}: {state}")
        names = {"created": "új", "updated": "frissítve", "unchanged": "változatlan"}
        out(f"Drive {drive_upload.PODCAST}/: " + ", ".join(f"{n} {names[s]}" for s, n in sorted(tally.items())))
    videos = video_items(repo, stored)
    problems += sync_videos(repo, local.name, out, base, stored)
    lacking = missing_descriptions(items) + missing_descriptions(videos)
    if lacking:
        out(f"leírás nélkül ({len(lacking)}): {', '.join(lacking)}")
    for line in problems:
        out(f"  {line}")
    return 1 if problems else 0
