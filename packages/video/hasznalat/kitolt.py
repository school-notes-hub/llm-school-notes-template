"""Séma, kitöltés, átmenetek és a felület szövegszerződése."""

import copy
import re

import jsonschema

from .adatok import ROOT, TEMPLATE, read, roles, steps


def article(text):
    if re.match(r"(?i)^az?\s", text):
        return ""
    return "az" if text[:1].casefold() in "aáeéiíoóöőuúüű" else "a"


def clean(text):
    return re.sub(r"^[^\w]+", "", text).strip()


def speakable(text):
    text = re.sub(r"\[\[.*?\]\]", "hely", text)
    return not re.search(
        r"[\d%§]|\b(?!PDF\b)[A-ZÁÉÍÓÖŐÚÜŰ]{2,}\b|\b\w+\.(?=\s+\w)", text
    )


def validate(script, actors):
    jsonschema.validate(script, read(ROOT / "forgatokonyv.schema.json"))
    seen = set()
    for step in steps(script):
        if step["id"] in seen:
            raise ValueError("ismételt lépés: " + step["id"])
        seen.add(step["id"])
        for role in roles(step) + ([step["csak_ha"]] if step.get("csak_ha") else []):
            if role not in actors:
                raise ValueError("ismeretlen szerep: " + role)
        for cue in [
            *step.get("kiemel", []),
            *step.get("allapot", []),
            step.get("kurzor", {}),
        ]:
            if cue.get("horgony") and "{" + cue["horgony"] + "}" not in step["text"]:
                raise ValueError(step["id"] + ": hiányzó horgony " + cue["horgony"])
        if not speakable(step["text"]):
            raise ValueError(step["id"] + ": nem kimondható szöveg")


def values_for(selection):
    values = {
        k: clean(selection[k]["title"]) for k in ("tantargy", "lecke", "osszefoglalo")
    }
    values["fejezet"] = selection["lecke"].get("chapterTitle", "")
    values["temavalaszto"] = selection["kezdolap"].get("usageThemeLabel", "")
    values["projekt"] = selection.get("projekt", {}).get("navigationLabel") or selection.get("projekt", {}).get("title", "")
    for key in ("tantargy", "fejezet"):
        values["a_" + key] = (article(values[key]) + " " + values[key]).strip()
        values["A_" + key] = values["a_" + key][:1].upper() + values["a_" + key][1:]
    words = re.findall(r"\w+", values["lecke"])
    values["keresoszo"] = next((w.casefold() for w in words if len(w) > 3), "")
    if not values["keresoszo"]:
        raise ValueError("nincs legalább négybetűs keresőszó")
    return values


def substitute(value, values):
    if isinstance(value, str):
        # Only template articles immediately before a filled title; anchors stay intact.
        value = re.sub(
            r"\b([Aa]z?) (\{?)(\[\[(\w+)\]\])",
            lambda m: ((article(values[m[4]]).capitalize() if m[1][0].isupper()
                        else article(values[m[4]])) + " " if article(values[m[4]]) else "")
            + m[2] + m[3], value,
        )
        return re.sub(r"\[\[(\w+)\]\]", lambda m: values[m[1]], value)
    if isinstance(value, list):
        return [substitute(v, values) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v, values) for k, v in value.items()}
    return value


def transition_seconds(step, previous):
    seconds = 1.6 if step.get("gorget") else 0
    for action in step.get("allapot", []):
        if not action.get("horgony"):
            seconds += (
                (len(action.get("text", "")) * 0.1 + 1.1)
                if action["muvelet"] == "gepel"
                else 0.6
                if action["muvelet"] == "esc"
                else 0.9
            )
    if previous and (
        previous["url"] != step["url"] or previous["nezet"] != step["nezet"]
    ):
        seconds += 0.3
    return round(seconds, 3)


def prepare_step(step, scene, selection, previous):
    page = step.get("lap", previous["lap"] if previous else "kezdolap")
    camera = step.get("kamera", previous["kamera"] if previous else "teljes")
    step.update(
        lap=page, kamera=camera, nezet=scene["nezet"], url=selection[page]["url"]
    )
    step["atmenet_s"] = transition_seconds(step, previous)
    if previous:
        click = 0.9 if previous.get("kurzor", {}).get("kattint") else 0
        previous["szunet"] = max(previous.get("szunet", 0.5), step["atmenet_s"] + click)


def fill(script, selection, available=None):
    values = values_for(selection)
    out = substitute(copy.deepcopy(script), values)
    previous = None
    for scene in out["jelenetek"]:
        scene["lepesek"] = [
            s
            for s in scene["lepesek"]
            if available is None or not s.get("csak_ha") or s["csak_ha"] in available
        ]
        for step in scene["lepesek"]:
            prepare_step(step, scene, selection, previous)
            previous = step
    actors = substitute(read(ROOT / "szereplok.json"), values)
    actors["cimke-nelkuli"]["forras_szovegek"] = selection["lecke"].get("usageClassroomParagraphs", [])
    return out, actors


def contract(root=TEMPLATE, contract=None):
    definition = contract if contract is not None else read(ROOT / "felulet.json")
    return [
        row
        for row in definition["szovegek"]
        if row["text"] not in (root / row["file"]).read_text()
    ]
