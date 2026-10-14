"""Minimális geometriai próba a render-naplón (K3 kilógás, K4 átfedés, K5 betűméret).

Nem a kapu (az a 2. lépés video.py-ja), csak a tesztjelenetek önellenőrzése: a TesztJelenet
ezekre a szabályokra tiszta, a HibasJelenet pontosan az elvárt helyen sért.
"""

from __future__ import annotations

SZEL, MAG, SAV_X, SAV_Y = 1920, 1080, 96, 54


def _szakasz_doboz(p, q, d) -> bool:
    """A p–q szakasz metszi-e a d doboz belsejét (Liang–Barsky)."""
    x0, y0, x1, y1 = d
    t0, t1 = 0.0, 1.0
    dx, dy = q[0] - p[0], q[1] - p[1]
    for pp, qq in ((-dx, p[0] - x0), (dx, x1 - p[0]), (-dy, p[1] - y0), (dy, y1 - p[1])):
        if pp == 0:
            if qq < 0:
                return False
        else:
            t = qq / pp
            if pp < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
    return t0 < t1


def vonal_metszi(v: dict, d) -> bool:
    d = [d[0] + 2, d[1] + 2, d[2] - 2, d[3] - 2]
    if v["t"] == "kor":
        (cx, cy), r = v["k"], v["r"]
        nx, ny = min(max(cx, d[0]), d[2]), min(max(cy, d[1]), d[3])
        kozel = ((nx - cx) ** 2 + (ny - cy) ** 2) ** 0.5
        tavol = max(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 for x in (d[0], d[2]) for y in (d[1], d[3]))
        return kozel < r < tavol
    utak = [v["p"]] if v["t"] == "szakasz" else v["p"]
    return any(_szakasz_doboz(u[i], u[i + 1], d) for u in utak for i in range(len(u) - 1))


def leletek(naplo: dict) -> list[tuple[str, str, str]]:
    """(lépés, kód, objektum) hármasok, lépésenként a vége- és a horgonyállapotból, ismétlés nélkül."""
    ki = set()
    for lep in naplo["lepesek"]:
        for objok in lep["allapot"].values():
            szovegek = [o for o in objok if "font" in o]
            for o in objok:
                x0, y0, x1, y1 = o["doboz"]
                if not o.get("kivul") and (x0 < -2 or y0 < -2 or x1 > SZEL + 2 or y1 > MAG + 2
                                           or x0 < SAV_X or y0 < SAV_Y or x1 > SZEL - SAV_X or y1 > MAG - SAV_Y):
                    ki.add((lep["id"], "K3", o["obj"]))
                if "font" in o and o["font"] < 28:
                    ki.add((lep["id"], "K5", o["obj"]))
            for s in szovegek:
                if s.get("ra"):
                    continue
                for o in objok:
                    if o is s or o.get("ra"):
                        continue
                    a, b = s["doboz"], o["doboz"]
                    atfed = min(a[2], b[2]) - max(a[0], b[0]) > 4 and min(a[3], b[3]) - max(a[1], b[1]) > 4
                    if atfed and (("font" in o and s["obj"] < o["obj"]) or o["kat"] == "jelolo"):
                        ki.add((lep["id"], "K4", s["obj"]))
                    if "vonal" in o and (o["csoport"] != s["csoport"] or o["kat"] == "nyil") \
                            and vonal_metszi(o["vonal"], s["doboz"]):
                        ki.add((lep["id"], "K4", s["obj"]))
    return sorted(ki)
