"""The podcast's Drive copy (owner, 2026-10-08: "jegyzetoldalon, és drive-on is"; "nem kell
tantárgyanként a drive-on hanem könnyen elérhető legyen"): every episode directly in one
`Podcast/` folder under the learner's Drive root, named `<Tantárgy> – 00100_<lapcím>.mp3` (the
subject's order number in the teaching order, `wiki.media_order`).

The tool's existing full `drive` scope is used as it is; nothing here changes a permission or
a share (the owner shares the folder). The folder is created when it is missing. An episode's
file is found by its private app property (`schoolNotesPodcast` = `<subject>/<page>`), never by
its name: a re-release updates the same file (content and, when the title changed, its name),
never a second one. A new file is created with its content in one multipart request, so an
interruption never leaves an empty file behind. The upload is verified by the size and MD5 Drive
reports."""

import hashlib
import json
import urllib.parse
from collections.abc import Callable

from ..state.errors import NeedsOwner, SnError, Transient
from .client import API, FIELDS, FOLDER, DriveClient
from .inventory import nfc

UPLOAD = "https://www.googleapis.com/upload/drive/v3"
PODCAST = "Podcast"
APP_KEY = "schoolNotesPodcast"
MIME = "audio/mpeg"


def podcast_folder(client: DriveClient, root_id: str) -> tuple[str, bool]:
    """(the id of `Podcast/` directly under the root, created now)."""
    found = [i for i in client.list_children(root_id)
             if i["mimeType"] == FOLDER and nfc(i["name"]) == PODCAST and not i.get("trashed")]
    if len(found) > 1:
        raise NeedsOwner(f"a Drive-gyökérben {len(found)} {PODCAST} mappa van",
                         todo=f"hagyj meg egyet a {PODCAST} mappák közül")
    if found:
        return found[0]["id"], False
    meta = client.t.request("POST", f"{API}/files?" + urllib.parse.urlencode({"fields": FIELDS}),
                            {"name": PODCAST, "mimeType": FOLDER, "parents": [root_id]})[2]
    return meta["id"], True


def managed(client: DriveClient, folder_id: str, ident: str) -> list[dict]:
    query = (f"'{folder_id}' in parents and trashed = false and "
             f"appProperties has {{ key='{APP_KEY}' and value='{_quote(ident)}' }}")
    params = {"q": query, "fields": f"files({FIELDS})", "pageSize": "10", "orderBy": "name"}
    return client.t.request("GET", f"{API}/files?" + urllib.parse.urlencode(params))[2].get("files", [])


def _put(client: DriveClient, folder: str, files: list[dict], ident: str, name: str, data: bytes) -> tuple[dict, str]:
    """The episode's one file (`files`: found by its app property) with this name and content:
    created, or renamed and/or its content replaced; (its metadata, created|updated|unchanged)."""
    if not files:
        return _create(client, {"name": name, "mimeType": MIME, "parents": [folder],
                                "appProperties": {APP_KEY: ident}}, data), "created"
    meta, state = files[0], "unchanged"
    if nfc(meta["name"]) != nfc(name):
        meta = client.t.request("PATCH", f"{API}/files/{_id(meta['id'])}?" + urllib.parse.urlencode(
            {"fields": FIELDS}), {"name": name})[2]
        state = "updated"
    if meta.get("md5Checksum") != hashlib.md5(data).hexdigest() or str(meta.get("size")) != str(len(data)):
        _media(client, meta["id"], data)
        state = "updated"
    return meta, state


def _verified(client: DriveClient, file_id: str, name: str, data: bytes, ident: str) -> dict:
    final = client.get(file_id)
    if final.get("md5Checksum") != hashlib.md5(data).hexdigest() or str(final.get("size")) != str(len(data)) or \
            nfc(final.get("name", name)) != nfc(name):
        raise Transient(f"a Drive-ra feltöltött adás ({ident}) neve, mérete vagy MD5-je nem egyezik",
                        todo="futtasd újra ugyanazt a parancsot (ugyanazt a fájlt frissíti)")
    return final


def upload(client: DriveClient, root_id: str, ident: str, name: str, data: bytes) -> dict:
    """Create or update the episode's file; returns `{id, name, state, folder_created,
    same_name}` (`state`: created, updated or unchanged; `same_name`: other files in the folder
    with this name that the tool did not make)."""
    folder, created = podcast_folder(client, root_id)
    files = managed(client, folder, ident)
    if len(files) > 1:
        raise NeedsOwner(f"a {PODCAST} mappában {len(files)} fájl tartozik ehhez az adáshoz: {ident}",
                         todo="töröld a fölösleget a Drive-on, azután futtasd újra")
    meta, state = _put(client, folder, files, ident, name, data)
    final = _verified(client, meta["id"], name, data, ident)
    others = [i for i in client.list_children(folder)
              if nfc(i["name"]) == nfc(name) and i["id"] != meta["id"]]
    return {"id": meta["id"], "name": final.get("name", name), "state": state, "folder_created": created,
            "same_name": len(others)}


def sync(client: DriveClient, root_id: str, wanted: dict[str, tuple[str, Callable[[], bytes]]]) -> list[tuple[str, str]]:
    """Every episode's Drive file with this name and these bytes (`sn publish`: the order number
    and the tags; owner, 2026-10-14). One folder lookup, then per episode its file by the app
    property; its bytes are made only then (one MP3 in memory at a time). A changed file is
    verified by size, MD5 and name. Returns [(ident, state)] in ident order: `created`,
    `updated`, `unchanged`, or a problem for that episode (two files of one episode – the
    owner's –, its bytes could not be made); a Drive error stops the whole sync."""
    if not wanted:
        return []
    folder, _ = podcast_folder(client, root_id)
    out = []
    for ident in sorted(wanted):
        name, make = wanted[ident]
        files = managed(client, folder, ident)
        if len(files) > 1:
            out.append((ident, f"{len(files)} fájl tartozik hozzá a {PODCAST} mappában – a tulajdonosé"))
            continue
        try:
            data = make()
        except (SnError, OSError) as exc:
            out.append((ident, f"hiba: {exc}"))
            continue
        meta, state = _put(client, folder, files, ident, name, data)
        if state != "unchanged":
            _verified(client, meta["id"], name, data, ident)
        out.append((ident, state))
    return out


def _create(client: DriveClient, meta: dict, data: bytes) -> dict:
    """One `uploadType=multipart` request: the metadata and the content together."""
    boundary = "sn-podcast-" + hashlib.sha256(data).hexdigest()[:32]
    while boundary.encode() in data:
        boundary += "x"
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(meta, ensure_ascii=False)}\r\n--{boundary}\r\nContent-Type: {MIME}\r\n\r\n").encode() + \
        data + f"\r\n--{boundary}--\r\n".encode()
    url = f"{UPLOAD}/files?" + urllib.parse.urlencode({"uploadType": "multipart", "fields": FIELDS})
    return client.t.request("POST", url, body, {"Content-Type": f"multipart/related; boundary={boundary}"})[2]


def _media(client: DriveClient, file_id: str, data: bytes) -> None:
    url = f"{UPLOAD}/files/{_id(file_id)}?" + urllib.parse.urlencode({"uploadType": "media", "fields": FIELDS})
    client.t.request("PATCH", url, data, {"Content-Type": MIME})


def _id(file_id: str) -> str:
    return urllib.parse.quote(file_id, safe="")


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")

