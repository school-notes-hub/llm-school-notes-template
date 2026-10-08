"""`sn podcast` end to end with the fakes: the release, its outputs and a free, byte-identical re-run."""

import json
import subprocess

from school_notes2.local import done, guard
from school_notes2.podcast import openrouter
from school_notes2.state import safefs
from school_notes2.wiki import podcast as wiki_podcast
from tests.local.conftest import git
from tests.podcast.conftest import FOLDER_OUT, TOPIC, needs_ffmpeg, release

pytestmark = needs_ffmpeg
ASSET = "wiki/assets/proba/podcast/elso.mp3"
RECORD = "docs/evidence/podcast/proba/elso.json"


def probe(path, entries):
    return subprocess.run(["ffprobe", "-v", "error", "-show_entries", entries, "-of", "json", str(path)],
                          capture_output=True, text=True, check=True).stdout


def test_release_writes_the_mp3_receipt_page_block_podcast_page_and_drive_copy(world):
    code, lines = release(world)
    repo = world["repo"]
    assert code == 0, lines
    data = safefs.read_bytes(repo, ASSET)
    info = json.loads(probe(repo / ASSET, "stream=channels,sample_rate,bit_rate:format=duration:format_tags"))
    assert info["streams"][0]["channels"] == 1 and info["streams"][0]["bit_rate"] == "64000"
    assert info["format"]["tags"] == {"title": "Az első téma röviden", "album": "Képben vagy?"}
    record = safefs.read_json(repo, RECORD)
    assert record["output_sha256"] == __import__("hashlib").sha256(data).hexdigest()
    assert record["rights"]["class"] == "generated" and "Suno" in record["rights"]["music"]
    assert record["drive"] == {"folder": "Podcast", "name": "Próba – Első.mp3"}
    assert record["verdict"]["verdict"] == "accept" and record["reviewer"].startswith("claude-opus")
    assert [s["id"] for s in record["speech"]["scenes"]] == ["J1", "J2"]
    page = safefs.read_text(repo, TOPIC)
    block = page.split("<!-- school-notes:generated podcast -->")[1].split("<!-- /school-notes:generated -->")[0]
    assert "🎧 **Képben vagy?** · *Az első téma röviden*" in block
    assert "](../assets/proba/podcast/elso.mp3)" in block and "](../podcast.md)" in block
    assert page.index("# Első") < page.index("school-notes:generated podcast") < page.index("Az első téma szövege")
    podcast_page = safefs.read_text(repo, "wiki/podcast.md")
    assert "**Képben vagy?**" in podcast_page and "Dani, a műsorvezető" in podcast_page
    assert "Vendégek: Zsófi (próba)." in podcast_page
    assert "## Az első téma röviden" in podcast_page and "[Első](proba/elso.md)" in podcast_page
    assert "Dani és Zsófi az első témát beszéli át" in podcast_page
    assert "](assets/proba/podcast/elso.mp3)" in podcast_page
    public = safefs.read_json(repo, "publication/public.json")
    assert [p["path"] for p in public["pages"][:2]] == ["wiki/index.md", "wiki/podcast.md"]
    assert public["pages"][1]["navigationLabel"] == "🎧 Podcast"
    asset = next(a for a in public["assets"] if a["path"] == ASSET)
    assert asset["rights"] == "generated" and asset["rightsEvidence"] == RECORD
    drive = world["drive"]
    folder = next(i for i in drive.items.values() if i["name"] == "Podcast")
    assert folder["parents"] == ["root-id"]
    [file] = drive.files_in(folder["id"])
    assert file["name"] == "Próba – Első.mp3" and drive.content[file["id"]] == data
    assert any("Drive: Podcast/Próba – Első.mp3 (új fájl" in line for line in lines)
    # the tool's own writes: the content check and the writer guard are clean
    assert done.problems(repo, world["local"].git()) == [(n, []) for n, _ in done.problems(repo, world["local"].git())]


def test_rerun_pays_nothing_and_gives_the_same_bytes_and_the_same_drive_file(world):
    assert release(world)[0] == 0
    repo, router = world["repo"], world["router"]
    before = {rel: safefs.read_bytes(repo, rel) for rel in (ASSET, RECORD, TOPIC, "wiki/podcast.md",
                                                             "publication/public.json")}
    paid = len(router.calls)
    code, lines = release(world)
    assert code == 0
    assert [u for _, u, _ in router.calls[paid:] if not u.startswith(openrouter.GENERATION)] == []
    assert {rel: safefs.read_bytes(repo, rel) for rel in before} == before
    drive = world["drive"]
    assert len([i for i in drive.items.values() if i["mimeType"] == "audio/mpeg"]) == 1
    assert any("(változatlan" in line for line in lines)


def test_rerun_after_commit_is_clean_for_the_guard_and_publishable(world):
    assert release(world)[0] == 0
    repo, local = world["repo"], world["local"]
    assert guard.violations(repo, local.git()) == []
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "podcast")
    assert release(world)[0] == 0
    assert git(repo, "status", "--porcelain") == ""


def test_retitled_episode_updates_the_same_drive_file(world):
    from tests.podcast.conftest import SCRIPT, hand_over, snapshot_and_accept
    assert release(world)[0] == 0
    repo = world["repo"]
    safefs.write_text(repo, TOPIC, safefs.read_text(repo, TOPIC).replace("title: Első", "title: Első lépések"))
    hand_over(repo, {**SCRIPT, "title": "Új cím"})
    snapshot_and_accept(world["local"])
    code, lines = release(world)
    assert code == 0, lines
    drive = world["drive"]
    [file] = [i for i in drive.items.values() if i["mimeType"] == "audio/mpeg"]
    assert file["name"] == "Próba – Első lépések.mp3"
    assert drive.content[file["id"]] == safefs.read_bytes(repo, ASSET)
    assert any("(frissítve" in line for line in lines)
    assert safefs.read_json(repo, RECORD)["title"] == "Új cím"


def test_names_not_verified_do_not_block_and_go_into_the_receipt_with_their_moment(world):
    world["router"].heard = {"[NÉV] pedig": "kossut lajos"}
    code, lines = release(world)
    assert code == 0
    names = {n["form"]: n for n in safefs.read_json(world["repo"], RECORD)["names"]}
    assert names["Batthyány Lajos"]["verified"] is True
    assert names["Batthyány Lajos"]["heard"] == ["battyányi lajos"] * 3 and names["Batthyány Lajos"]["whisper"]
    kossuth = names["Kossuth Lajos"]
    assert kossuth["verified"] is False and kossuth["heard"] == ["kossut lajos"]      # stops at the first miss
    assert kossuth["scene"] == "J2" and kossuth["at"] and kossuth["at_s"] > 12.3     # after the 12 s intro
    assert any(line.startswith("  nem igazolt: Kossuth Lajos – ") for line in lines)
    assert "nevek: 1/2 gépileg igazolt" in lines


def test_both_learners_get_the_same_episode_from_the_same_input(world, tmp_path, music):
    from school_notes2.local import podcast
    from tests.podcast.conftest import FakeDrive, FakeOpenRouter, PodcastLocal, hand_over, learner_repo, \
        snapshot_and_accept
    assert release(world)[0] == 0
    other = learner_repo(tmp_path / "other")
    hand_over(other)
    drive = FakeDrive()
    drive.items["root-id"] = {"id": "root-id", "name": "Root", "mimeType": "x", "parents": [], "appProperties": {}}
    local = PodcastLocal(other, tmp_path / "other-state", music, drive, name="masik")
    snapshot_and_accept(local)
    c = openrouter.Client("test-key", 30, transport=FakeOpenRouter(), sleep=lambda s: None)
    assert podcast.run(local, "proba", "elso", False, out=lambda *_: None, client=c, sleep=lambda s: None) == 0
    for rel in (ASSET, TOPIC, "wiki/podcast.md"):
        assert safefs.read_bytes(other, rel) == safefs.read_bytes(world["repo"], rel)


def test_podcast_hand_over_is_not_a_subject_hand_over_for_sn_close(world):
    from school_notes2.local import handoff
    assert safefs.is_dir(world["repo"], FOLDER_OUT)
    assert handoff.handoffs(world["repo"], None) == []


def test_drive_names_are_told_apart_by_first_release():
    names = wiki_podcast.drive_names({"b/x": ("Próba", "Cím", "2026-10-09"), "a/y": ("Próba", "Cím", "2026-10-08"),
                                      "c/z": ("Próba", "Cím/2", "2026-10-08")})
    assert names == {"a/y": "Próba – Cím.mp3", "b/x": "Próba – Cím (2).mp3", "c/z": "Próba – Cím-2.mp3"}
