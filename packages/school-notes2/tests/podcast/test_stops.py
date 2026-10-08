"""`sn podcast` stops before paying or writing anything: script checks, the reviewer's accept
bound to the content, the budget; a failing provider is retried a bounded number of times."""

import json

import pytest

from school_notes2.local import podcast
from school_notes2.podcast import openrouter
from school_notes2.podcast.ledger import BudgetExhausted, Ledger
from school_notes2.state import safefs
from school_notes2.state.errors import NeedsOwner, Transient
from tests.podcast.conftest import (ACCEPT, FOLDER_OUT, SCRIPT, TOPIC, PodcastLocal, hand_over, http_error,
                                    needs_ffmpeg, release)


def tree(repo):
    return {p: safefs.read_bytes(repo, p) for p in safefs.walk_files(repo) if not p.startswith(".git/")}


def snapshot(world):
    return podcast.run(world["local"], "proba", "elso", True, out=lambda *_: None)


@pytest.mark.parametrize("text, what", [
    ("Ezerhétszáz helyett 1848-ban történt.", "számjegy"),
    ("V. Ferdinánd volt a király.", "római szám"),
    ("Sok minden, pl. a sajtó.", "rövidítés"),
    ("A lakosság 40 százaléka.", "számjegy"),
    ("Kr. e. történt.", "rövidítés"),
])
def test_snapshot_stops_on_a_form_the_speech_model_must_not_get(world, text, what):
    script = json.loads(json.dumps(SCRIPT))
    script["scenes"][0]["turns"][1]["text"] = text
    hand_over(world["repo"], script)
    lines = []
    assert podcast.run(world["local"], "proba", "elso", True, out=lines.append) == 2
    assert any(f"kimondható alak kell, nem {what}" in line for line in lines)


def test_snapshot_stops_on_schema_host_speaker_and_name_problems(world):
    script = json.loads(json.dumps(SCRIPT))
    script["speakers"]["Zsófi"]["role"] = "host"
    script["scenes"][1]["turns"][0]["speaker"] = "Kata"
    script["names"].append({"form": "Széchenyi István", "targets": ["szécsényi istván"]})
    hand_over(world["repo"], script)
    lines = []
    assert podcast.run(world["local"], "proba", "elso", True, out=lines.append) == 2
    text = "\n".join(lines)
    assert "pontosan egy műsorvezető" in text and "ismeretlen beszélő 'Kata'" in text
    assert "a név nem fordul elő a szövegben ebben az alakban: 'Széchenyi István'" in text
    hand_over(world["repo"], {**SCRIPT, "title": "Cím [zárójellel]"})
    assert podcast.run(world["local"], "proba", "elso", True, out=lines.append) == 2


def test_snapshot_stops_on_a_private_path_in_public_text(world):
    hand_over(world["repo"], {**SCRIPT, "summary": "A sources/proba mappából."})
    lines = []
    assert podcast.run(world["local"], "proba", "elso", True, out=lines.append) == 2
    assert any("nyilvánosra nem kerülhet" in line for line in lines)


def test_no_hand_over_or_unknown_page_is_a_stop(world):
    lines = []
    assert podcast.run(world["local"], "proba", "masodik", False, out=lines.append) == 2
    assert any("nincs podcast-átadás" in line for line in lines)
    with pytest.raises(Exception, match="kisbetűs"):
        podcast.run(world["local"], "Próba", "elso", False, out=lines.append)


@pytest.mark.parametrize("change, message", [
    (lambda repo: safefs.unlink(repo, f"{FOLDER_OUT}/verdict.json"), "nincs lektori ítélet"),
    (lambda repo: safefs.write_json(repo, f"{FOLDER_OUT}/verdict.json", {
        "verdict": "reject", "observed": "x", "defects": [
            {"location": "J1", "observed": "a", "expected": "b", "severity": "hiba"}]}), "nem fogadta el (reject)"),
    (lambda repo: safefs.write_json(repo, f"{FOLDER_OUT}/verdict.json", {
        "verdict": "accept", "observed": "x", "defects": [
            {"location": "J1", "observed": "a", "expected": "b", "severity": "hiba"}]}), "`hiba` súlyosságú"),
    (lambda repo: safefs.unlink(repo, f"{FOLDER_OUT}/keys.json"), "nincs pillanatkép"),
    (lambda repo: safefs.write_text(repo, TOPIC, safefs.read_text(repo, TOPIC).replace(
        "További szöveg.", "Más szöveg.")), "az accept nem erre a változatra szól"),
    (lambda repo: hand_over(repo, {**SCRIPT, "summary": "Más összefoglaló."}), "az accept nem erre a változatra szól"),
])
def test_release_without_a_valid_accept_stops_before_paying_or_writing(world, change, message):
    repo = world["repo"]
    change(repo)
    before = tree(repo)
    code, lines = release(world)
    assert code == 2
    assert any(message in line for line in lines), lines
    assert world["router"].calls == []
    assert {p: v for p, v in tree(repo).items() if not p.startswith(".school-notes/")} == \
        {p: v for p, v in before.items() if not p.startswith(".school-notes/")}


def test_generated_blocks_and_lesson_lines_do_not_change_the_review_key(world):
    repo = world["repo"]
    text = safefs.read_text(repo, TOPIC)
    safefs.write_text(repo, TOPIC, text.replace("## Részlet\n", "## Részlet\n\n<sub>🗓️ Óra: okt. 6.</sub>\n"))
    from school_notes2.podcast import script as scripts
    ep = scripts.episode("proba", "elso")
    keys = safefs.read_json(repo, f"{FOLDER_OUT}/keys.json")
    assert scripts.review_key(repo, ep, SCRIPT) == keys["key"]


@needs_ffmpeg
def test_429_is_retried_after_15_and_60_seconds_then_it_goes_on(world):
    world["router"].fail = [http_error(429), http_error(503)]
    sleeps = []
    code, _ = release(world, sleeps=sleeps)
    assert code == 0 and sleeps == [15, 60]


def test_429_three_times_stops_and_books_nothing(world):
    world["router"].fail = [http_error(429)] * 3
    with pytest.raises(Transient, match="HTTP 429 3 próba után"):
        release(world)
    ledger = Ledger(world["local"].podcast_settings())
    [call] = ledger.value["calls"]
    assert call["state"] == "failed" and call["cost_usd"] == 0.0
    assert not safefs.is_file(world["repo"], "wiki/assets/proba/podcast/elso.mp3")


def test_another_4xx_stops_at_once(world):
    world["router"].fail = [http_error(400)]
    with pytest.raises(NeedsOwner, match="HTTP 400"):
        release(world)
    assert len(world["router"].calls) == 1


def test_a_lost_answer_is_unknown_and_keeps_its_reservation(world):
    world["router"].fail = [TimeoutError("lost")]
    with pytest.raises(openrouter.Unknown):
        release(world)
    ledger = Ledger(world["local"].podcast_settings())
    [call] = ledger.value["calls"]
    assert call["state"] == "unknown" and call["cost_usd"] is None
    assert ledger.spent_year() == ledger.cost(call) > 0


def test_budget_must_cover_the_whole_episode_before_the_first_call(world):
    local = world["local"]
    small = PodcastLocal(local.repo, local.cfg.root, local.music, world["drive"], monthly="0.05")
    world["local"] = small
    with pytest.raises(BudgetExhausted, match="havi kerete"):
        release(world)
    assert world["router"].calls == []
    world["local"] = PodcastLocal(local.repo, local.cfg.root, local.music, world["drive"], year="0.01")
    with pytest.raises(BudgetExhausted, match="tanévi kerete"):
        release(world)


def test_missing_music_is_a_prerequisite(world, tmp_path):
    from school_notes2.state.errors import Prerequisite
    local = world["local"]
    world["local"] = PodcastLocal(local.repo, local.cfg.root, tmp_path / "nincs.mp3", world["drive"])
    with pytest.raises(Prerequisite, match="a zene nincs meg"):
        release(world)
    assert world["router"].calls == []


def test_accept_fixture_is_valid():
    from school_notes2.schemas import errors
    assert errors("podcast-verdict", ACCEPT) == [] and errors("podcast-script", SCRIPT) == []
