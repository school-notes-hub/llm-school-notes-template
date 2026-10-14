"""The teaching order of the episodes and videos (owner, 2026-10-14: "legyen biztosítva egy sorrend
a videókban, podcastekben, ahogy sorban vették a tananyagot. A podcast oldalon is csak oda van
hányva."): the Podcast page by subject and chapter in the subject index's order, counted 1, 2, 3;
the stored, gapped order number in the file names (five digits, step 100, a page inserted between
two gets the middle, renumbering only when no number is free); the tags of the learner's copies."""

import json
import shutil
import subprocess

import pytest

from school_notes2.drive import upload
from school_notes2.drive.client import FOLDER, DriveClient
from school_notes2.local import guard, media_files, tool_writes
from school_notes2.state import safefs
from school_notes2.wiki import media_order
from school_notes2.wiki import podcast as wiki_podcast
from tests.podcast.conftest import FakeDrive, git

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg missing")


# --- the number: assign ----------------------------------------------------------------------

def test_first_numbers_are_hundreds_in_the_teaching_order():
    assert media_order.assign(["a", "b", "c"], {}) == ({"a": 100, "b": 200, "c": 300}, False)


def test_a_page_between_two_gets_the_middle_and_nothing_else_moves():
    numbers, whole = media_order.assign(["a", "x", "b", "c"], {"a": 100, "b": 200, "c": 300})
    assert numbers == {"a": 100, "x": 150, "b": 200, "c": 300} and not whole
    numbers, _ = media_order.assign(["a", "x", "y", "z", "b"], {"a": 100, "b": 200})
    assert numbers == {"a": 100, "x": 125, "y": 150, "z": 175, "b": 200}
    assert media_order.assign(["x", "a"], {"a": 100})[0] == {"x": 50, "a": 100}       # before the first
    assert media_order.assign(["a", "b", "x"], {"a": 100, "b": 200})[0]["x"] == 300  # appended


def test_a_moved_page_gets_a_new_number_the_rest_keep_theirs():
    numbers, whole = media_order.assign(["a", "c", "b", "d"], {"a": 100, "b": 200, "c": 300, "d": 400})
    assert not whole and numbers["a"] == 100 and numbers["d"] == 400
    assert sum(numbers[k] != v for k, v in {"a": 100, "b": 200, "c": 300, "d": 400}.items()) == 1
    assert list(numbers.values()) == sorted(numbers.values())


def test_no_free_number_renumbers_the_whole_subject_and_says_so():
    numbers, whole = media_order.assign(["a", "x", "b"], {"a": 100, "b": 101})
    assert whole and numbers == {"a": 100, "x": 200, "b": 300}


def test_backwards_generation_never_needs_a_number_because_every_page_has_one():
    order = [f"p{i}" for i in range(12)]
    first, _ = media_order.assign(order, {})
    assert media_order.assign(order, first) == (first, False)


def test_the_end_squeezes_below_the_top_and_beyond_it_the_tool_stops():
    assert media_order.assign(["a", "b"], {"a": 99850}) == ({"a": 99850, "b": 99875}, False)
    assert media_order.assign(["a", "b"], {"a": 99900}) == ({"a": 100, "b": 200}, True)
    with pytest.raises(media_order.MediaOrderError, match="nem fér el"):
        media_order.renumbered([f"p{i}" for i in range(1000)])
    assert len(media_order.renumbered([f"p{i}" for i in range(999)])) == 999


def test_assign_is_total_strictly_increasing_and_deterministic():
    order = [f"p{i}" for i in range(40)]
    stored = {f"p{i}": (i * 37) % 4000 + 1 for i in range(0, 40, 3)}
    one, two = media_order.assign(order, stored), media_order.assign(list(order), dict(stored))
    assert one == two and set(one[0]) == set(order)
    values = [one[0][p] for p in order]
    assert values == sorted(set(values)) and all(1 <= v <= media_order.MAX for v in values)


def test_numbered_name_has_five_digits_and_replaces_an_old_number():
    assert media_order.numbered(150, "halmazok-1") == "00150_halmazok-1"
    assert media_order.numbered(200, "00150_halmazok-1") == "00200_halmazok-1"
    assert media_order.video_page("halmazok-12") == "halmazok"
    with pytest.raises(media_order.MediaOrderError):
        media_order.numbered(100000, "x")


# --- a learner repo with two subjects -------------------------------------------------------

SUBJECTS = {"subjects": {"tori": {"name": "Történelem", "emoji": "🏛️"}, "mate": {"name": "Matematika"}}}


def index(chapters: list[tuple[str, str]]) -> str:
    lines = "".join(f"  - {{id: {i}, title: '9. évfolyam: {t}'}}\n" for i, t in chapters)
    return f"---\ndescription: x\nchapters:\n{lines}---\n\n# Tárgy\n"


def topic(title: str, chapter: str, order: int) -> str:
    return f"---\ntype: topic\ntitle: {title}\ndescription: {title} röviden.\nchapter: {chapter}\norder: {order}\n---\n# {title}\n"


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    files = {
        "tools/subjects.json": json.dumps(SUBJECTS),
        "wiki/index.md": "# Jegyzetek\n",
        # chapters listed in the order the class started them; file names and release days disagree
        "wiki/tori/index.md": index([("kelet", "Ókori Kelet"), ("hellasz", "Hellász")]),
        "wiki/tori/zz-egyiptom.md": topic("Egyiptom", "kelet", 20),
        "wiki/tori/aa-mezopotamia.md": topic("Mezopotámia", "kelet", 10),
        "wiki/tori/athen.md": topic("Athén", "hellasz", 20),
        "wiki/tori/kreta.md": topic("Kréta", "hellasz", 10),
        "wiki/tori/osszefoglalo.md": topic("Összefoglaló", "kelet", 90).replace("type: topic", "type: chapter-summary"),
        "wiki/mate/index.md": index([("halmaz", "Halmazok")]),
        "wiki/mate/halmazok.md": topic("Halmazok", "halmaz", 10),
    }
    for rel, text in files.items():
        safefs.write_text(repo, rel, text)
    return repo


def record(subject: str, stem: str, day: str, title: str) -> dict:
    return {"subject": subject, "page": f"wiki/{subject}/{stem}.md", "title": title, "summary": f"{title}: összefoglaló.",
            "asset": f"wiki/assets/{subject}/podcast/{stem}.mp3", "duration_s": 200.0, "first_released": day,
            "speakers": [{"name": "Dani", "role": "host", "voice": "x"}, {"name": "Zsófi", "role": "guest", "voice": "y"}]}


def test_numbers_follow_the_subject_index_order_and_are_stored_byte_stably(tmp_path):
    repo = make_repo(tmp_path)
    assert media_order.teaching_pages(repo, "tori") == ["aa-mezopotamia", "zz-egyiptom", "osszefoglalo", "kreta", "athen"]
    changed, lines = media_order.update(repo)
    first = safefs.read_text(repo, media_order.STORE)
    assert changed and lines == []
    assert media_order.load(repo)["tori"] == {"aa-mezopotamia": 100, "zz-egyiptom": 200, "osszefoglalo": 300,
                                              "kreta": 400, "athen": 500}
    assert media_order.update(repo) == (False, []) and safefs.read_text(repo, media_order.STORE) == first
    # a page inserted into the first chapter: the middle, nothing else changes
    safefs.write_text(repo, "wiki/tori/nilus.md", topic("Nílus", "kelet", 15))
    media_order.update(repo)
    assert media_order.load(repo)["tori"]["nilus"] == 150
    assert media_order.load(repo)["tori"]["athen"] == 500


def test_a_renumbering_names_the_files_that_change(tmp_path):
    repo = make_repo(tmp_path)
    safefs.write_text(repo, media_order.STORE, json.dumps({"subjects": {"tori": {
        "aa-mezopotamia": 100, "zz-egyiptom": 101, "osszefoglalo": 300, "kreta": 400, "athen": 500}}}))
    safefs.write_text(repo, "wiki/tori/nilus.md", topic("Nílus", "kelet", 15))
    safefs.write_json(repo, "docs/evidence/podcast/tori/athen.json", {})
    _, lines = media_order.update(repo)
    assert lines == ["sorszám: tori újraszámozva 100-as lépéssel (nem volt szabad szám): 1 adás- vagy videófájl "
                     "neve változik a következő sn publish-kor"]


def test_podcast_page_is_by_subject_and_chapter_in_the_teaching_order_counted_per_subject(tmp_path):
    repo = make_repo(tmp_path)
    found = [record("tori", "athen", "2026-10-01", "Athén adás"), record("tori", "aa-mezopotamia", "2026-10-09", "Mezo adás"),
             record("tori", "kreta", "2026-10-09", "Kréta adás"), record("tori", "zz-egyiptom", "2026-10-02", "Egyiptom adás"),
             record("mate", "halmazok", "2026-10-05", "Halmaz adás"), record("tori", "elveszett", "2026-10-03", "Régi adás")]
    text = wiki_podcast.list_block(repo, found)
    heads = [ln for ln in text.splitlines() if ln.startswith("#")]
    assert heads == ["## 🏛️ Történelem", "### 📘 Ókori Kelet", "#### 1. Mezo adás", "#### 2. Egyiptom adás",
                     "### 📘 Hellász", "#### 3. Kréta adás", "#### 4. Athén adás", "### 📘 Egyéb", "#### 5. Régi adás",
                     "## Matematika", "### 📘 Halmazok", "#### 1. Halmaz adás"]
    assert wiki_podcast.list_block(repo, list(reversed(found))) == text           # input order does not matter
    assert "00" not in "".join(heads)                                              # no gapped number on the site


# --- the learner's copies: tags, video names, Drive -----------------------------------------

def probe_tags(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags:stream_tags", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    value = json.loads(out)
    return {**value.get("format", {}).get("tags", {}), **(value.get("streams") or [{}])[0].get("tags", {})}


@pytest.fixture
def media(tmp_path):
    folder = tmp_path / "media"
    folder.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=5:duration=1", "-f", "lavfi",
                    "-i", "sine=duration=1", "-c:v", "libx264", "-c:a", "aac", "-shortest", "-metadata", "title=régi",
                    str(folder / "v.mp4")], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=1", "-c:a", "libopus",
                    str(folder / "v.opus")], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=1", "-c:a", "libmp3lame",
                    "-metadata", "title=régi", str(folder / "p.mp3")], check=True)
    return folder


@needs_ffmpeg
def test_tags_are_the_standard_ones_without_reencoding_and_byte_stable(media):
    tags = {"title": "Forgatónyomaték", "album": "School Notes – Statika", "artist": "School Notes",
            "album_artist": "School Notes", "genre": "Oktatóvideó", "track": "3", "comment": "Rövid leírás."}
    for name in ("v.mp4", "v.opus", "p.mp3"):
        src = media / name
        one, two = media / f"1-{name}", media / f"2-{name}"
        media_files.tag(src, one, tags)
        media_files.tag(one, two, tags)                       # tagging a tagged file again: same bytes
        assert one.read_bytes() == two.read_bytes()
        found = probe_tags(one)
        assert {k: found.get(k) or found.get(k.upper()) for k in ("title", "album", "genre", "track")} == {
            "title": "Forgatónyomaték", "album": "School Notes – Statika", "genre": "Oktatóvideó", "track": "3"}
        assert "régi" not in json.dumps(found, ensure_ascii=False)
    assert probe_tags(media / "1-v.mp4")["description"] == "Rövid leírás."
    codecs = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name", "-of", "csv=p=0",
                             str(media / "1-v.mp4")], capture_output=True, text=True).stdout.split()
    assert codecs == ["h264", "aac"]


@needs_ffmpeg
def test_videos_get_the_number_and_tags_in_video_kesz_and_a_rerun_changes_nothing(tmp_path, media):
    repo = make_repo(tmp_path)
    media_order.update(repo)
    for video in ("athen-1", "athen-2", "aa-mezopotamia-1"):
        safefs.write_json(repo, f"docs/evidence/video/tori/{video}.json", {"nyitozaro": {"cim": f"{video} cím"}})
    safefs.write_text(repo, "docs/evidence/video/tori/athen-2/leiras.txt", "Athén második része.\n")
    base = tmp_path / "kesz"
    folder = base / "barna" / "tori"
    folder.mkdir(parents=True)
    for video in ("athen-1", "athen-2", "aa-mezopotamia-1"):
        shutil.copy(media / "v.mp4", folder / f"{video}.mp4")
    shutil.copy(media / "v.opus", folder / "athen-2.opus")
    lines = []
    assert media_files.sync_videos(repo, "barna", lines.append, base) == []
    assert sorted(p.name for p in folder.iterdir()) == ["00100_aa-mezopotamia-1.mp4", "00500_athen-1.mp4",
                                                        "00500_athen-2.mp4", "00500_athen-2.opus"]
    tags = probe_tags(folder / "00500_athen-2.mp4")
    assert tags["title"] == "Athén (2. rész)" and tags["track"] == "500" and tags["genre"] == "Oktatóvideó"
    assert tags["comment"] == "Athén második része." and tags["album"] == "School Notes – Történelem"
    assert probe_tags(folder / "00100_aa-mezopotamia-1.mp4")["track"] == "100"     # the stored number
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    lines.clear()
    assert media_files.sync_videos(repo, "barna", lines.append, base) == []
    assert lines == ["videók: 0 átnevezve, 0 címkézve, 4 változatlan"]
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before
    assert media_files.missing_descriptions(media_files.video_items(repo)) == ["tori/aa-mezopotamia-1", "tori/athen-1"]


def test_drive_sync_renames_and_replaces_by_the_app_property_and_then_is_quiet():
    fake = FakeDrive()
    fake.items["root"] = {"id": "root", "name": "Root", "mimeType": FOLDER, "parents": [], "appProperties": {}}
    folder = fake.add("Podcast", "root")
    old = fake.add("Történelem – Athén.mp3", folder, "audio/mpeg", b"old", props={"schoolNotesPodcast": "tori/athen"})
    foreign = fake.add("Saját.mp3", folder, "audio/mpeg", b"mine")
    client = DriveClient(fake)
    wanted = {"tori/athen": ("Történelem – 00500_Athén.mp3", lambda: b"tagged"),
              "tori/kreta": ("Történelem – 00400_Kréta.mp3", lambda: b"k")}
    assert upload.sync(client, "root", wanted) == [("tori/athen", "updated"), ("tori/kreta", "created")]
    assert fake.items[old]["name"] == "Történelem – 00500_Athén.mp3" and fake.content[old] == b"tagged"
    assert fake.items[foreign]["name"] == "Saját.mp3"
    assert upload.sync(client, "root", wanted) == [("tori/athen", "unchanged"), ("tori/kreta", "unchanged")]
    assert not any("permissions" in path for _, path, _ in fake.requests)


def test_the_store_is_the_tools_own_a_hand_edit_is_a_guard_finding(tmp_path):
    repo = make_repo(tmp_path)
    media_order.update(repo)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed")
    local_git = _git(repo)
    assert guard.violations(repo, local_git) == []
    safefs.write_text(repo, media_order.STORE, safefs.read_text(repo, media_order.STORE).replace("500", "450"))
    assert guard.violations(repo, local_git) == [
        f"{media_order.STORE}: the media order numbers only `sn close` and `sn podcast` write (M)"]
    tool_writes.record(repo, files=[media_order.STORE])
    assert guard.violations(repo, local_git) == []


def _git(repo):
    from tests.local.conftest import FakeLocal
    return FakeLocal(repo, repo.parent / "root").git()


# --- review round: re-render, interruption, errors, parts ---------------------------------------

def video_repo(tmp_path, videos=("athen-1",)):
    repo = make_repo(tmp_path)
    media_order.update(repo)
    for video in videos:
        safefs.write_json(repo, f"docs/evidence/video/tori/{video}.json", {})
    return repo


@needs_ffmpeg
def test_a_re_render_wins_over_the_numbered_copy_and_leaves_one_file(tmp_path, media):
    repo = video_repo(tmp_path)
    folder = tmp_path / "kesz" / "barna" / "tori"
    folder.mkdir(parents=True)
    shutil.copy(media / "v.mp4", folder / "00500_athen-1.mp4")        # the last publish's copy
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=32x24:rate=5:duration=1",
                    "-c:v", "libx264", str(folder / "athen-1.mp4")], check=True)   # video.py's fresh render
    fresh_streams = probe_streams(folder / "athen-1.mp4")
    assert media_files.sync_videos(repo, "barna", lambda _: None, tmp_path / "kesz") == []
    assert [p.name for p in folder.iterdir()] == ["00500_athen-1.mp4"]
    assert probe_streams(folder / "00500_athen-1.mp4") == fresh_streams


@needs_ffmpeg
def test_an_interrupted_rename_is_finished_by_the_target_and_the_old_copy_goes(tmp_path, media):
    repo = video_repo(tmp_path)
    folder = tmp_path / "kesz" / "barna" / "tori"
    folder.mkdir(parents=True)
    shutil.copy(media / "v.mp4", folder / "00400_athen-1.mp4")        # the old number
    shutil.copy(media / "v.mp4", folder / "00500_athen-1.mp4")        # already in place when it stopped
    assert media_files.sync_videos(repo, "barna", lambda _: None, tmp_path / "kesz") == []
    assert [p.name for p in folder.iterdir()] == ["00500_athen-1.mp4"]


def probe_streams(path):
    return subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height", "-of", "csv=p=0",
                           str(path)], capture_output=True, text=True, check=True).stdout


class BrokenDriveLocal:
    def __init__(self, repo):
        self.repo, self.name = repo, "barna"
        self.student = type("S", (), {"drive_root": "root"})()

    def drive(self):
        from school_notes2.state.errors import NeedsOwner
        raise NeedsOwner("nincs Drive-token", todo="jelentkezz be")


@needs_ffmpeg
def test_publish_file_step_never_raises_a_drive_ffmpeg_or_file_error_is_a_line(tmp_path, monkeypatch):
    repo = video_repo(tmp_path)
    safefs.write_json(repo, "docs/evidence/podcast/tori/athen.json", {})
    monkeypatch.setattr(media_files.wiki_podcast, "records", lambda repo: [record("tori", "athen", "2026-10-01", "Athén")])
    folder = tmp_path / "kesz" / "barna" / "tori"
    folder.mkdir(parents=True)
    (folder / "athen-1.mp4").write_bytes(b"not a video")
    lines = []
    assert media_files.sync(BrokenDriveLocal(repo), lines.append, tmp_path / "kesz") == 1
    assert "  Drive: nincs Drive-token" in lines
    assert any(line.startswith("  tori/athen-1.mp4: hiba: ffmpeg: athen-1.mp4") for line in lines)
    assert (folder / "athen-1.mp4").read_bytes() == b"not a video"            # nothing lost
    assert [p.name for p in folder.iterdir()] == ["athen-1.mp4"]               # no temp file left


def test_parts_sort_as_numbers_and_only_the_last_number_is_the_part(tmp_path):
    assert media_order.video_page("fejezet-2-10") == "fejezet-2" and media_order.video_part("fejezet-2-10") == 10
    assert media_order.video_page("athen") == "athen" and media_order.video_part("athen") == 0
    repo = make_repo(tmp_path)
    safefs.write_text(repo, "wiki/tori/fejezet-2.md", topic("Második fejezet", "hellasz", 30))
    media_order.update(repo)
    for video in ("fejezet-2-10", "fejezet-2-2", "fejezet-2-1"):
        safefs.write_json(repo, f"docs/evidence/video/tori/{video}.json", {})
    items = media_files.video_items(repo)
    assert [i["video"] for i in items] == ["fejezet-2-1", "fejezet-2-2", "fejezet-2-10"]
    assert {i["number"] for i in items} == {600} and items[2]["tags"]["title"] == "Második fejezet (10. rész)"


def test_mp4_track_above_its_16_bit_field_is_left_out(tmp_path):
    args = media_files.ffmpeg_args(tmp_path / "a.mp4", tmp_path / "b.mp4", {"title": "x", "track": "70000"})
    assert "track=70000" not in args and "title=x" in args
    args = media_files.ffmpeg_args(tmp_path / "a.mp3", tmp_path / "b.mp3", {"track": "70000"})
    assert "track=70000" in args
