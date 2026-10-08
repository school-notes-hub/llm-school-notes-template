"""Fakes for `sn podcast`: OpenRouter (speech, Whisper, the blind check, generation cost) and
Drive are in-process; ffmpeg is the real one, with a synthetic music file."""

import hashlib
import io
import itertools
import json
import math
import shutil
import struct
import subprocess
import urllib.error
import urllib.parse
from decimal import Decimal
from pathlib import Path

import pytest

from school_notes2.drive.client import FOLDER, DriveClient
from school_notes2.podcast import openrouter
from school_notes2.podcast.ledger import PodcastSettings
from school_notes2.state import safefs
from tests.local.conftest import FakeLocal, git, learner_files

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")

TOPIC = "wiki/proba/elso.md"
FOLDER_OUT = ".school-notes/out/podcast/proba/elso"
SCRIPT = {
    "writer": "podcast-iro (teszt)",
    "title": "Az első téma röviden",
    "summary": "Dani és Zsófi az első témát beszéli át, a végén a dolgozatpontokkal.",
    "style": "Két fiatal laza, élő podcast-beszélgetése magyarul.",
    "speakers": {"Dani": {"voice": "Puck", "role": "host"}, "Zsófi": {"voice": "Laomedeia", "role": "guest"}},
    "scenes": [
        {"id": "J1", "turns": [
            {"speaker": "Zsófi", "text": "Sziasztok, itt a Képben vagy? Ma Batthyány Lajos a téma.",
             "style": "Jelenet-felidézően kezd."},
            {"speaker": "Dani", "text": "Dani vagyok, és ez tényleg érdekes.", "style": "Élénk, kíváncsi."}]},
        {"id": "J2", "turns": [
            {"speaker": "Zsófi", "text": "Kossuth Lajos pedig a pénzügyeket vitte.", "style": "Közvetlenül magyaráz."},
            {"speaker": "Dani", "text": "Ez volt a Képben vagy? Sziasztok!", "style": ""}]},
    ],
    "names": [{"form": "Batthyány Lajos", "targets": ["battyányi lajos"]},
              {"form": "Kossuth Lajos", "targets": ["kosut lajos", "kosút lajos"]}],
}
ACCEPT = {"verdict": "accept", "observed": "A forgatókönyv a lapot követi.", "defects": []}


def tone(seconds: float, freq: float, rate: int = 24000) -> bytes:
    return b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * n / rate)))
                    for n in range(int(seconds * rate)))


class FakeOpenRouter:
    """The four endpoints as `openrouter.Client` sees them; records every call."""

    def __init__(self, heard: dict | None = None):
        self.calls = []
        self.heard = heard or {}          # context marker → what the blind check hears (default: the target)
        self.fail = []                    # exceptions raised by the next calls, in order
        self.whisper_text = None
        self.voices = {}

    def __call__(self, method, url, body, headers, timeout):
        assert headers["Authorization"] == "Bearer test-key"
        payload = json.loads(body) if body else None
        self.calls.append((method, url, payload))
        if self.fail:
            raise self.fail.pop(0)
        if url == openrouter.SPEECH:
            seconds = 1.0 + sum(len(t["text"]) for t in payload["input"]) / 60
            pcm = tone(seconds, 200 + 20 * len(payload["input"]))
            return openrouter.Answer(200, {"content-type": "audio/pcm", "x-generation-id": f"gen-{len(self.calls)}"},
                                     pcm)
        if url == openrouter.TRANSCRIPTION:
            import base64
            assert payload["input_audio"]["format"] == "mp3"
            data = base64.b64decode(payload["input_audio"]["data"])
            seconds = (len(data) - 200) * 8 / 64000          # 64 kbit/s CBR, minus the header
            text = self.whisper_text or self._transcript()
            words = text.split()
            step = seconds / max(len(words), 1)
            return self._json({"text": text, "words": [{"word": w, "start": round(i * step, 3),
                                                        "end": round((i + 1) * step, 3)} for i, w in enumerate(words)],
                               "usage": {"cost": 0.0004}})
        if url == openrouter.CHAT:
            prompt = payload["messages"][0]["content"][0]["text"]
            heard = None
            for marker, value in self.heard.items():
                if marker in prompt:
                    heard = value
            return self._json({"id": f"gen-{len(self.calls)}", "usage": {"cost": 0.001},
                               "choices": [{"message": {"content": json.dumps({"hallott": heard or self._target(prompt)},
                                                                              ensure_ascii=False)}}]})
        if url.startswith(openrouter.GENERATION):
            return self._json({"data": {"total_cost": 0.05}})
        raise AssertionError(url)

    def _transcript(self):
        return ("Sziasztok itt a Képben vagy Ma battyányi lajos a téma Dani vagyok és ez tényleg érdekes "
                "kosut lajos pedig a pénzügyeket vitte Ez volt a Képben vagy Sziasztok")

    @staticmethod
    def _target(prompt):
        return "kosut lajos" if "[NÉV] pedig" in prompt else "battyányi lajos"

    @staticmethod
    def _json(value):
        return openrouter.Answer(200, {"content-type": "application/json"}, json.dumps(value).encode())

    def count(self, url):
        return sum(1 for _, u, _ in self.calls if u == url)


def http_error(code):
    return urllib.error.HTTPError(openrouter.SPEECH, code, "x", {}, io.BytesIO(b'{"error": "x"}'))


class FakeDrive:
    """Drive v3 for the podcast upload: list (parents, appProperties), create, metadata and
    media update, get."""

    def __init__(self):
        self.items, self.content, self.ids = {}, {}, itertools.count(1)
        self.requests = []

    def add(self, name, parent=None, mime=FOLDER, data=None, props=None):
        fid = f"id{next(self.ids)}"
        self.items[fid] = {"id": fid, "name": name, "mimeType": mime, "parents": [parent] if parent else [],
                           "appProperties": props or {}}
        if data is not None:
            self._set(fid, data)
        return fid

    def _set(self, fid, data):
        self.content[fid] = data
        self.items[fid].update(size=str(len(data)), md5Checksum=hashlib.md5(data).hexdigest())

    def request(self, method, url, payload=None, headers=None):
        parts = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parts.query))
        self.requests.append((method, parts.path, query))
        if parts.path.startswith("/upload/drive/v3/files/") and method == "PATCH":
            fid = urllib.parse.unquote(parts.path.rsplit("/", 1)[1])
            assert query["uploadType"] == "media" and headers["Content-Type"] == "audio/mpeg"
            self._set(fid, payload)
            return 200, {}, self._public(fid)
        path = parts.path.removeprefix("/drive/v3/files")
        if method == "GET" and path == "":
            return 200, {}, {"files": [self._public(i) for i in self._list(query["q"])]}
        if method == "POST" and path == "":
            fid = self.add(payload["name"], payload["parents"][0], payload["mimeType"],
                           props=payload.get("appProperties"))
            return 200, {}, self._public(fid)
        fid = urllib.parse.unquote(path.lstrip("/"))
        if method == "GET":
            return 200, {}, self._public(fid)
        if method == "PATCH":
            self.items[fid].update(payload)
            return 200, {}, self._public(fid)
        raise AssertionError((method, url))

    def _public(self, fid):
        return {k: v for k, v in self.items[fid].items() if k != "appProperties"}

    def _list(self, q):
        parent = q.split("'")[1]
        found = [i for i in self.items.values() if parent in i["parents"]]
        if "appProperties has" in q:
            value = q.split("value='")[1].rsplit("'", 1)[0]
            found = [i for i in found if i["appProperties"].get("schoolNotesPodcast") == value]
        return sorted((i["id"] for i in found), key=lambda f: self.items[f]["name"])

    def files_in(self, parent):
        return [i for i in self.items.values() if parent in i["parents"]]


class PodcastLocal(FakeLocal):
    def __init__(self, repo, root, music, drive, name="barna", monthly="5", year="40"):
        super().__init__(repo, root, name=name, drive=DriveClient(drive), drive_root="root-id")
        self.music, self.monthly, self.year = music, Decimal(monthly), Decimal(year)

    def podcast_settings(self):
        return PodcastSettings(learner=self.name, state_root=self.cfg.root / "state" / "podcast",
                               lock_path=self.cfg.root / "state" / "podcast.lock", key_file=Path("/nonexistent"),
                               music=self.music, monthly_usd=self.monthly, year_total_usd=self.year,
                               timeout_s=30)


@pytest.fixture(scope="session")
def music(tmp_path_factory):
    if shutil.which("ffmpeg") is None:
        return None
    path = tmp_path_factory.mktemp("music") / "outro.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=30:sample_rate=44100",
                    "-ac", "2", "-c:a", "libmp3lame", "-b:a", "128k", "-metadata", "title=Suno teszt",
                    str(path)], check=True)
    return path


def learner_repo(path: Path) -> Path:
    from school_notes2.wiki import generate, public
    path.mkdir(parents=True)
    files = learner_files()
    files[TOPIC] = ("---\ntype: topic\ntitle: Első\ndescription: Az első téma.\nchapter: alapok\norder: 10\n---\n"
                    "# Első\n\nAz első téma szövege.\n\n## Részlet\n\nTovábbi szöveg.\n")
    for rel, text in files.items():
        safefs.write_text(path, rel, text)
    safefs.write_text(path, ".gitignore", ".school-notes/\n")
    generate.write_indexes(path)
    public.write(path, public.render_rights(path))
    git(path, "init", "-q", "-b", "main")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "seed")
    return path


def hand_over(repo: Path, script=None) -> None:
    safefs.write_json(repo, f"{FOLDER_OUT}/adas.json", script or SCRIPT)


def accept(repo: Path, verdict=ACCEPT) -> None:
    """The reviewer's verdict, after the snapshot."""
    safefs.write_json(repo, f"{FOLDER_OUT}/verdict.json", verdict)


def snapshot_and_accept(local, verdict=ACCEPT) -> None:
    from school_notes2.local import podcast
    assert podcast.run(local, "proba", "elso", True, out=lambda *_: None) == 0
    accept(local.repo, verdict)


@pytest.fixture
def world(tmp_path, music):
    """A committed learner repo with an accepted, snapshotted hand-over; fakes ready."""
    from school_notes2.local import podcast
    repo = learner_repo(tmp_path / "repo")
    hand_over(repo)
    drive = FakeDrive()
    drive.add("Root", None)
    drive.items["root-id"] = drive.items.pop("id1")
    drive.items["root-id"]["id"] = "root-id"
    local = PodcastLocal(repo, tmp_path / "state-root", music, drive)
    router = FakeOpenRouter()
    snapshot_and_accept(local)
    return {"repo": repo, "local": local, "drive": drive, "router": router, "tmp": tmp_path}


def client(router):
    return openrouter.Client("test-key", 30, transport=router, sleep=lambda s: None)


def release(world, out=None, sleeps=None):
    from school_notes2.local import podcast
    lines = [] if out is None else out
    c = openrouter.Client("test-key", 30, transport=world["router"],
                          sleep=(sleeps.append if sleeps is not None else (lambda s: None)))
    code = podcast.run(world["local"], "proba", "elso", False, out=lines.append, client=c, sleep=lambda s: None)
    return code, lines
