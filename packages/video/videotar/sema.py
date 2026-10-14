"""Kis JSON-séma-ellenőrző a naplo-sema.json-hoz (függőség nélkül, mindkét környezetben fut).

Ismeri: type, enum, required, properties, additionalProperties, items, minItems, maxItems,
minimum, minLength, $ref (#/$defs/...). Használat: hibak(adat) -> list[str]; üres lista = megfelel.
"""

from __future__ import annotations

import json
from pathlib import Path

SEMA_UT = Path(__file__).resolve().parent / "naplo-sema.json"
_TIPUS = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def _tipus_ok(x, t: str) -> bool:
    if t == "integer":
        return isinstance(x, int) and not isinstance(x, bool)
    if t == "number":
        return isinstance(x, (int, float)) and not isinstance(x, bool)
    return isinstance(x, _TIPUS[t])


def _ellenoriz(x, s: dict, gyoker: dict, ut: str, hibak: list) -> None:
    if "$ref" in s:
        s = gyoker["$defs"][s["$ref"].split("/")[-1]]
    if "type" in s:
        tipusok = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(_tipus_ok(x, t) for t in tipusok):
            hibak.append(f"{ut}: típus {type(x).__name__}, várt {s['type']}")
            return
    if "enum" in s and x not in s["enum"]:
        hibak.append(f"{ut}: {x!r} nincs a {s['enum']} között")
    if isinstance(x, (int, float)) and "minimum" in s and x < s["minimum"]:
        hibak.append(f"{ut}: {x} < {s['minimum']}")
    if isinstance(x, str) and len(x) < s.get("minLength", 0):
        hibak.append(f"{ut}: üres szöveg")
    if isinstance(x, list):
        if len(x) < s.get("minItems", 0) or len(x) > s.get("maxItems", len(x)):
            hibak.append(f"{ut}: {len(x)} elem")
        if "items" in s:
            for i, e in enumerate(x):
                _ellenoriz(e, s["items"], gyoker, f"{ut}[{i}]", hibak)
    if isinstance(x, dict):
        for k in s.get("required", []):
            if k not in x:
                hibak.append(f"{ut}: hiányzik a(z) {k!r}")
        props = s.get("properties", {})
        for k, v in x.items():
            if k in props:
                _ellenoriz(v, props[k], gyoker, f"{ut}.{k}", hibak)
            elif s.get("additionalProperties") is False:
                hibak.append(f"{ut}: ismeretlen mező {k!r}")
            elif isinstance(s.get("additionalProperties"), dict):
                _ellenoriz(v, s["additionalProperties"], gyoker, f"{ut}.{k}", hibak)


def hibak(adat, def_nev: str | None = None, sema: dict | None = None) -> list[str]:
    """A séma szerinti hibák; def_nev: a $defs egy eleme (például "idoterv", "szavak") a gyökér helyett."""
    gyoker = sema or json.loads(SEMA_UT.read_text(encoding="utf-8"))
    s = gyoker["$defs"][def_nev] if def_nev else gyoker
    ki: list[str] = []
    _ellenoriz(adat, s, gyoker, "$", ki)
    return ki
