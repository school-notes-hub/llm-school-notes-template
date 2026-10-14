"""A lektor tömör időtáblája (tabla.txt, ≤ 10 e token) és a narráció mondatai (szoveg.md).

terv-menet.md 5. pont, 5. tétel: fejléc a kapu sorával, figyelmeztetésekkel, kivételekkel, kapcsolókkal,
kézi és becsült/gyanús szóidőkkel; utána lépésenként egy sor: idő | mondat | szó | kép (megjelenés,
mozgássáv, keretrajzolás a vonatkozással, „(szóra)”) | álló idő | leletek.
"""

from __future__ import annotations

import re

from kapu import Munka, allo_s, ido, jeltelen, kulcslepes, szoveg_ir, tized

MAX_KEP = 420     # a kép-oszlop legfeljebb ennyi karakter lépésenként


def _termeszetes(s: str):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s)]


def nevek(ns) -> str:
    ns = sorted(set(ns), key=_termeszetes)
    return ", ".join(ns) if len(ns) <= 3 else f"{ns[0]}…{ns[-1]} ({len(ns)})"


def _rel(k: int, kezd: int, fps: float) -> str:
    return f"+{tized((k - kezd) / fps)}"


def kep_oszlop(mu: Munka, l: dict) -> str:
    fps, kezd = mu.fps, l["kezd_kocka"]
    ev = []   # (kocka, sorrend, szöveg)
    csop: dict[tuple, list] = {}
    for e in l["megjelenik"]:
        csop.setdefault((e["kocka"], e.get("csoport") or e["obj"]), []).append(e)
    for (k, c), es in csop.items():
        es.sort(key=lambda e: e["obj"])
        a = mu.attr.get(es[0]["obj"], {})
        ref = sorted({r for e in es for r in (mu.attr.get(e["obj"], {}).get("vonatkozik") or [])})
        tart = " ".join(f"„{e['tartalom'][:24]}”" for e in es if e.get("tartalom"))
        nev = es[0]["obj"] if len(es) == 1 else f"{c}[{len(es)}]"
        kot = {e.get("kotes") for e in es}
        jel = " (szóra)" if "szora" in kot else " (horgony)" if "horgony" in kot else ""
        if any(e["ok"] == "tartalom" for e in es):
            nev = "→ " + nev
        s = f"{_rel(k, kezd, fps)} {nev}{' ' + tart if tart else ''}"
        if ref:
            kat = next((e["kat"] for e in es if mu.attr.get(e["obj"], {}).get("vonatkozik")), es[0]["kat"])
            s = f"{_rel(k, kezd, fps)} {kat} {nev}{' ' + tart if tart else ''} ← {nevek(ref)}"
        s += jel
        for kap in ("ra", "kivul", "szamellenorzes"):
            if a.get(kap):
                s += f" [{kap}=„{a[kap][:30]}”]"
        ev.append((k, 0, s))
    for fajta, cim in (("mozog", "mozog"), ("atalakul", "átalakul")):
        sav: dict[tuple, list] = {}
        for s in l[fajta]:
            sav.setdefault((s["tol"], s["ig"]), []).append(s["obj"])
        for (t0, t1), ns in sav.items():
            ev.append((t0, 1, f"{_rel(t0, kezd, fps)}–{tized((t1 - kezd) / fps)} {cim} {nevek(ns)}"))
    for fajta, cim in (("szinvaltas", "szín"), ("eltunik", "ki")):
        g: dict[int, list] = {}
        for e in l[fajta]:
            g.setdefault(e["kocka"], []).append(e["obj"])
        for k, ns in g.items():
            ev.append((k, 2 if fajta == "szinvaltas" else 3, f"{_rel(k, kezd, fps)} {cim} {nevek(ns)}"))
    s = " · ".join(x[2] for x in sorted(ev))
    return (s[:MAX_KEP - 1] + "…") if len(s) > MAX_KEP else (s or "–")


def szo_oszlop(mu: Munka, l: dict) -> str:
    fps, kezd = mu.fps, l["kezd_kocka"] / mu.fps
    kotott = {e.get("kotes_szo") for e in l["megjelenik"] if e.get("kotes_szo")}
    kotott |= set(mu.tmap.get(l["id"], {}).get("horgonyok", {}))
    r = []
    for w in mu.szavak(l["id"]):
        if w.get("ertek") is not None or w["szo"] in kotott:
            jel = "" if w.get("forras") in (None, "whisper") else f" ({w['forras']})"
            r.append(f"{w['szo']} +{tized(w['szo_s'] - kezd)}{jel}")
    return " · ".join(r) or "–"


def ir(mu: Munka, k: dict) -> str:
    fps = mu.fps
    ls = k["leletek"]
    sz = k["szamok"]
    fej = [f"{k['jelenet']} · {mu.minoseg if mu.naplo else '?'} · {len(mu.tl)} lépés · {ido(mu.terv['kocka_osszes'] / fps)} · "
           f"KAPU: {'ZÖLD' if k['zold'] else 'PIROS'} – {sz['hiba']} hiba, {sz['figy']} figyelmeztetés",
           k["allapot"]]

    def lsor(x, el=""):
        return f"{el}{x['kod']} {x['lepes'] or '–'} {x['obj'] or '–'}: {x['uzenet']}"
    for cim, felt in (("HIBA", lambda x: x["sulyossag"] == "hiba" and not x.get("teves_hiba") and not x.get("felulbiralva")),
                      ("TÉVES HIBA?", lambda x: x.get("teves_hiba")),
                      ("FELÜLBÍRÁLVA", lambda x: x.get("felulbiralva")),
                      ("FIGY", lambda x: x["sulyossag"] == "figy" and not x.get("elfogadva")),
                      ("ELFOGADVA", lambda x: x.get("elfogadva"))):
        for x in ls:
            if felt(x):
                indok = x.get("teves_hiba") or x.get("felulbiralva") or x.get("elfogadva")
                fej.append(f"{cim} " + lsor(x) + (f" — indok: {indok}" if indok and cim != "HIBA" and cim != "FIGY" else ""))
    for e in k["ervenytelen_kivetelek"]:
        fej.append(f"ÉRVÉNYTELEN KIVÉTEL ({e['fajta']}) {e['kod']} {e['lepes']} {e['obj']}: {e['ok']}")
    kap: dict[str, list] = {"ra": [], "kivul": [], "szamellenorzes": []}
    for l in mu.lepesek:
        for x in l["kapcsolok"]:
            kap[x["kapcsolo"]].append(f"{l['id']} {x['obj']} „{x['indok']}”")
    kapsor = " · ".join(f"{n}= {len(v)}" + (f" ({'; '.join(sorted(set(v)))})" if v else "") for n, v in kap.items())
    kezi = [f"{sid} {', '.join(f'{a} {b}' for a, b in sorted(v.items()))}" for sid, v in sorted(mu.kezi.items())]
    fej.append(f"kapcsolók: {kapsor} · kézi {len(kezi)}" + (f" ({'; '.join(kezi)})" if kezi else ""))
    bizonytalan = []
    for sid in mu.ids:
        n = {}
        for w in mu.szavak(sid):
            if w.get("forras") in ("becsult", "gyanus"):
                n[w["forras"]] = n.get(w["forras"], 0) + 1
        if n:
            bizonytalan.append(f"{sid} " + ", ".join(f"{v} {'becsült' if f == 'becsult' else 'gyanús'}" for f, v in sorted(n.items())))
    fej.append("becsült/gyanús szóidő: " + ("; ".join(bizonytalan) if bizonytalan else "nincs"))
    if k["jelzesek"]:
        fej.append("rövidítés: " + " · ".join(f"{j['lepes']} {j['uzenet'].split(' (')[0].removeprefix('rövidítés ')}"
                                                  for j in k["jelzesek"]))
    fej.append("Lépésenként: id idő | mondat | szó: kötött vagy számos szó +s a lépés elejétől | kép: +s esemény "
               "(← vonatkozás, „tartalom”, (szóra)) | álló | leletek")
    lepes_lelet: dict[str, list] = {}
    for x in ls:
        if x["lepes"]:
            lepes_lelet.setdefault(x["lepes"], []).append(f"{x['kod']} {x['sulyossag']}" +
                                                          (" elfogadva" if x.get("elfogadva") else ""))
    sorok = []
    jelenet = None
    for t in mu.tl:
        sid = t["id"]
        n = mu.narr_lepes.get(sid, {})
        if n.get("jelenet") != jelenet:
            jelenet = n.get("jelenet")
            sorok.append(f"## {jelenet}")
        l = mu.lmap.get(sid)
        if l is None:
            sorok.append(f"{sid} {ido(t['kezd_kocka'] / fps)}–{ido(t['veg_kocka'] / fps)} | {n.get('text', '')} | (nincs a naplóban)")
            continue
        allo = f"álló {tized(allo_s(mu, l))} s" + (" (kulcs)" if kulcslepes(mu, l) else "")
        sorok.append(f"{sid} {ido(t['kezd_kocka'] / fps)}–{ido(t['veg_kocka'] / fps)} | {n.get('text', '')} | "
                     f"szó: {szo_oszlop(mu, l)} | kép: {kep_oszlop(mu, l)} | {allo} | "
                     f"{', '.join(lepes_lelet.get(sid, [])) or '–'}")
    tabla = "\n".join(fej + ["", *sorok]) + "\n"
    szoveg_ir(mu.m / "tabla.txt", tabla)
    sz_sorok = [f"# {k['jelenet']} – a narráció mondatai", ""]
    jelenet = None
    for sid, n in mu.narr_lepes.items():
        if n["jelenet"] != jelenet:
            jelenet = n["jelenet"]
            sz_sorok += ["", f"## {jelenet}", ""] if len(sz_sorok) > 2 else [f"## {jelenet}", ""]
        sz_sorok.append(f"{sid} · {jeltelen(n['text'])}")
    szoveg_ir(mu.m / "szoveg.md", "\n".join(sz_sorok) + "\n")
    token = round(len(tabla) / 3.2 / 1000, 1)
    return f"tábla   tabla.txt ({len(sorok)} sor, kb. {tized(token)} e token) · szoveg.md"
