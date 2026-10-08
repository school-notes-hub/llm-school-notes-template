"""The podcast's Drive copy: one `Podcast/` folder under the learner's root, the episode found by
its app property, never a duplicate, no permission or share request, verified by size and MD5."""

import pytest

from school_notes2.drive import upload
from school_notes2.drive.client import FOLDER, DriveClient
from school_notes2.state.errors import NeedsOwner, Transient
from tests.podcast.conftest import FakeDrive, needs_ffmpeg, release


def drive_with_root():
    fake = FakeDrive()
    fake.items["root"] = {"id": "root", "name": "Root", "mimeType": FOLDER, "parents": [], "appProperties": {}}
    return fake


def test_existing_podcast_folder_is_used_and_the_file_is_updated_in_place():
    fake = drive_with_root()
    folder = fake.add("Podcast", "root")
    client = DriveClient(fake)
    first = upload.upload(client, "root", "proba/elso", "Próba – Első.mp3", b"one")
    assert first["state"] == "created" and not first["folder_created"]
    again = upload.upload(client, "root", "proba/elso", "Próba – Első.mp3", b"one")
    assert again == {**first, "state": "unchanged"}
    changed = upload.upload(client, "root", "proba/elso", "Próba – Első rész.mp3", b"two")
    assert changed["state"] == "updated" and changed["id"] == first["id"]
    [item] = [i for i in fake.files_in(folder)]
    assert item["name"] == "Próba – Első rész.mp3" and fake.content[item["id"]] == b"two"
    assert fake.items[item["id"]]["appProperties"] == {"schoolNotesPodcast": "proba/elso"}


def test_no_permission_or_share_call_is_made():
    fake = drive_with_root()
    upload.upload(DriveClient(fake), "root", "proba/elso", "Próba – Első.mp3", b"x")
    assert not any("permissions" in path for _, path, _ in fake.requests)


def test_two_podcast_folders_or_two_files_of_one_episode_need_the_owner():
    fake = drive_with_root()
    fake.add("Podcast", "root")
    fake.add("Podcast", "root")
    with pytest.raises(NeedsOwner, match="2 Podcast mappa"):
        upload.upload(DriveClient(fake), "root", "proba/elso", "x.mp3", b"x")
    fake = drive_with_root()
    folder = fake.add("Podcast", "root")
    for _ in range(2):
        fake.add("x.mp3", folder, "audio/mpeg", b"x", props={"schoolNotesPodcast": "proba/elso"})
    with pytest.raises(NeedsOwner, match="2 fájl tartozik"):
        upload.upload(DriveClient(fake), "root", "proba/elso", "x.mp3", b"x")


def test_a_foreign_file_with_the_same_name_is_left_alone_and_counted():
    fake = drive_with_root()
    folder = fake.add("Podcast", "root")
    foreign = fake.add("Próba – Első.mp3", folder, "audio/mpeg", b"owner's")
    result = upload.upload(DriveClient(fake), "root", "proba/elso", "Próba – Első.mp3", b"tool's")
    assert result["same_name"] == 1 and result["id"] != foreign and fake.content[foreign] == b"owner's"


def test_an_unverified_upload_is_transient():
    fake = drive_with_root()
    original = fake._set
    fake._set = lambda fid, data: original(fid, data[:-1])      # Drive keeps a truncated file
    with pytest.raises(Transient, match="MD5"):
        upload.upload(DriveClient(fake), "root", "proba/elso", "x.mp3", b"abc")


@needs_ffmpeg
def test_a_drive_failure_comes_after_the_repo_part_and_a_rerun_finishes_it(world):
    world["local"]._drive = DriveClient(FailingDrive(world["drive"]))
    code, lines = release(world)
    assert code == 1 and any(line.startswith("Hiba: Drive:") for line in lines)
    assert (world["repo"] / "wiki/assets/proba/podcast/elso.mp3").is_file()
    assert world["local"].records[-1][1] == "drive-failed"
    paid = len(world["router"].calls)
    world["local"]._drive = DriveClient(world["drive"])
    code, lines = release(world)
    assert code == 0 and any("Drive: Podcast/Próba – Első.mp3 (új fájl" in line for line in lines)
    assert all(u.startswith("https://openrouter.ai/api/v1/generation") for _, u, _ in world["router"].calls[paid:])


class FailingDrive:
    def __init__(self, inner):
        self.inner = inner

    def request(self, method, url, payload=None, headers=None):
        if method != "GET":
            raise Transient("Drive HTTP 503")
        return self.inner.request(method, url, payload, headers)
