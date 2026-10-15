"""Közös fájlformátum; a sorrend mindig a tartalom sorrendje."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT.parents[2]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def encoded(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(encoded(value))
    tmp.replace(path)


def sha(value):
    return hashlib.sha256(
        value if isinstance(value, bytes) else encoded(value)
    ).hexdigest()


def steps(script):
    return [s for scene in script["jelenetek"] for s in scene["lepesek"]]


def roles(step):
    result = []
    for value in [
        step.get("gorget"),
        step.get("kurzor"),
        *step.get("kiemel", []),
        *step.get("allapot", []),
    ]:
        if value and value.get("szereplo") and value["szereplo"] not in result:
            result.append(value["szereplo"])
    return result
