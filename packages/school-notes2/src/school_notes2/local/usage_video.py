"""`sn hasznalat`: saját, végleges és elfogadott használati videó beillesztése."""

import hashlib
import json
import math
import re
import sys
from pathlib import Path

from .. import VERSION
from ..state import safefs
from ..wiki import generate, public
from . import tool_writes
from .podcast import _record_pages, _texts

VIDEO_PACKAGE = Path(__file__).resolve().parents[4] / "video"
sys.path.insert(0, str(VIDEO_PACKAGE))
try:
    from hasznalat.lapok_h import review_key

    PACKAGE_ERROR = None
except ModuleNotFoundError as error:
    PACKAGE_ERROR = f"hiányzik a használativideó-csomag vagy függősége: {error.name} ({VIDEO_PACKAGE})"

ASSET = "wiki/assets/hasznalat"
FILE_PATTERN = re.compile(r"hasznalat-\d{8}\.(mp4|png)")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def work_folder(repo):
    folder = repo / ".school-notes/out/hasznalat"
    choices = sorted(
        p for p in folder.glob("*") if re.fullmatch(r"\d{8}", p.name) and p.is_dir()
    )
    if not choices:
        raise ValueError("nincs használati videó")
    work = choices[-1]
    if not work.resolve().is_relative_to(folder.resolve()) or work.is_symlink():
        raise ValueError("a munkamappa nem a saját átadásmappában van")
    return work


def validate_chapters(receipt):
    duration, chapters = receipt.get("hossz_s"), receipt.get("fejezetek")
    if (
        not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration <= 0
        or not isinstance(chapters, list)
        or not chapters
    ):
        raise ValueError("hibás hossz vagy fejezetlista a nyugtában")
    previous = -1
    for chapter in chapters:
        if not isinstance(chapter, dict):
            raise ValueError("hibás fejezetlista")
        seconds = chapter.get("masodperc")
        if (
            not isinstance(chapter.get("jelenet"), str)
            or not isinstance(seconds, (int, float))
            or not previous <= seconds < duration
        ):
            raise ValueError("hibás fejezetlista")
        previous = seconds


def validate_receipt(local, work, receipt, gate):
    validate_chapters(receipt)
    if receipt.get("template") != VERSION:
        raise ValueError("más eszközverzióval készült; új ellenőrzés kell")
    if receipt.get("csonk") is not False:
        raise ValueError("tesztcsonk nem adható ki")
    if receipt.get("forgatokonyv_sha256") != digest(
        (work / "forgatokonyv-kitoltott.json").read_bytes()
    ):
        raise ValueError("a forgatókönyv megváltozott")
    if (
        not receipt.get("vegleges")
        or receipt.get("tanulo") != local.name
        or not gate.get("zold")
        or gate.get("elonezet")
        or gate.get("nem_mert")
        or any(not f.get("felulbiralva") for f in gate.get("leletek", []))
    ):
        raise ValueError("saját végleges videó és zöld kapu kell")
    if receipt["commit"] != local.git().out("rev-parse", "HEAD").strip():
        raise ValueError("a build nem a jelenlegi HEAD")


def validate_review(work, receipt, gate, verdict):
    key = review_key(work)
    if (
        verdict.get("verdict") != "accept"
        or verdict.get("key") != key
        or receipt.get("key") != key
    ):
        raise ValueError("nincs accept a mostani tartalomra")
    if any(d.get("severity") == "hiba" for d in verdict.get("defects", [])):
        raise ValueError("hibás review")
    if receipt.get("kapu_sha256") != digest((work / "kapu.json").read_bytes()):
        raise ValueError("a kapu megváltozott")
    for name in ("hasznalat.mp4", "hasznalat.png"):
        if digest((work / name).read_bytes()) != receipt["outputs"][name]:
            raise ValueError("eltérő kimenet: " + name)


def preflight(local):
    if PACKAGE_ERROR:
        raise ValueError(PACKAGE_ERROR)
    work = work_folder(local.repo)
    receipt, gate, verdict = [
        json.loads((work / name).read_text())
        for name in ("nyugta.json", "kapu.json", "verdict.json")
    ]
    if not all(isinstance(value, dict) for value in (receipt, gate, verdict)):
        raise ValueError("hibás nyugta, kapu vagy ítélet")
    validate_receipt(local, work, receipt, gate)
    validate_review(work, receipt, gate, verdict)
    names = {
        name: f"hasznalat-{work.name}" + Path(name).suffix
        for name in ("hasznalat.mp4", "hasznalat.png")
    }
    for source, target in names.items():
        rel = f"{ASSET}/{target}"
        if (
            safefs.is_file(local.repo, rel)
            and safefs.read_bytes(local.repo, rel) != (work / source).read_bytes()
        ):
            raise ValueError("ezen a napon már más videó jelent meg")
    return work, receipt, names


def write_assets(repo, work, receipt, names, written):
    evidence = f"docs/evidence/hasznalati-video/{work.name}.json"
    safefs.write_json(repo, evidence, receipt)
    written.append(evidence)
    for source, target in names.items():
        rel = f"{ASSET}/{target}"
        safefs.write_bytes(repo, rel, (work / source).read_bytes())
        written.append(rel)
    record = {
        "source": evidence,
        "source_sha256": digest(safefs.read_bytes(repo, evidence)),
        "outputs": {
            target: {"sha256": receipt["outputs"][source]}
            for source, target in names.items()
        },
    }
    safefs.write_json(repo, f"{ASSET}/render.json", record)
    written.append(f"{ASSET}/render.json")
    for rel in safefs.walk_files(repo, ASSET):
        name = Path(rel).name
        if (
            Path(rel).parent.as_posix() == ASSET
            and FILE_PATTERN.fullmatch(name)
            and name not in names.values()
        ):
            safefs.unlink(repo, rel)
            written.append(rel)


def publish(local, work, receipt, names, out):
    before = _texts(local.repo, ["wiki/index.md"])
    written = []
    try:
        write_assets(local.repo, work, receipt, names, written)
        safefs.write_text(local.repo, "wiki/index.md", generate.root_index(local.repo))
        public.write(local.repo, public.default_rights(local.repo))
        written.append("publication/public.json")
    finally:
        tool_writes.record(local.repo, files=written)
        _record_pages(local.repo, local.git(), before, out)
    local.record("hasznalat", "ok", asset=f"{ASSET}/{names['hasznalat.mp4']}")


def run(local, out=print):
    try:
        work, receipt, names = preflight(local)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        out("STOP: " + str(error))
        return 2
    publish(local, work, receipt, names, out)
    out("Használati videó beillesztve; következő: sn done, commit, sn publish")
    return 0
