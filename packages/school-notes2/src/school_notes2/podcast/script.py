"""The podcast hand-over `.school-notes/out/podcast/<subject>/<page>/` (never committed):

* `adas.json` – the podcast writer's script (schema `podcast-script`): episode title and
  one-sentence summary (both public: the Podcast page, the topic page block, the MP3 tags),
  the shared tone sentence `style`, `speakers` (name → Gemini voice and role, exactly one
  `host`), the `scenes` (one speech call each) with their `turns` (speaker, text as it is
  spoken, the turn's own tone instruction) and the `names` to check (`form` as it stands in
  the text, `targets` – the accepted pronunciations in Hungarian spelling);
* `keys.json` – `sn podcast --snapshot`: the review key of the script and the topic page as
  they are now; the reviewer's accept is valid for this key only;
* `verdict.json` – the reviewer's verdict (schema `podcast-verdict`).

The review key binds the script and the topic page's author text (generated blocks, machine
frontmatter keys and the lesson and textbook lines left out, as for a figure's section)."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..figures.review import is_error
from ..schemas import errors as schema_errors
from ..state import safefs
from ..wiki import frontmatter, markers
from ..wiki.date_spans import META_LINE

ROOT = ".school-notes/out/podcast"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")
SHOW = "Képben vagy?"

# What the speech model must not get (owner rule 2026-10-07: only the spoken form goes to the
# TTS): digits, percent and paragraph signs, Roman numerals with a dot, common abbreviations.
UNSPOKEN = (
    (re.compile(r"\d"), "számjegy"),
    (re.compile(r"[%§]"), "jel (%, §)"),
    (re.compile(r"(?<![\w-])[IVXLCDM]{1,6}\.(?=\s|$)"), "római szám"),
    (re.compile(r"(?<![\w-])(?:pl|stb|kb|ill|ún|vö|kr|db|sz|ld|ford)\.", re.I),
     "rövidítés"),
)


@dataclass(frozen=True)
class Episode:
    """Where one episode's hand-over and outputs live (subject and page stem are slugs)."""

    subject: str
    page_stem: str

    @property
    def page(self) -> str:
        return f"wiki/{self.subject}/{self.page_stem}.md"

    @property
    def folder(self) -> str:
        return f"{ROOT}/{self.subject}/{self.page_stem}"

    @property
    def asset(self) -> str:
        return f"wiki/assets/{self.subject}/podcast/{self.page_stem}.mp3"

    @property
    def record(self) -> str:
        return f"docs/evidence/podcast/{self.subject}/{self.page_stem}.json"

    @property
    def ident(self) -> str:
        return f"{self.subject}/{self.page_stem}"


def episode(subject: str, page: str) -> Episode:
    """`page` is the topic page's file stem (`elso`, also `elso.md` or the wiki path)."""
    stem = page.rsplit("/", 1)[-1].removesuffix(".md")
    for value, what in ((subject, "tantárgy"), (stem, "lap")):
        if not SLUG.fullmatch(value):
            raise ValueError(f"a {what} neve kisbetűs, ékezet nélküli azonosító legyen: {value!r}")
    if stem == "index":
        raise ValueError("a tantárgyi index nem témalap")
    return Episode(subject, stem)


def read(repo: Path, ep: Episode, name: str, default=None):
    rel = f"{ep.folder}/{name}"
    return safefs.read_json(repo, rel, default) if safefs.is_file(repo, rel) else default


def load(repo: Path, ep: Episode) -> tuple[dict | None, list[str]]:
    """(script or None, problems): the schema and the rules no schema can say."""
    if not safefs.is_dir(repo, ep.folder):
        return None, [f"nincs podcast-átadás: {ep.folder}/"]
    try:
        script = read(repo, ep, "adas.json")
    except ValueError as exc:
        return None, [f"{ep.folder}/adas.json nem JSON: {exc}"]
    if script is None:
        return None, [f"hiányzik: {ep.folder}/adas.json"]
    found = schema_errors("podcast-script", script)
    if found:
        return None, [f"{ep.folder}/adas.json: {p}" for p in found[:10]]
    return script, problems(repo, ep, script)


def problems(repo: Path, ep: Episode, script: dict) -> list[str]:
    out = []
    if not safefs.is_file(repo, ep.page):
        out.append(f"a témalap nincs meg: {ep.page}")
    roles = [n for n, s in script["speakers"].items() if s["role"] == "host"]
    if len(roles) != 1:
        out.append(f"pontosan egy műsorvezető (role: host) kell, van: {len(roles)}")
    ids = [s["id"] for s in script["scenes"]]
    if len(ids) != len(set(ids)):
        out.append("a jelenetek azonosítója ismétlődik")
    for scene in script["scenes"]:
        for n, turn in enumerate(scene["turns"], 1):
            where = f"{scene['id']}/{n}"
            if turn["speaker"] not in script["speakers"]:
                out.append(f"{where}: ismeretlen beszélő {turn['speaker']!r}")
            for pattern, what in UNSPOKEN:
                found = pattern.search(turn["text"])
                if found:
                    out.append(f"{where}: kimondható alak kell, nem {what}: {found[0]!r}")
    from .names import occurrences
    for entry in script["names"]:
        if not any(occurrences(turn["text"], [entry]) for scene in script["scenes"] for turn in scene["turns"]):
            out.append(f"a név nem fordul elő a szövegben ebben az alakban: {entry['form']!r}")
    from ..wiki.check import SECRET_PATTERNS, VISIBLE_PATTERNS
    public = [script["title"], script["summary"]] + [t["text"] for s in script["scenes"] for t in s["turns"]]
    secrets = tuple(re.compile(p, re.I) for p in SECRET_PATTERNS)
    for text in public:
        for pattern in (*secrets, *VISIBLE_PATTERNS):
            if pattern.search(text):
                out.append(f"nyilvánosra nem kerülhet (titok, forrásút vagy oldalazonosító): {pattern.pattern!r}")
    return out


def page_text(repo: Path, ep: Episode) -> str:
    """The topic page's author text: title and body without generated blocks and lesson lines."""
    text = safefs.read_text(repo, ep.page)
    page = frontmatter.split(text)
    body = META_LINE.sub("", markers.BLOCK.sub("", page.body))
    return str(page.meta.get("title", "")) + "\n" + re.sub(r"\n(?:[ \t]*\n)+", "\n\n", body).strip()


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def review_key(repo: Path, ep: Episode, script: dict) -> str:
    return digest({"script": script, "page": page_text(repo, ep)})


def verdict_problems(repo: Path, ep: Episode, script: dict) -> list[str]:
    """Why the release may not start: no accept, an accept with an open `hiba`, or an accept
    given to other content than what is there now (no snapshot, or changed since)."""
    try:
        verdict = read(repo, ep, "verdict.json")
        keys = read(repo, ep, "keys.json", {})
    except ValueError as exc:
        return [f"{ep.folder}: olvashatatlan ítélet vagy kulcs: {exc}"]
    if verdict is None:
        return [f"nincs lektori ítélet: {ep.folder}/verdict.json"]
    found = schema_errors("podcast-verdict", verdict)
    if found:
        return [f"{ep.folder}/verdict.json: {p}" for p in found[:10]]
    if verdict["verdict"] != "accept":
        return [f"a lektor nem fogadta el ({verdict['verdict']}): {ep.folder}/verdict.json"]
    if any(is_error(d) for d in verdict["defects"]):
        return ["az accept mellett `hiba` súlyosságú lelet áll – a lektor javítja"]
    if not isinstance(keys, dict) or not keys.get("key"):
        return [f"nincs pillanatkép (keys.json): sn podcast <tanuló> {ep.subject} {ep.page_stem} --snapshot, "
                "utána a lektor"]
    if keys["key"] != review_key(repo, ep, script):
        return ["az accept nem erre a változatra szól (a forgatókönyv vagy a témalap változott a pillanatkép óta) "
                "– új pillanatkép és megerősítés kell"]
    return []


def verdict(repo: Path, ep: Episode) -> dict:
    return read(repo, ep, "verdict.json")


def host(script: dict) -> str:
    return next(n for n, s in script["speakers"].items() if s["role"] == "host")


def guests(script: dict) -> list[str]:
    return [n for n, s in script["speakers"].items() if s["role"] == "guest"]


def characters(script: dict) -> int:
    return sum(len(t["text"]) for s in script["scenes"] for t in s["turns"])
