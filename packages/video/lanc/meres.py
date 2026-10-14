"""`--meres`: könyvelés, szerepenkénti token, gépi idő és díj, API-egyenérték → meres.md (terv 7. pont).

Csak a videó szerepei számítanak: videoiro és videolektor (Claude-ügynök vagy Codex-munkamenet). A
fejlesztő-, review- és egyéb ügynök akkor sem, ha az OUT-mappát megnevezi.
Melyik videóé egy átirat (tartalomból, determinisztikusan, `video_kulcs`): az első feladatüzenet kitöltéséből
(író: „Tanuló: …”, „Tantárgy: …”, „Lap, rész: <lap>, <n>”; lektor: „Tanuló: …”, „Tantárgy, lap, rész:
wiki/<tantárgy>/<lap>.md, <n>”); kitöltés nélkül az átirat első videó-hivatkozásából (abszolút vagy ~-os
OUT-út, `video.sh <tanuló> <tantárgy> <lap>` hívás, vagy relatív OUT-út, ennél a tanuló a sor `cwd`-jéből).
Más videó mappájának vagy hívásának későbbi említése (minta, összevetés) nem sorolja át. A „halmazok-1” nem
„halmazok-12”.
Claude-ügynök: a ~/.claude/projects/*/<munkamenet>/subagents/agent-*.jsonl közül az, amelyiknek .meta.json
`agentType`-ja videós szerep, és a videója ez. Egy API-hívás több sorban is megjelenik (tartalomblokkonként); a
`requestId` szerint egyszer számít.
Vezérlő (`vezerlo`): az ügynökök munkamenetének fő .jsonl-jéből csak a videó menetének időablaka: az ablak a videó
ügynökeinek első és utolsó sora, a vezérlő e videóra szóló `video.sh`-hívásai (a --meres nélkül) és a videó
lánc-futásai (futasok.json, a munkamenet első és utolsó időbélyege közé vágva) közt; a munkamenet minden videójának
ablaka ugyanígy készül. Ha ugyanabban a munkamenetben más videók ablaka is fedi a hívást (párhuzamos
videók), a hívás tokenje egyenlően oszlik közöttük (k videónál 1/k). A falióra az ablak hossza, a tulajdonosi
üzenetre váró szakaszok nélkül.
Codex-munkamenet: a ~/.codex/sessions/**/rollout-*.jsonl közül az, amelyiknek első feladatüzenete (az
AGENTS.md és a rendszerszöveg után az első felhasználói üzenet) videós szerepfájlt nevez meg
(`szerepek/videoiro.md`), és a videója (lásd fent) ez. Csak az OUT-mappa fájljainak idősávjába eső
munkamenetek (módosítva a legrégebbi előtt legfeljebb 1 órával; a fájlnévben álló indulás a legújabb után
legfeljebb 1 órával); üres OUT-mappánál nincs keresés (a tár gigabájtos). Token a `token_count` eseményekből
(az utolsó `total_token_usage`); a szerep „ (Codex)” jelzéssel. API-egyenérték nincs (Codex-keret): „–”.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

PROJEKTEK = Path.home() / ".claude" / "projects"
CODEX = Path.home() / ".codex" / "sessions"
VIDEO_SZEREPEK = {"videoiro", "videolektor"}
CODEX_RAHAGYAS_S = 3600     # a Codex-munkamenet idősávja az OUT-mappa fájljaihoz képest (lásd fent)
# USD / millió token, Opus 5.5 (review-hatekonysag.md): bemenet, cache-olvasás, cache-írás (5 p, 1 ó), kimenet
AR = {"input": 4.0, "cache_read": 0.20, "cache_write_5m": 5.0, "cache_write_1h": 8.0, "output": 20.0}


def _ido(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _szoveg(uzenet) -> str:
    c = (uzenet or {}).get("content")
    if isinstance(c, str):
        return c
    return " ".join(b.get("text", "") for b in c or [] if isinstance(b, dict) and b.get("type") == "text")


def _kepek(uzenet) -> int:
    n = 0
    for b in (uzenet or {}).get("content") or []:
        if isinstance(b, dict):
            n += b.get("type") == "image"
            if b.get("type") == "tool_result" and isinstance(b.get("content"), list):
                n += sum(isinstance(x, dict) and x.get("type") == "image" for x in b["content"])
    return n


def atirat(ut: Path, vezerlo: bool = False, ablak: tuple[datetime, datetime] | None = None,
           suly=None) -> dict:
    """Egy átirat összesítője: hívás, token (bemenet, cache-olvasás, cache-írás), kimenet, USD, kontextus, kép, idő.
    `ablak`: csak az ebbe eső hívások és sorok (a vezérlő egy videóra); `suly(ido)`: a hívás súlya (osztás)."""
    hivasok, sorok = {}, []
    for sor in ut.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(sor)
        except json.JSONDecodeError:
            continue
        if not d.get("timestamp"):
            continue
        t = _ido(d["timestamp"])
        if ablak and not ablak[0] <= t <= ablak[1]:
            continue
        sorok.append(d)
        u = (d.get("message") or {}).get("usage") if d.get("type") == "assistant" else None
        if u:
            kulcs = d.get("requestId") or d.get("uuid")
            regi = hivasok.get(kulcs)
            if regi is None or u.get("output_tokens", 0) >= regi[0].get("output_tokens", 0):
                hivasok[kulcs] = (u, min(t, regi[1]) if regi else t)
    o = {"hivas": 0, "input": 0, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0, "output": 0,
         "csucs": 0, "zaro": 0, "kep": sum(_kepek(d.get("message")) for d in sorok if d.get("type") == "user")}
    hiv = 0.0
    for u, t in sorted(hivasok.values(), key=lambda x: x[1]):
        w = suly(t) if suly else 1.0
        cc = u.get("cache_creation") or {}
        w1 = cc.get("ephemeral_1h_input_tokens", 0)
        w5 = cc.get("ephemeral_5m_input_tokens", u.get("cache_creation_input_tokens", 0) - w1)
        ctx = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + w5 + w1
        hiv += w
        o["input"] += w * u.get("input_tokens", 0)
        o["cache_read"] += w * u.get("cache_read_input_tokens", 0)
        o["cache_write_5m"] += w * w5
        o["cache_write_1h"] += w * w1
        o["output"] += w * u.get("output_tokens", 0)
        o["csucs"], o["zaro"] = max(o["csucs"], ctx), ctx
    for k in ("input", "cache_read", "cache_write_5m", "cache_write_1h", "output"):
        o[k] = round(o[k])
    o["hivas"] = round(hiv)
    o["beolvasott"] = o["input"] + o["cache_read"] + o["cache_write_5m"] + o["cache_write_1h"]
    o["usd"] = round(sum(o[k] * AR[k] for k in AR) / 1e6, 2)
    idok = sorted(_ido(d["timestamp"]) for d in sorok)
    o["falio_s"] = (idok[-1] - idok[0]).total_seconds() if idok else 0
    if ablak:
        o["falio_s"] = (ablak[1] - ablak[0]).total_seconds()
    o["kezd"] = idok[0].isoformat() if idok else ""
    o["veg"] = idok[-1].isoformat() if idok else ""
    o["tulajdonos_uzenet"], o["varakozas_s"] = 0, 0.0
    if vezerlo:
        sorok.sort(key=lambda d: d["timestamp"])
        for elozo, d in zip(sorok, sorok[1:]):
            m = d.get("message") or {}
            if (d.get("type") == "user" and not d.get("isMeta") and _szoveg(m).strip()
                    and not _szoveg(m).lstrip().startswith(("<task-notification", "<system-reminder"))
                    and not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in m.get("content") or [])):
                o["tulajdonos_uzenet"] += 1
                o["varakozas_s"] += (_ido(d["timestamp"]) - _ido(elozo["timestamp"])).total_seconds()
    return o


# --- melyik videóé ------------------------------------------------------------------------------------

LAP = r"([a-z0-9][a-z0-9-]*-\d+)(?![\w-])"
KITOLTES_IRO = re.compile(r"Tanuló:\s*(\w+)[\s\S]*?Tantárgy:\s*([\w-]+)[\s\S]*?Lap, rész:\s*([\w-]+),\s*(\d+)")
KITOLTES_LEKTOR = re.compile(r"Tanuló:\s*(\w+)[\s\S]*?Tantárgy, lap, rész:\s*(?:wiki/)?([\w-]+)/([\w-]+)(?:\.md)?,\s*(\d+)")
HIVAS = re.compile(r"video\.sh\s+(\w+)\s+([\w-]+)\s+" + LAP)
OUT_ABS = re.compile(r"school-notes-(\w+)-active/\.school-notes/out/video/([\w-]+)/" + LAP)
OUT_REL = re.compile(r"\.school-notes/out/video/([\w-]+)/" + LAP)
CWD = re.compile(r'"cwd":\s*"[^"]*school-notes-(\w+)-active')


def kitoltes_video(szoveg: str) -> tuple | None:
    """A kitöltés videója (tanuló, tantárgy, <lap>-<n>), vagy None."""
    for m in (KITOLTES_LEKTOR.search(szoveg), KITOLTES_IRO.search(szoveg)):
        if m:
            return m.group(1), m.group(2), f"{m.group(3)}-{m.group(4)}"
    return None


def hivatkozas(sor: str) -> tuple | None:
    """Egy sor első videó-hivatkozása (tanuló vagy None, tantárgy, <lap>-<n>): video.sh-hívás, abszolút OUT-út,
    relatív OUT-út (a tanuló a sor cwd-jéből). Több találatnál a sorban előbb kezdődő (az abszolút út a benne
    álló relatív előtt kezdődik)."""
    jeloltek = [(m.start(), (m.group(1), m.group(2), m.group(3))) for r in (HIVAS, OUT_ABS) for m in r.finditer(sor)]
    c = CWD.search(sor)
    jeloltek += [(m.start(), (c.group(1) if c else None, m.group(1), m.group(2))) for m in OUT_REL.finditer(sor)]
    return min(jeloltek, key=lambda x: x[0])[1] if jeloltek else None


def video_kulcs(sorok) -> tuple | None:
    """Claude-átirat videója: az első felhasználói üzenet kitöltéséből, különben az első hivatkozásból (a sorok
    fájlsorrendben)."""
    elso = True
    for sor in sorok:
        if elso:
            try:
                d = json.loads(sor)
            except json.JSONDecodeError:
                d = {}
            if d.get("type") == "user":
                elso = False
                k = kitoltes_video(_szoveg(d.get("message")))
                if k:
                    return k
        h = hivatkozas(sor)
        if h:
            return h
    return None


def egyezik(k: tuple | None, video: tuple) -> bool:
    """A kulcs ez a videó-e (a hiányzó tanuló a relatív hivatkozásnál bármelyik tanuló)."""
    return bool(k) and k[1:] == video[1:] and (k[0] is None or video[0] is None or k[0] == video[0])


def _video(out: Path, tanulo: str | None) -> tuple:
    return tanulo, out.parts[-2], out.name


def video_ugynokei(projektek: Path = PROJEKTEK, munkamenet: Path | None = None) -> list[dict]:
    """A videós szerepű Claude-ügynökök (minden munkamenetből, vagy csak egyből) a videójukkal (`video`)."""
    minta = f"{munkamenet.name}/subagents/agent-*.jsonl" if munkamenet else "*/*/subagents/agent-*.jsonl"
    ki = []
    for ut in sorted((munkamenet.parent if munkamenet else projektek).glob(minta)):
        meta = ut.with_suffix(".meta.json")
        try:
            szerep = json.loads(meta.read_text()).get("agentType", "?") if meta.exists() else "?"
        except (OSError, json.JSONDecodeError):
            continue
        if szerep not in VIDEO_SZEREPEK:
            continue
        with open(ut, encoding="utf-8", errors="replace") as f:
            k = video_kulcs(f)
        ki.append({"szerep": szerep, "fajl": ut, "munkamenet": ut.parent.parent, "video": k})
    return ki


def ugynokok(out: Path, projektek: Path = PROJEKTEK, codex: Path | None = CODEX, tanulo: str | None = None) -> list[dict]:
    """A videó ügynökei időrendben: videós szerepű Claude-ügynökök és Codex-munkamenetek, amelyeknek a videója
    (kitöltés, különben első hivatkozás) ez."""
    out = Path(out)
    video = _video(out, tanulo)
    ki = [{**x, **atirat(x["fajl"])} for x in video_ugynokei(projektek) if egyezik(x["video"], video)]
    ki += codex_munkamenetek(out, codex, video) if codex else []
    return sorted(ki, key=lambda a: (a["kezd"], str(a["fajl"])))


def _codex_indulas(ut: Path) -> float | None:
    """A rollout-fájlnév indulási ideje (helyi idő) epoch-másodpercben."""
    m = re.match(r"rollout-(\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d)", ut.name)
    return datetime.strptime(m.group(1), "%Y-%m-%dT%H-%M-%S").timestamp() if m else None


def _codex_szoveg(sor: str) -> str:
    try:
        p = json.loads(sor).get("payload") or {}
    except json.JSONDecodeError:
        return ""
    return " ".join(c.get("text", "") for c in p.get("content") or [] if isinstance(c, dict))


def _codex_szerep(sor: str) -> str | None:
    """Az első feladatüzenet szerepe: "" ha a sor nem feladatüzenet, None ha az, de nem videós szerep."""
    if '"role"' not in sor or '"user"' not in sor:
        return ""
    try:
        p = json.loads(sor).get("payload") or {}
    except json.JSONDecodeError:
        return ""
    if p.get("type") != "message" or p.get("role") != "user":
        return ""
    szoveg = " ".join(c.get("text", "") for c in p.get("content") or [] if isinstance(c, dict))
    if not szoveg.strip() or szoveg.lstrip().startswith(("#", "<")):      # AGENTS.md, környezet, rendszerszöveg
        return ""
    m = re.search(r"szerepek/([\w-]+)\.md", szoveg)
    return m.group(1) if m and m.group(1) in VIDEO_SZEREPEK else None


def codex_munkamenetek(out: Path, codex: Path, video: tuple) -> list[dict]:
    idok = [p.stat().st_mtime for p in out.iterdir() if p.is_file()] if out.is_dir() else []
    if not idok or not codex.is_dir():
        return []
    also, felso = min(idok) - CODEX_RAHAGYAS_S, max(idok) + CODEX_RAHAGYAS_S
    ki = []
    for ut in sorted(codex.glob("**/rollout-*.jsonl")):
        indul = _codex_indulas(ut)
        if ut.stat().st_mtime < also or (indul is not None and indul > felso):
            continue
        szerep, k = "", None
        with open(ut, encoding="utf-8", errors="replace") as f:
            for sor in f:
                if szerep == "":
                    szerep = _codex_szerep(sor)
                    if szerep is None:
                        break
                    if szerep:
                        k = kitoltes_video(_codex_szoveg(sor))
                        if k:
                            break
                    continue
                k = hivatkozas(sor)
                if k:
                    break
        if szerep and egyezik(k, video):
            o = codex_atirat(ut.read_text(encoding="utf-8", errors="replace"))
            ki.append({"szerep": f"{szerep} (Codex)", "fajl": ut, "munkamenet": None, **o})
    return ki


def codex_atirat(szoveg: str) -> dict:
    """Egy Codex-munkamenet összesítője az `atirat` mezőivel. A `token_count` összesítője halmozott (az
    utolsó a teljes); a bemenet a gyorsítótárból olvasottat is tartalmazza, itt külön mező."""
    ossz, utolso, csucs, hivas, kep, idok, latott = {}, {}, 0, 0, 0, [], set()
    for sor in szoveg.splitlines():
        try:
            d = json.loads(sor)
        except json.JSONDecodeError:
            continue
        if d.get("timestamp"):
            idok.append(_ido(d["timestamp"]))
        p = d.get("payload") or {}
        if p.get("type") == "token_count" and p.get("info"):
            t = p["info"].get("total_token_usage") or {}
            if t.get("total_tokens", 0) in latott:     # ugyanaz az állás újra (díjkeret-frissítés): nem új hívás
                continue
            latott.add(t.get("total_tokens", 0))
            hivas += 1
            ossz, utolso = t, p["info"].get("last_token_usage") or {}
            csucs = max(csucs, utolso.get("input_tokens", 0))
        elif d.get("type") == "response_item" and p.get("type") == "message" and p.get("role") == "user":
            tartalom = [c for c in p.get("content") or [] if isinstance(c, dict)]
            kep += sum(c.get("type") == "input_image" for c in tartalom)
    o = {"hivas": hivas, "input": ossz.get("input_tokens", 0) - ossz.get("cached_input_tokens", 0),
         "cache_read": ossz.get("cached_input_tokens", 0), "cache_write_5m": ossz.get("cache_write_input_tokens", 0),
         "cache_write_1h": 0, "output": ossz.get("output_tokens", 0), "csucs": csucs,
         "zaro": utolso.get("input_tokens", 0), "kep": kep, "usd": None}
    o["beolvasott"] = o["input"] + o["cache_read"] + o["cache_write_5m"]
    idok.sort()
    o["falio_s"] = (idok[-1] - idok[0]).total_seconds() if idok else 0
    o["kezd"] = idok[0].isoformat() if idok else ""
    o["veg"] = idok[-1].isoformat() if idok else ""
    o["tulajdonos_uzenet"], o["varakozas_s"] = 0, 0.0
    return o


# --- a vezérlő egy videóra ------------------------------------------------------------------------------

def vezerlo_hivasai(ut: Path) -> tuple[dict[tuple, list[datetime]], tuple[datetime, datetime] | None]:
    """A vezérlő `video.sh`-hívásai videónként (a hívás és a válasz ideje, a --meres nélkül), és a munkamenet
    idősávja (az első és az utolsó időbélyeg)."""
    nyitott, ki, elso, utolso = {}, {}, None, None
    for sor in ut.read_text(encoding="utf-8", errors="replace").splitlines():
        m_ido = re.search(r'"timestamp":\s*"([^"]+)"', sor)
        if m_ido:
            t = _ido(m_ido.group(1))
            elso, utolso = min(elso or t, t), max(utolso or t, t)
        if "video.sh" not in sor and "tool_result" not in sor:
            continue
        try:
            d = json.loads(sor)
        except json.JSONDecodeError:
            continue
        if not d.get("timestamp"):
            continue
        t = _ido(d["timestamp"])
        for b in (d.get("message") or {}).get("content") or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                parancs = str((b.get("input") or {}).get("command", ""))
                for m in HIVAS.finditer(parancs):
                    if "--meres" not in parancs[m.end():].split("\n")[0].split("&&")[0].split(";")[0]:
                        k = (m.group(1), m.group(2), m.group(3))
                        ki.setdefault(k, []).append(t)
                        nyitott.setdefault(b.get("id"), []).append(k)
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in nyitott:
                for k in nyitott.pop(b["tool_use_id"]):
                    ki[k].append(t)
    return ki, ((elso, utolso) if elso else None)


def _unio_kulcs(k: tuple, kulcsok) -> tuple:
    """A tanuló nélküli (relatív) kulcs a tanulós párjához (ha egyértelmű)."""
    if k[0] is None:
        par = sorted({x for x in kulcsok if x and x[0] and x[1:] == k[1:]})
        if len(par) == 1:
            return par[0]
    return k


def _sajat_kulcs(kulcsok, video: tuple) -> tuple | None:
    """A videó kulcsa: előbb a pontos (tanulós), csak ha az nincs, a tanuló nélküli egyezés."""
    if video in kulcsok:
        return video
    return next((k for k in sorted(kulcsok, key=lambda k: tuple(x or "" for x in k)) if egyezik(k, video)), None)


def _futasok(out: Path, tanulo: str | None, k: tuple) -> list[dict]:
    """A k videó futasok.json-ja: ugyanannak a tanulónak a videómappájából, más tanulónál a szomszéd tanulói repóból
    (school-notes-<tanuló>-active); ha nem található, üres."""
    video_mappa = out.parents[1]
    if k[0] in (None, tanulo):
        m = video_mappa / k[1] / k[2]
    else:
        repo = out.parents[4]
        if not re.fullmatch(r"school-notes-\w+-active", repo.name):
            return []
        m = repo.parent / f"school-notes-{k[0]}-active" / ".school-notes" / "out" / "video" / k[1] / k[2]
    try:
        return json.loads((m / "futasok.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _futas_idok(futasok: list[dict], sav: tuple[datetime, datetime]) -> list[datetime]:
    """A lánc-futások kezdete és vége, a munkamenet idősávjára vágva (más munkamenet futása nem nyújtja az ablakot)."""
    ki = []
    for f in futasok:
        if not f.get("ido") or f.get("mod") == "meres":
            continue
        veg = _ido(f["ido"])
        kezd = veg - timedelta(seconds=float(f.get("s") or 0))
        if veg < sav[0] or kezd > sav[1]:
            continue
        ki += [max(kezd, sav[0]), min(veg, sav[1])]
    return ki


def vezerlo(out: Path, tanulo: str | None, ugy: list[dict], futasok: list[dict] | None = None,
            projektek: Path = PROJEKTEK) -> list[dict]:
    """A vezérlő munkameneteinek összesítője csak erre a videóra: munkamenetenként minden videó ablaka ugyanúgy készül
    (Claude-ügynökei, a vezérlő video.sh-hívásai, a lánc-futásai a munkamenet idősávjára vágva), és a hívás tokenje
    1/k, ha k videó ablaka fedi. `futasok`: ennek a videónak a futásai (különben a mappájából). A sorrend a
    munkamenet útja szerint."""
    out = Path(out)
    video = _video(out, tanulo)
    ki = []
    for mm in sorted({x["munkamenet"] for x in ugy if x.get("munkamenet")}):
        fo = mm.with_suffix(".jsonl")
        if not fo.exists():
            continue
        hivasok, sav = vezerlo_hivasai(fo)
        if not sav:
            continue
        nyers: dict[tuple, list[datetime]] = {}
        for x in video_ugynokei(projektek, mm):
            if x["video"]:
                o = atirat(x["fajl"])
                if o["kezd"]:
                    nyers.setdefault(x["video"], []).extend([_ido(o["kezd"]), _ido(o["veg"])])
        for k, ts in hivasok.items():
            nyers.setdefault(k, []).extend(ts)
        idok: dict[tuple, list[datetime]] = {}
        for k in sorted(nyers, key=lambda k: tuple(x or "" for x in k)):
            idok.setdefault(_unio_kulcs(k, nyers), []).extend(nyers[k])
        for k in sorted(idok, key=lambda k: tuple(x or "" for x in k)):
            sajat = k == video or (k[0] is None and egyezik(k, video))
            idok[k] += _futas_idok(futasok if sajat and futasok is not None else _futasok(out, tanulo, k), sav)
        ablakok = {k: (min(v), max(v)) for k, v in idok.items() if v}
        kulcs = _sajat_kulcs(ablakok, video)
        if kulcs is None:
            continue
        sajat_ablak = ablakok[kulcs]

        def suly(t, ablakok=ablakok):
            return 1.0 / max(1, sum(a <= t <= b for a, b in ablakok.values()))
        o = atirat(fo, vezerlo=True, ablak=sajat_ablak, suly=suly)
        o["ablak"] = [sajat_ablak[0].isoformat(), sajat_ablak[1].isoformat()]
        o["parhuzamos"] = sorted(f"{k[0] or '?'}/{k[1]}/{k[2]}" for k, (a, b) in ablakok.items()
                                 if k != kulcs and a <= sajat_ablak[1] and b >= sajat_ablak[0])
        ki.append(o)
    return ki


def ledger_osszeg(calls: list[dict]) -> dict:
    konyvelt = sum((Decimal(str(c["cost_usd"])) for c in calls if c.get("cost_usd") is not None), Decimal(0))
    foglalt = sum((Decimal(str(c.get("reserved_usd", 0))) for c in calls if c.get("cost_usd") is None), Decimal(0))
    return {"konyvelt": konyvelt, "foglalt": foglalt, "hivas": len(calls),
            "tts": sum(c["kind"] == "speech" for c in calls), "whisper": sum(c["kind"] == "transcription" for c in calls)}


def tabla(sorok: list[tuple[str, dict]]) -> list[str]:
    ki = ["| szerep | hívás | beolvasott | cache-olv. | cache-írás | kimenet | API-USD | csúcs | záró | kép | idő |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for nev, o in sorok:
        ki.append(f"| {nev} | {o['hivas']} | {o['beolvasott'] / 1e6:.2f} M | {o['cache_read'] / 1e6:.2f} M | "
                  f"{(o['cache_write_5m'] + o['cache_write_1h']) / 1e6:.2f} M | {o['output'] / 1e3:.0f} e | "
                  f"{'–' if o['usd'] is None else format(o['usd'], '.2f')} | {o['csucs'] / 1e3:.0f} e | {o['zaro'] / 1e3:.0f} e | {o['kep']} | "
                  f"{(o['falio_s'] - o.get('varakozas_s', 0)) / 60:.0f} p |")
    return ki


def osszead(lista: list[dict]) -> dict:
    kulcsok = ["hivas", "input", "cache_read", "cache_write_5m", "cache_write_1h", "output", "beolvasott", "kep",
               "falio_s", "varakozas_s"]
    o = {k: sum(a.get(k, 0) for a in lista) for k in kulcsok}
    usd = [a["usd"] for a in lista if a.get("usd") is not None]
    o["usd"] = round(sum(usd), 2) if usd else None          # Codex: nincs API-egyenérték
    o["csucs"] = max((a["csucs"] for a in lista), default=0)
    o["zaro"] = 0
    return o
