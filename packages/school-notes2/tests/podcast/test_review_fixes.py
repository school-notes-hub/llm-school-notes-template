"""The 0.4.0 review's fix round: H2 (no laundering of hand-written machine parts), H3 (a released
episode whose topic page was renamed or deleted can be retired by the tool), J1, J3, J4, J9."""

import subprocess

import pytest

from school_notes2.local import done, guard, podcast
from school_notes2.podcast import audio, openrouter
from school_notes2.podcast.ledger import Ledger
from school_notes2.state import safefs
from school_notes2.state.errors import BadWork
from school_notes2.wiki import markers
from tests.podcast.conftest import TOPIC, needs_ffmpeg, release, snapshot_and_accept

pytestmark = needs_ffmpeg
ASSET = "wiki/assets/proba/podcast/elso.mp3"
RECORD = "docs/evidence/podcast/proba/elso.json"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def open_problems(repo, local):
    return {k: v for k, v in done.problems(repo, local.git()) if v}


def test_hand_written_machine_part_stops_the_release_and_is_never_recorded(world):
    """Reviewer's test_rev_launder.py: a forged generated block on the topic page."""
    repo, local = world["repo"], world["local"]
    text = safefs.read_text(repo, TOPIC)
    forged = text.replace("Az első téma szövege.", markers.wrap("lesson-log", "📎 kézzel írt gépi blokk\n")
                          + "\nAz első téma szövege.")
    safefs.write_text(repo, TOPIC, forged)
    before = guard.violations(repo, local.git())
    assert any("lesson-log" in v for v in before)
    snapshot_and_accept(local)
    code, lines = release(world)
    assert code == 2 and any("kézzel írt gépi rész (block lesson-log)" in line for line in lines)
    assert world["router"].calls == []
    assert guard.violations(repo, local.git()) == before


def test_a_hand_edit_of_the_podcast_page_stops_too(world):
    repo, local = world["repo"], world["local"]
    assert release(world)[0] == 0
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "podcast")
    page = safefs.read_text(repo, "wiki/podcast.md")
    safefs.write_text(repo, "wiki/podcast.md", page.replace("Vendégek:", "Vendégeink:"))
    code, lines = release(world)
    assert code == 2 and any(line.startswith("  wiki/podcast.md: kézzel írt gépi rész") for line in lines)


def test_renamed_topic_page_is_retired_by_the_tool_and_done_is_clean(world):
    """Reviewer's test_rev_rename.py: after a rename `sn done` stayed red with no tool path."""
    repo, local = world["repo"], world["local"]
    assert release(world)[0] == 0
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "podcast")
    git(repo, "mv", TOPIC, "wiki/proba/masodik-lap.md")
    assert open_problems(repo, local)                                  # the broken episode shows
    lines = []
    assert podcast.run(local, "proba", "elso", retire_=True, out=lines.append) == 0
    assert "lejátszó levéve: wiki/proba/masodik-lap.md" in lines
    assert not safefs.is_file(repo, ASSET) and not safefs.is_file(repo, RECORD)
    assert not safefs.is_file(repo, "wiki/podcast.md")                 # no episode: no menu item
    assert any("Próba – Első.mp3 fájl megmarad" in line for line in lines)
    assert "podcast" not in markers.names(safefs.read_text(repo, "wiki/proba/masodik-lap.md"))
    # what stays is the rename's own (the subject index link, `sn close` regenerates it), nothing of the podcast
    assert open_problems(repo, local) == {"lapellenőrzési hiba": [
        "wiki/proba/index.md:20 link target does not exist: 'elso.md'"]}
    public = safefs.read_json(repo, "publication/public.json")
    assert "wiki/podcast.md" not in [p["path"] for p in public["pages"]]
    assert not any(a["path"] == ASSET for a in public["assets"])
    assert world["drive"].files_in(next(i["id"] for i in world["drive"].items.values() if i["name"] == "Podcast"))


def test_deleted_topic_page_is_retired_too(world):
    repo, local = world["repo"], world["local"]
    assert release(world)[0] == 0
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "podcast")
    git(repo, "rm", "-q", TOPIC)
    assert podcast.run(local, "proba", "elso", retire_=True, out=lambda *_: None) == 0
    left = open_problems(repo, local)
    assert "író-őr: tiltott módosítás" not in left and not any("podcast" in str(v) for v in left.values())


def test_a_hand_deleted_receipt_is_still_a_guard_finding(world):
    repo, local = world["repo"], world["local"]
    assert release(world)[0] == 0
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "podcast")
    safefs.unlink(repo, RECORD)
    assert any(v.startswith(f"{RECORD}: a podcast receipt only") for v in guard.violations(repo, local.git()))


def test_retire_without_a_release_is_a_stop(world):
    lines = []
    assert podcast.run(world["local"], "proba", "elso", retire_=True, out=lines.append) == 2
    assert any("nincs kiadott adás" in line for line in lines)


def test_a_request_left_unknown_warns_before_it_is_sent_again(world):
    world["router"].fail = [TimeoutError("lost")]
    with pytest.raises(openrouter.Unknown):
        release(world)
    code, lines = release(world)
    assert code == 0
    assert any(line.startswith("figyelmeztetés: speech: ugyanez a kérés korábban unknown") for line in lines)


def test_an_error_body_with_status_200_is_not_cached(world):
    router = world["router"]
    real = router.__call__

    def once(method, url, body, headers, timeout):
        if url == openrouter.TRANSCRIPTION and not router.calls_error:
            router.calls_error = True
            router.calls.append((method, url, None))
            return openrouter.Answer(200, {"content-type": "application/json"}, b'{"error": {"message": "busy"}}')
        return real(method, url, body, headers, timeout)
    router.calls_error = False
    world["router"] = once
    with pytest.raises(BadWork, match="a válasz nem text"):
        release(world)
    calls = Ledger(world["local"].podcast_settings()).value["calls"]
    assert [c["state"] for c in calls if c["kind"] == "transcription"] == ["failed"]
    world["router"] = router
    assert release(world)[0] == 0                                         # asked again, not served from the cache


def test_ffmpeg_failure_is_an_sn_error(tmp_path):
    bad = tmp_path / "zene.mp3"
    bad.write_bytes(b"not audio")
    with pytest.raises(audio.MixError):
        audio.episode([b"\0\0" * 24000], bad, tmp_path, title="x", album="y")


def test_the_podcast_lock_names_itself(tmp_path):
    import fcntl
    import os
    from school_notes2.images.budget import LockTimeout, images_lock
    path = tmp_path / "podcast.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    with pytest.raises(LockTimeout, match="podcast lock busy"):
        with images_lock(path, 0, poll_s=0, what="podcast"):
            pass
    os.close(fd)


def test_a_new_drive_file_is_created_with_its_content_in_one_request(world):
    assert release(world)[0] == 0
    methods = [(m, p, q.get("uploadType")) for m, p, q in world["drive"].requests]
    assert ("POST", "/upload/drive/v3/files", "multipart") in methods
    assert [p for m, p, q in world["drive"].requests if m == "PATCH" and p.startswith("/upload/")] == []
    files = [i for i in world["drive"].items.values() if i["mimeType"] == "audio/mpeg"]
    assert len(files) == 1 and int(files[0]["size"]) > 0


def test_client_repr_hides_the_key():
    assert "test-key" not in repr(openrouter.Client("test-key"))
