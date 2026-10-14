"""Szavak: magyar számnév-szótár, a narráció és a Whisper-szavak illesztése, szóidők, számeltérés.

A szó azonosítása a narráció szövegéből jön, az ideje a Whisperből (terv 2. pont):
- a narráció és a Whisper szavai egységekre bomlanak (egy szó, vagy egy többszavas szám:
  „két egész öt tized”, „mínusz három”, „két és fél”); az egység kanonikus alakja kisbetűs,
  ékezet nélküli szó, vagy számnál `#<érték>` (a -szor/-szer alaknál `#<érték>x`);
- a két sorozatot a `difflib` illeszti; az egyező és az 1:1-es cserében álló egység a Whisper idejét
  kapja (`forras: whisper`), a többi betűarányos becslést a szomszédok közé (`becsult`);
- a hangidő szüneteivel összevetve: szünetbe eső szókezdet, vagy a lépés első szavánál 0,25 s-nál
  nagyobb eltérés a beszéd kezdetétől: `gyanus`.
Az „egy” értéke 1 (a K2 kezeli úgy, hogy csak kifejezett kötéssel számít számnak).
"""

from __future__ import annotations

import difflib
import re
import unicodedata

HORGONY = re.compile(r"\{([^{}]+)\}")
ELSO_SZO_TURES_S = 0.25      # a lépés első szava ennyinél jobban nem térhet el a beszéd kezdetétől
SZUNET_TURES_S = 0.05        # a szünet szélén ennyi belecsúszás még nem gyanús
SAV_HASONLO = 0.8            # szóhatár-eltérésnél ennyi karakteres hasonlóság kell a Whisper-sávidőhöz
IRASJEL = ".,:;!?–—\"„”“()[]«»…'’"
HATAR_JEL = set(".!?;:")    # mondathatár és kettőspont: utána a „mínusz” előjel, nem kivonás

# ékezetes tövek (a „hát” nem 6, a „het” csak toldalékkal 7: „hetet”, „heten”), a hosszabb előbb
EGYES = [("kettő", 2), ("kett", 2), ("kilenc", 9), ("nyolc", 8), ("három", 3), ("hárm", 3), ("négy", 4), ("egy", 1),
         ("két", 2), ("hat", 6), ("hét", 7), ("het", 7), ("öt", 5)]
TIZES = [("kilencven", 90), ("nyolcvan", 80), ("hetven", 70), ("hatvan", 60), ("ötven", 50), ("negyven", 40),
         ("harminc", 30), ("huszon", 20), ("húsz", 20), ("husz", 20), ("tizen", 10), ("tíz", 10), ("tiz", 10)]
EGY_NEM = {"es", "en", "re", "ben", "be"}      # „egyes”, „egyen”, „egyre”, „egyben”: nem szám
# a toldalék ékezetesen: így a „hatás” nem 6, a „hatos” igen
TOLDALEK = re.compile(r"^(|t|[aeoö]t|[aeoö]n|ten|ra|re|ba|be|ban|ben|ból|ből|ról|ről|tól|től|nak|nek|nál|nél|hoz|"
                      r"hez|höz|ig|szor|szer|ször|[aeoö]s|val|vel|(.)\2?[ae]l|gyel|szal|szel|kor)$")
SZOR = re.compile(r"(szor|szer|ször)$")
TORT = {"tized": 10, "szazad": 100, "ezred": 1000}   # ékezet nélkül (sima)
MUVELET = re.compile(r"(?<=\d)\s*([−–+-])\s*(?=\d)")   # a Whisper „15-2”-je: tizenöt mínusz kettő
BETUNEV = {"á": "a", "bé": "b", "cé": "c", "dé": "d", "é": "e", "ef": "f", "gé": "g", "há": "h", "í": "i",
           "jé": "j", "ká": "k", "el": "l", "em": "m", "en": "n", "ó": "o", "pé": "p", "er": "r", "es": "s",
           "té": "t", "ú": "u", "vé": "v", "iksz": "x", "ipszilon": "y", "zé": "z"}      # a betű neve a narrációban, a betű a Whisperben
KOTOJEL = re.compile(r"(?<=[^\W\d_])-(?=[^\W\d_])")        # „Z-elem” → „Z elem” (betű és betű között)
JEL_SZAMON = re.compile(r"([−-]?\d+(?:[.,]\d+)?)([^\d\s.,−-].*)")   # „30°”, „5kN”: szám + egységjel
JEGY = re.compile(r"^([−-]?)([1-9]\d{0,2}(?:\.\d{3})+|\d+(?:[.,]\d+)?)(?:-?([a-záéíóöőúüű%]*))?$")
# A magyar Whisper-írásban a pont ezres tagoló („15.000”, „125.980”), a vessző tizedesvessző („1,5”); a
# szóidős listában a tagoló vagy a vessző a következő szó elejére kerül: „15” „.000”, „1” „,5”.
EZRES_PONT = re.compile(r"[1-9]\d{0,2}(?:\.\d{3})+")    # vezető nulla soha nem ezres tagolás („0.125”)
SZAMJEGY_FOLYTATAS = re.compile(r"^\s*(?:,\d+|\.\d{3}(?!\d))")
# szóközzel tagolt ezres csoportok a Whisperben („125 980”, „15 000”): első csoport 1–3 jegy, a többi pontosan 3
ELSO_CSOPORT = re.compile(r"[−-]?(?:0|[1-9]\d{0,2})")
EZRES_CSOPORT = re.compile(r"\d{3}")


def ekezet_nelkul(s: str) -> str:
    """Kisbetű, ékezet nélkül, karakterenként (a hossz nem változik: az eredeti toldaléka visszakereshető)."""
    s = unicodedata.normalize("NFC", s.lower())
    return "".join(unicodedata.normalize("NFD", c)[0] for c in s)


def sima(s: str) -> str:
    return _kiejtes(re.sub(r"[^a-z0-9]", "", ekezet_nelkul(s)))


def _kiejtes(s: str) -> str:
    """Az idegen írású név kiejtés szerinti alakja: a „newton” magyarul „nyúton”, a Whisper gyakran így írja."""
    return s.replace("newton", "nyuton")


def betu(s: str) -> str:
    """A szó egyeztető alakja: a betűnév („zé”, „há”) a betű, a mértékegység a kulcsa (`mertekegyseg`),
    különben a `sima` alak. Mindkét oldalon ugyanez fut, ezért az egyező szavak egyezők maradnak."""
    b = BETUNEV.get(unicodedata.normalize("NFC", s.lower().strip(IRASJEL)))
    return b or mertekegyseg(s) or sima(s)


# --- mértékegységek: a kimondott név és a Whisper jele ugyanaz ----------------------------------------
# A Whisper a kimondott mértékegységet gyakran jellel írja: „newtonméter” → „Nm”, „kilonewtonméter” →
# „kNm”, „newtont” → „N-t”, „harminc fokos” → „30°-os”. Ez nem a hang hibája. A `mertekegyseg` mindkét
# alakot ugyanarra a kulcsra hozza; a kulcs az egység felépítéséből jön (előtag × alapegység × hatvány,
# legfeljebb kéttagú szorzat, egy „per”/„/” hányados), nem felsorolásból, és a toldalékot is hordozza.
# Más egység más kulcs: newton „n”, kilonewton „kn”, newtonméter „nm”, méter „m”, centiméter „cm”.
# A kulcs egyezik a betűnév kulcsával („en” = „N” = „n”), így a betűként kimondott jel sem lesz lelet.
ALAP_NEV = {"n": ("nyuton",), "m": ("méter",), "g": ("gramm",), "t": ("tonna",), "s": ("másodperc", "szekundum"),
            "pa": ("pascal", "paszkál"), "j": ("joule", "dzsul"), "w": ("watt", "vatt"), "l": ("liter",),
            "fok": ("fok",), "h": ("óra",)}
ALAP_JEL = {"n": ("N",), "m": ("m",), "g": ("g",), "t": ("t",), "s": ("s",), "pa": ("Pa",), "j": ("J",),
            "w": ("W",), "l": ("l", "L"), "fok": ("°",), "h": ("h",)}
ELOTAG_NEV = {"k": ("kilo", "kiló"), "meg": ("mega",), "gig": ("giga",), "m": ("milli",), "c": ("centi",),
              "d": ("deci",), "u": ("mikro",), "h": ("hekto",)}
ELOTAG_JEL = {"k": ("k",), "meg": ("M",), "gig": ("G",), "m": ("m",), "c": ("c",), "d": ("d",), "u": ("µ", "μ"),
              "h": ("h",)}
ELOTAG_OK = {"n": {"k", "meg", "m"}, "m": {"k", "c", "d", "m", "u"}, "g": {"k", "m", "u"}, "s": {"m", "u"},
             "pa": {"k", "meg", "gig", "h"}, "j": {"k", "meg"}, "w": {"k", "meg", "gig"}, "l": {"d", "c", "m", "h"}}
HATVANY_NEV = {"2": ("négyzet",), "3": ("köb",)}           # „négyzetméter”, „szekundumnégyzet”
HATVANY_JEL = {"2": ("²", "^2", "2"), "3": ("³", "^3", "3")}
HATVANYOS = {"m", "s"}
NEM_ELSO = {"h"}                                          # az „óra”/„h” csak „km/h”, „kWh” tagja
SZORZO = "·⋅*"
EGYSEG_TOLDALEK = re.compile(r"(?:[aeoö]?t|[aeoö]?s(?:[aeoö][tkn])?|[aeoö]?k|[aeoö]n|ban|ben|ba|be|ra|re|ról|"
                             r"ről|ból|ből|tól|től|nak|nek|nál|nél|hoz|hez|höz|ig|ért|ként|nyi|"
                             r"(?:([^aáeéioóöőuü])\1?)?[ae]l)?")
VAL = re.compile(r"(?:([^aáeéioóöőuü])\1?)?[ae]l")         # -val/-vel hasonult alakja: „N-nal”, „kg-mal”


def _atomok(s: str, i: int, jeles: bool) -> list[tuple[str, int, str]]:
    """Az i. helytől kezdődő egységtag lehetséges olvasatai: (kulcs, vég, alapegység)."""
    alapok, elotagok = (ALAP_JEL, ELOTAG_JEL) if jeles else (ALAP_NEV, ELOTAG_NEV)
    hatvanyok = HATVANY_JEL if jeles else HATVANY_NEV
    ki = []
    for pk, pn in [("", "")] + ([] if jeles else [(k, n) for k, ns in HATVANY_NEV.items() for n in ns]):
        if not s.startswith(pn, i):
            continue
        for ek, en in [("", "")] + [(k, n) for k, ns in elotagok.items() for n in ns]:
            j = i + len(pn)
            if not s.startswith(en, j):
                continue
            j += len(en)
            for bk, bns in alapok.items():
                if (ek and ek not in ELOTAG_OK.get(bk, ())) or (pk and bk not in HATVANYOS):
                    continue
                for bn in bns:
                    if not s.startswith(bn, j):
                        continue
                    e = j + len(bn)
                    utana = [("", e)]
                    if not pk and bk in HATVANYOS:
                        utana += [(h, e + len(n)) for h, ns in hatvanyok.items() for n in ns if s.startswith(n, e)]
                    ki += [(ek + bk + (pk or hk), v, bk) for hk, v in utana]
    return ki


def _egyseg_resz(t: str, utolso: bool, elso: bool) -> tuple[str, str] | None:
    """Egy (legfeljebb kéttagú szorzat) egység jellel („kNm”, „N·m”, „m²”, „kN-t”) vagy névvel
    („kilonewtonméter”, „métert”): (kulcs, toldalék), vagy None. Toldalék csak az utolsó részen lehet, óra
    csak nem első tagként („km/h”, „kWh”)."""
    m = re.fullmatch(r"([^\s-]+)(?:-([a-záéíóöőúüű]+))?", t)
    if m:
        test, told = m.group(1), betuk(m.group(2) or "")
        if EGYSEG_TOLDALEK.fullmatch(told) and (utolso or not told):
            for k1, e1, b1 in _atomok(test, 0, True):
                if elso and b1 in NEM_ELSO:
                    continue
                e1b = e1 + int(e1 < len(test) and test[e1] in SZORZO)
                for k, e in [(k1, e1)] + [(k1 + k2, e2) for k2, e2, _ in _atomok(test, e1b, True)]:
                    if e == len(test):
                        return k, told
    s = betuk(t)
    for k1, e1, b1 in _atomok(s, 0, False):
        if elso and b1 in NEM_ELSO:
            continue
        for k, e in [(k1, e1)] + [(k1 + k2, e2) for k2, e2, _ in _atomok(s, e1, False)]:
            if EGYSEG_TOLDALEK.fullmatch(s[e:]) and (utolso or e == len(s)):
                return k, s[e:]
    return None


def mertekegyseg(szo: str) -> str | None:
    """A mértékegység kulcsa a toldalékkal („kNm-es” = „kilonewtonméteres” → „knm-es”), vagy None.
    Hányados „/”-rel vagy „per”-rel: „m/s²” = „méter per szekundumnégyzet” → „mpers2”."""
    s = unicodedata.normalize("NFC", szo).strip().strip(IRASJEL)
    reszek = re.split(r"\s+per\s+|\s*/\s*", s, flags=re.IGNORECASE)
    if not s or len(reszek) > 2 or any(not r or re.search(r"\s", r) for r in reszek):
        return None
    kulcsok, told = [], ""
    for n, r in enumerate(reszek):
        x = _egyseg_resz(r, n == len(reszek) - 1, n == 0)
        if x is None:
            return None
        kulcsok.append(x[0])
        told = x[1]
    if VAL.fullmatch(told):
        told = "vel"
    return "per".join(kulcsok) + ("-" + told if told else "")


def _kis(s: str) -> tuple[int, str]:
    """1–999 a szó elején: (érték, maradék); érték 0, ha nincs."""
    v = 0
    for t, tv in EGYES:                                   # százasok: „kétszáz”, „háromszáz”
        if s.startswith(t + "száz"):
            v, s = tv * 100, s[len(t) + 4:]
            break
    else:
        if s.startswith("száz"):
            v, s = 100, s[4:]
    for t, tv in TIZES:
        if s.startswith(t):
            v, s = v + tv, s[len(t):]
            break
    for t, tv in EGYES:
        if s.startswith(t):
            return v + tv, s[len(t):]
    return v, s


def egy_szo(szo: str) -> tuple[float | None, bool]:
    """Egy szó számértéke és hogy -szor/-szer alak-e. „harmincnyolcan” → 38; „kétszer” → (2, True);
    „egyik”, „hatás”, „harmadik” → None. Számjegyes alak is: „2,5”, „-3”, „12-szer”."""
    s = unicodedata.normalize("NFC", szo.lower()).strip(IRASJEL)
    m = JEGY.match(s)
    if m:
        ertek = float(m.group(2).replace(".", "") if EZRES_PONT.fullmatch(m.group(2)) else m.group(2).replace(",", "."))
        ertek = -ertek if m.group(1) else ertek
        return (int(ertek) if ertek.is_integer() else ertek), bool(SZOR.search(m.group(3) or ""))
    if s == "fél":
        return 0.5, False
    for kettos, egyszeres in (("ggyel", "gygyel"), ("sszal", "szszal")):   # „eggyel”, „néggyel”, „hússzal”
        if s.endswith(kettos):
            s = s[:-len(kettos)] + egyszeres
    e = s.replace("ezer-", "ezer")     # a helyes írásmód kötőjeles: „hatezer-ötszázkilencven”
    if not e or not e.isalpha():
        return None, False
    if e.startswith(("nulla", "nullá")):
        v, maradek = 0, e[5:]
    else:
        elotag, rest = _kis(e)
        if rest.startswith(("ezer", "ezr")):
            v, maradek = (elotag or 1) * 1000, rest[4 if rest.startswith("ezer") else 3:]
            utana, maradek2 = _kis(maradek)
            v, maradek = v + utana, maradek2
        elif elotag:
            v, maradek = elotag, rest
        else:
            return None, False
    toldalek = maradek
    if not TOLDALEK.match(toldalek) or (e == "egy" + toldalek and toldalek in EGY_NEM):
        return None, False
    return v, bool(SZOR.search(toldalek))


# A Whisper szóidős listája a tizedesvesszőt elhagyja: a kimondott „három egész két tized” egy
# számegységére „3 2” (toldalékkal „3 2 -del”) jut. Egy számegységre jutó két számjegycsoport ezért tizedes tört.
WHISPER_TIZEDES = re.compile(r"^\s*(?:-[^\W\d_]\w*\s+)?(m[ií]nusz\s+|[−-])?(\d+)(?:\s+(\d+))?(?:\s*-[^\W\d_]\w*)?\s*$",
                             re.I)   # a toldalék betűvel kezdődik: a „-9 6” nem „-9” toldalék + 6


def whisper_ertek(s: str) -> float | int | None:
    """Az egy narrációs számra jutó Whisper-szöveg értéke („3 2” = 3,2, „Minusz 15 6” = −15,6, „Minusz 9” = −9,
    „-gyel 0 75” = 0,75: az előző szó toldaléka is ide csúszhat; „15 000” = 15 000: tizedesjegy nem „000”;
    különben az első szó értéke)."""
    m = WHISPER_TIZEDES.match(s or "")
    if m:
        if m.group(3) == "000" and len(m.group(2)) <= 3:     # „15 000”: ezres tagolás (tizedesjegy nem „000”)
            v = int(m.group(2) + m.group(3))
        else:
            v = float(f"{m.group(2)}.{m.group(3)}") if m.group(3) else int(m.group(2))
        return -v if m.group(1) else v
    return egy_szo(s)[0] if s else None


def egysegek(szavak: list[str], jelek: list[str] | None = None) -> list[dict]:
    """A szavak egységekre: {kanon, idx: [szóindexek], ertek, szor}. Többszavas szám: tizedes
    („nulla egész öt”, „két egész öt tized”, „egy vessző öt”), „X és fél”, negatív („mínusz három”, „mínusz tizenöt egész hat
    tized”, ha előtte nem szám áll, vagy a szám után mondathatár vagy kettőspont van).
    `jelek`: a szavak utáni írásjel (`narracio_szavai`, `whisper_szavai`); nélküle a szám utáni „mínusz” kivonás
    („hat mínusz három”), „hat: mínusz kilenc” és „hat. Mínusz kilenc” viszont −9. A vessző nem határ: a
    „hat plusz öt, mínusz kettő” láncolt művelet."""
    ertekek = [egy_szo(w) for w in szavak]

    def hatar(i: int) -> bool:
        return bool(jelek) and 0 < i <= len(jelek) and any(c in HATAR_JEL for c in jelek[i - 1])

    def osszetett(i: int) -> tuple[float, list[int]] | None:
        """Tizedes („két egész öt tized”) vagy „X és fél” az i. szótól: (érték, szóindexek)."""
        v = ertekek[i][0]
        if v is None or i + 2 >= len(szavak):
            return None
        if sima(szavak[i + 1]) == "egesz" and ertekek[i + 2][0] is not None:
            m, idx = ertekek[i + 2][0], [i, i + 1, i + 2]
            nev = sima(szavak[i + 3]) if i + 3 < len(szavak) else ""
            tort = next((d for t, d in TORT.items() if nev.startswith(t)), None)
            if tort:
                idx.append(i + 3)
            else:
                tort = 10 ** len(str(int(m)))
            return round(v + m / tort, 6), idx
        if sima(szavak[i + 1]) == "es" and szavak[i + 2].lower().strip(IRASJEL) == "fél":
            return v + 0.5, [i, i + 1, i + 2]
        if sima(szavak[i + 1]) == "vesszo" and float(v).is_integer() and not hatar(i + 1) and not hatar(i + 2):
            return vesszos(v, i)
        return None

    def vesszos(v, i: int) -> tuple[float, list[int]] | None:
        """Kimondott tizedesvessző: „egy vessző öt” = 1,5, „egy vessző nulla öt” = 1,05. A vessző után a
        tizedesjegyek egy számnévként állnak, előttük a nullák külön szóként."""
        j, nullak = i + 2, 0
        while j < len(szavak) and sima(szavak[j]) == "nulla":
            nullak, j = nullak + 1, j + 1
        m = ertekek[j][0] if j < len(szavak) else None
        if m is None or m < 0 or not float(m).is_integer() or ertekek[j][1]:
            return (round(v, 6), list(range(i, j))) if nullak else None
        m = int(m)
        return round(v + m / 10 ** (nullak + len(str(m))), 6), list(range(i, j + 1))

    ki, i = [], 0
    while i < len(szavak):
        v, szor = ertekek[i]
        e = sima(szavak[i])
        elozo_szam = bool(ki) and ki[-1]["ertek"] is not None and not hatar(i)
        if e in ("minusz", "negativ") and i + 1 < len(szavak) and ertekek[i + 1][0] is not None and not elozo_szam:
            o = osszetett(i + 1)
            if o:
                ki.append(_egyseg(-o[0], [i] + o[1], False))
                i = o[1][-1] + 1
                continue
            n = ertekek[i + 1][0]
            ki.append(_egyseg(-n, [i, i + 1], ertekek[i + 1][1]))
            i += 2
            continue
        o = osszetett(i)
        if o:
            ki.append(_egyseg(o[0], o[1], False))
            i = o[1][-1] + 1
            continue
        if v is None and i + 2 < len(szavak) and (sima(szavak[i + 1]) == "per" or szavak[i + 1] == "/"):
            k = mertekegyseg(f"{szavak[i]} per {szavak[i + 2]}")      # „méter per szekundum” = „m / s”
            if k:
                ki.append({"kanon": k, "idx": [i, i + 1, i + 2], "ertek": None, "szor": False})
                i += 3
                continue
        ki.append(_egyseg(v, [i], szor) if v is not None else
                  {"kanon": betu(szavak[i]), "idx": [i], "ertek": None, "szor": False})
        i += 1
    return ki


def _egyseg(v, idx, szor) -> dict:
    v = int(v) if float(v).is_integer() else v
    return {"kanon": f"#{v}{'x' if szor else ''}", "idx": idx, "ertek": v, "szor": szor}


def narracio_szavai(text: str) -> tuple[list[str], dict[int, str]]:
    """A lépés szavai (írásjel nélkül) és a horgonyok első szavának indexe → horgonynév."""
    szavak, _, horg = narracio_szavai_jellel(text)
    return szavak, horg


def narracio_szavai_jellel(text: str) -> tuple[list[str], list[str], dict[int, str]]:
    """Mint a `narracio_szavai`, és szavanként a szó utáni írásjel (a számolvasónak: „hat: mínusz kilenc”).
    A horgony zárójele utáni írásjel („{hat}:”) az előtte álló szóé."""
    szavak, jelek, horg = [], [], {}
    for tok in re.findall(r"\{[^{}]+\}|[^\s{}]+", text):
        nev = tok[1:-1] if tok.startswith("{") else None
        for j, resz in enumerate(nev.split() if nev else [tok]):
            szo = resz.strip(IRASJEL)
            if not szo:
                if jelek:
                    jelek[-1] += resz
                continue
            if nev and j == 0:
                horg[len(szavak)] = nev
            szavak.append(szo)
            jelek.append(resz[len(resz.rstrip(IRASJEL)):])
    return szavak, jelek, horg


def whisper_szavai(words: list[dict]) -> list[dict]:
    """A Whisper-válasz szavai {szo, kezd, veg}; több szót tartó elem betűarányosan szétosztva. A számjegy után
    a tizedesvesszővel („,5”) vagy ezres tagoló ponttal („.000”) kezdődő elem az előző szám része („1,5”, „15.000”)."""
    ki = []
    for w in _szamjegy_folytatas(words):
        szoveg = MUVELET.sub(lambda m: " plusz " if m.group(1) == "+" else " mínusz ", str(w.get("word", "")))
        reszek = [r.strip(IRASJEL) for t in szoveg.split() for r in _whisper_tag(t.strip(IRASJEL))]
        reszek = [r for r in reszek if r]
        if not reszek:
            continue
        a, b = float(w.get("start", 0)), float(w.get("end", w.get("start", 0)))
        hossz, t = sum(len(r) for r in reszek), a
        for r in reszek:
            v = t + (b - a) * len(r) / hossz
            ki.append({"szo": r, "kezd": round(t, 3), "veg": round(v, 3)})
            t = v
    return ki


def _szamjegy_folytatas(words: list[dict]) -> list[dict]:
    """A Whisper a „1,5”-öt „1” „,5”, a „15.000”-et „15” „.000” elemekre bontja: az ilyen elemet az előző,
    számjegyre végződő elemhez fűzi (az idő az előző kezdetétől e vége). A vezető nullás „0.125” nem ezres tagolás:
    az `egy_szo` tizedesnek olvassa."""
    ki: list[dict] = []
    for w in words:
        t = str(w.get("word", ""))
        elozo = str(ki[-1].get("word", "")).strip() if ki else ""
        if ki and re.search(r"\d$", elozo) and SZAMJEGY_FOLYTATAS.match(t):   # „0” „.125” → „0.125”: tizedes (JEGY)
            e = ki[-1]
            ki[-1] = {**e, "word": str(e.get("word", "")).rstrip() + t.strip(), "end": w.get("end", e.get("end"))}
        else:
            ki.append(w)
    return ki


def _whisper_tag(t: str) -> list[str]:
    """Egy Whisper-szó részei: a számhoz tapadt egység külön szó („30°-os” → „30”, „°-os”), a jel és a
    kötőjeles toldaléka együtt marad („kN-t”), a kötőjeles számnév is („hatezer-ötszáz”); máskor a betűk közti
    kötőjel szóhatár („Z-elem” → „Z elem”)."""
    m = JEL_SZAMON.fullmatch(t)
    if m and mertekegyseg(m.group(2)):
        return [m.group(1), m.group(2)]
    return [t] if mertekegyseg(t) or egy_szo(t)[0] is not None else KOTOJEL.sub(" ", t).split()


def _osszevont_szet(wsz: list[dict], nszo: list[str]) -> list[dict]:
    """A szóhatár kétirányú egyeztetése (különben a szó, és benne a szám, elveszne):
    - a Whisper két narrációs szót egy szóba ír („kéthalmaz” = „két halmaz”): a narráció két szavára bontja,
      betűarányos idővel;
    - a Whisper egy narrációs szót két szóba ír („elem száma” = „elemszáma”): a két szót összevonja.
    Szám nem vonódik össze, és nem bontódik, ha a szó (vagy a pár) a narrációban maga is előfordul."""
    nsima = [sima(x) for x in nszo]
    egyes = set(nsima)
    parok, par_n = {}, set()
    for x, y in zip(nszo, nszo[1:]):
        parok.setdefault(sima(x) + sima(y), (x.strip(IRASJEL), y.strip(IRASJEL)))
        par_n.add((sima(x), sima(y)))

    def szam(szo):
        return egy_szo(szo)[0] is not None

    ki, i = [], 0
    while i < len(wsz):
        w = wsz[i]
        if i + 1 < len(wsz):
            v = wsz[i + 1]
            a, b = sima(w["szo"]), sima(v["szo"])
            if a + b in egyes and (a, b) not in par_n and a and b and not szam(w["szo"]) and not szam(v["szo"]):
                ki.append({"szo": nszo[nsima.index(a + b)].strip(IRASJEL), "kezd": w["kezd"], "veg": v["veg"]})
                i += 2
                continue
        par = parok.get(sima(w["szo"]))
        if par is None or szam(w["szo"]) or sima(w["szo"]) in egyes:
            ki.append(w)
            i += 1
            continue
        kozep = w["kezd"] + (w["veg"] - w["kezd"]) * len(sima(par[0])) / len(sima(w["szo"]))
        ki += [{"szo": par[0], "kezd": w["kezd"], "veg": round(kozep, 3)},
               {"szo": par[1], "kezd": round(kozep, 3), "veg": w["veg"]}]
        i += 1
    return ki


def elteres(narracio: list[str], whisper: list[str]) -> float:
    """A K10 eltérése: 1 − a két oldal egyeztető alakjainak (számok értékkel, betűnevek betűvel) szóköz
    nélkül összefűzött szövegén mért karakteres SequenceMatcher-arány. Szóhatár-eltérés („elemszáma” –
    „elem száma”) nem számít, egy elírt betű csak a karakterei arányában."""
    a = "".join(u["kanon"] for u in egysegek(narracio))
    b = "".join(u["kanon"] for u in egysegek(whisper))
    if not a and not b:
        return 0.0
    return 1 - difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


# --- K10: szóváltozás a hangban ---------------------------------------------------------------------
# A Whisper a jól kimondott szót is gyakran a kiejtése szerint írja: „halmazt” → „halmaszt”, „metszet” →
# „meccet”, „medszet”, „metzet”, „mínusz” → „minusz”. Ezek nem a hang hibái. A `hangalak` a szót magyar
# hangokra bontja, és csak a kiejtésben valóban egybeeső írásmódokat hozza egy alakra:
# - a felső nyelvállású magánhangzók hossza (i/í, u/ú, ü/ű) nem számít: a beszédben és a Whisper írásában
#   is ingadozik; az a/á és az e/é minőségi különbség, az o/ó, ö/ő hossza szót különít el („tör” – „tőr”),
#   ezek számítanak, és az o/ö, u/ü is;
# - ly = j; a mássalhangzó-torlódásban a zöngésség nem számít; t/ty + sz/s = c/cs („metszet” = „meccet”);
# - a hosszú mássalhangzó csak torlódásban egyenlő a rövidvel; magánhangzók között („kell” – „kel”) nem.
# Ami ezután is eltér, az a kiejtett szó megváltozása („számokat” → „sámokat”: sz → s), akkor is, ha
# csak egy betű.
FONEMA = ("dzs", "cs", "dz", "gy", "ly", "ny", "sz", "ty", "zs")
ZONGES = {"b": "p", "d": "t", "g": "k", "z": "sz", "zs": "s", "dz": "c", "dzs": "cs", "gy": "ty", "v": "f"}
ZONGETLEN = set(ZONGES.values()) | {"h"}
MAGANHANGZO = set("aáeéiíoóöőuúüű")
HOSSZ_MINDEGY = str.maketrans("íúű", "iuü")
PAR_HASONLO = 0.5     # több szavas egyenlő csere: ha egy pár ennél távolabb van, az eltolt szóhatár, nem szócsere


def betuk(s: str) -> str:
    """Kisbetűs, ékezetes alak csak betűkkel és számjegyekkel; í, ú, ű → i, u, ü (lásd fent)."""
    s = unicodedata.normalize("NFC", s.lower())
    return _kiejtes(re.sub(r"[^a-z0-9áéíóöőúüű]", "", s).translate(HOSSZ_MINDEGY))


BETU_NEVE = {}
for _nev, _b in BETUNEV.items():
    BETU_NEVE.setdefault(_b, betuk(_nev))


def hangok(s: str) -> list[str]:
    """A `betuk` alak hangokra bontva (a hosszú mássalhangzó két hang: „ssz” = sz sz)."""
    s, ki, i = betuk(s), [], 0
    while i < len(s):
        for f in FONEMA:
            if s.startswith(f, i):
                ki.append(f)
                i += len(f)
                break
            if len(f) >= 2 and s[i] == f[0] and s.startswith(f, i + 1):      # ssz, ccs, ggy, tty, nny, zzs
                ki += [f, f]
                i += 1 + len(f)
                break
        else:
            ki.append(s[i])
            i += 1
    return ki


def hangalak(*szavak: str) -> str:
    """A szavak kiejtés szerinti egyeztető alakja egybefűzve (lásd fent); a kiejtésben egybeeső írásmódokra
    ugyanaz. Szavanként bont hangokra, így a szóhatáron nem keletkezik hamis betűkapcsolat („az szerint”)."""
    h = ["j" if x == "ly" else x for s in szavak for x in hangok(s)]
    zor = set(ZONGES) | ZONGETLEN
    i = 0
    while i < len(h):                                     # torlódásban a zöngésség nem számít: zöngétlenre
        j = i
        while j < len(h) and h[j] in zor:
            j += 1
        if j - i >= 2:
            h[i:j] = [ZONGES.get(x, x) for x in h[i:j]]
        i = max(j, i + 1)
    for i in range(len(h) - 1):                           # t/ty + sz/s → c/cs (összeolvadás: „metszet” = „meccet”)
        if h[i] in ("t", "ty") and h[i + 1] in ("sz", "s", "c", "cs"):
            h[i] = h[i + 1] = {"sz": "c", "s": "cs"}.get(h[i + 1], h[i + 1])

    def msh(k):                                           # mássalhangzó a k. helyen (a szó szélén nincs)
        return 0 <= k < len(h) and h[k] not in MAGANHANGZO
    ki = []
    for i, x in enumerate(h):
        if ki and x == h[i - 1] and (x in MAGANHANGZO or msh(i - 2) or msh(i + 1)):
            continue                                      # hosszú = rövid: magánhangzó-kettőzés, torlódás
        ki.append(x)
    return "".join(ki)


def _alak(szo: str) -> str:
    """Egy szó egyeztető alakja: a betűnév („zé”) a betű, a mértékegység a kulcsa („Nm” = „newtonméter”),
    különben a `hangalak`."""
    b = BETUNEV.get(unicodedata.normalize("NFC", szo.lower().strip(IRASJEL)))
    return b or mertekegyseg(szo) or hangalak(szo)


def valtozott_szavak(narracio: list[str], whisper: list[str]) -> list[dict]:
    """K10: a narráció szavai, amelyeket a Whisper kiejtésben más szóként hallott:
    [{"idx": a narrációs szó indexe, "szo": narráció, "hallott": Whisper}].
    Az egyenlő hosszú cseréknél (n narrációs szó helyén n hallott) a szavak párban, egyenként számítanak
    („a számokat” → „az sámokat”: két lelet); ha a két oldal egybefűzve kiejtésre azonos, vagy egy pár
    nem is hasonlít (`PAR_HASONLO`; „min játszanak aszerint” – „miniátszanak az szerint”), az eltolt szóhatár. Zaj, ezért nem számít: a kiejtés szerinti írás (`hangalak`), a betűnév és a betű („ef” –
    „f”), az eltérő szószámú csere (a Whisper szóhatár-zavara: „efnek” – „f nek”, „körbe zárt” – „körbezár”),
    a kimaradt vagy többlet szó (ezt a karakteres eltérés méri), és a szám (azt a K10 értékkel nézi)."""
    a, b = egysegek(narracio), egysegek(whisper)

    def kulcs(u, szavak):
        return u["kanon"] if u["ertek"] is not None else _alak(" ".join(szavak[i] for i in u["idx"]))
    ka, kb = [kulcs(u, narracio) for u in a], [kulcs(u, whisper) for u in b]
    ki = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ka, kb, autojunk=False).get_opcodes():
        if op != "replace" or i2 - i1 != j2 - j1:
            continue
        if i2 - i1 > 1 and (hangalak(*(narracio[i] for u in a[i1:i2] for i in u["idx"])) ==
                            hangalak(*(whisper[i] for u in b[j1:j2] for i in u["idx"])) or
                            any(difflib.SequenceMatcher(None, x, y, autojunk=False).ratio() < PAR_HASONLO
                                for x, y in zip(ka[i1:i2], kb[j1:j2]))):
            continue                                      # eltolt szóhatár: a párok nem egymás változatai
        for ua, ub, x, y in zip(a[i1:i2], b[j1:j2], ka[i1:i2], kb[j1:j2]):
            if ua["ertek"] is not None or ub["ertek"] is not None or x == y or \
                    BETU_NEVE.get(x, x) == BETU_NEVE.get(y, y):
                continue
            ki.append({"idx": ua["idx"][0], "szo": " ".join(narracio[i] for i in ua["idx"]),
                       "hallott": " ".join(whisper[i] for i in ub["idx"])})
    return ki


def hallott_szavak(ws: list[dict]) -> list[str]:
    """A szavak.json lépésének Whisper-szövege szavakra: a több narrációs szóra osztott Whisper-szöveg egyszer."""
    hallott, elozo = [], None
    for w in ws:
        if w.get("whisper") and w["whisper"] != elozo:
            hallott += w["whisper"].split()
        elozo = w.get("whisper")
    return hallott


def whisper_egysegek(wszo: list[str], narracio_kanon: list[str]) -> list[dict]:
    """A Whisper-szavak egységei; a szám utáni „mínusz” olvasatát (kivonás vagy előjel) a narráció dönti el, nem a
    Whisper saját írásjele (az a kettőspontot gyakran vesszőnek vagy semminek írja), és előfordulásonként külön (egy
    lépésben lehet kivonás és előjel is). Kiindulás a kivonásos olvasat; a „mínusz”-okon sorban végigmenve egy
    előfordulás akkor lesz előjel, ha attól a Whisper-egységsor jobban illeszkedik a narrációéhoz (egyenlőségnél
    kivonás marad). A valódi számhibát ez nem nyeli el: a más szám más egység marad.
    Utána az ezres összevonás (`_ezres_osszevon`): „125 980”, „15 ezer” egy szám, ha a narráció ezt az értéket mondja."""
    def arany(egys):
        return difflib.SequenceMatcher(None, narracio_kanon, [u["kanon"] for u in egys], autojunk=False).ratio()
    jelek = [""] * len(wszo)
    legjobb = arany(egysegek(wszo, jelek))
    for i in range(1, len(wszo)):
        if sima(wszo[i]) not in ("minusz", "negativ"):
            continue
        proba = jelek[:i - 1] + ["."] + jelek[i:]
        r = arany(egysegek(wszo, proba))
        if r > legjobb:
            jelek, legjobb = proba, r
    return _ezres_osszevon(egysegek(wszo, jelek), wszo, narracio_kanon, arany)


def _ezres_valtozatok(egys: list[dict], wszo: list[str], i: int) -> list[tuple[int, int, bool]]:
    """Az i. egységtől kezdődő, egy számot adó Whisper-alakok: (érték, egységszám, -szor). Szóközzel tagolt ezres
    csoportok („125 980”, „1 000 000”: első csoport 1–3 jegy, a többi pontosan 3) és szám + „ezer” („15 ezer” =
    15 000, „11 ezer 240” = 11 240). Az első tag egész számjegyes szó (előjeles egységben is: „Minusz 15 ezer”)."""
    u = egys[i]
    if not isinstance(u["ertek"], int) or u["szor"] or not ELSO_CSOPORT.fullmatch(wszo[u["idx"][-1]]):
        return []
    elojel, a = (-1 if u["ertek"] < 0 else 1), abs(u["ertek"])

    def jegyek(k: int, minta) -> str | None:
        """A k. egység számjegyei, ha egyetlen, a mintára illő (toldalékos is lehet: „000-et”) számjegyes szó."""
        x = egys[k] if k < len(egys) else None
        if x is None or len(x["idx"]) != 1 or not isinstance(x["ertek"], int):
            return None
        m = re.fullmatch(r"(\d+)(-[^\W\d_]+)?", wszo[x["idx"][0]])
        return m.group(1) if m and minta.fullmatch(m.group(1)) else None

    ki, szam, k = [], str(a), i + 1
    while not egys[k - 1]["szor"] and (k == i + 1 or "-" not in wszo[egys[k - 1]["idx"][0]]) and \
            (cs := jegyek(k, EZRES_CSOPORT)) is not None:       # a toldalékos csoport az utolsó
        szam += cs
        ki.append((elojel * int(szam), k - i + 1, egys[k]["szor"]))
        k += 1
    e = egys[i + 1] if i + 1 < len(egys) else None
    if e is not None and len(e["idx"]) == 1 and e["ertek"] == 1000 and sima(wszo[e["idx"][0]]).startswith(("ezer", "ezr")):
        ki.append((elojel * a * 1000, 2, e["szor"]))
        if sima(wszo[e["idx"][0]]) == "ezer" and jegyek(i + 2, ELSO_CSOPORT) is not None:
            ki.append((elojel * (a * 1000 + egys[i + 2]["ertek"]), 3, egys[i + 2]["szor"]))
    return ki


def _ezres_osszevon(egys: list[dict], wszo: list[str], narracio_kanon: list[str], arany) -> list[dict]:
    """A Whisper szóközzel tagolt vagy „ezer”-es számalakja („125 980”, „15 ezer”) egy egység, ha az összevont
    érték a narráció egyik száma, és az egységsor attól jobban illeszkedik a narrációéhoz (egyenlőségnél külön
    marad). Más értékű alak nem vonódik össze, így a valódi számhiba („15 000” ↔ „ezerötszáz”) megmarad.
    Balról jobbra, változatonként a rövidebb előbb: determinisztikus."""
    ertekek = set()
    for k in narracio_kanon:
        if k.startswith("#"):
            ertekek.add(float(k[1:].rstrip("x")))
    legjobb, i = arany(egys), 0
    while i < len(egys):
        valasztott = None
        for v, n, szor in _ezres_valtozatok(egys, wszo, i):
            if float(v) not in ertekek:
                continue
            proba = egys[:i] + [_egyseg(v, [x for u in egys[i:i + n] for x in u["idx"]], szor)] + egys[i + n:]
            r = arany(proba)
            if r > legjobb:
                valasztott, legjobb = proba, r
        if valasztott is not None:
            egys = valasztott
        i += 1
    return egys


def szamsor(egys: list[dict]) -> list:
    return [(u["ertek"], u["szor"]) for u in egys if u["ertek"] is not None]


def illeszt(text: str, words: list[dict], beszed: tuple[float, float], szunetek: list) -> dict:
    """A lépés szavai idővel: {szavak: [{szo, kezd_s, veg_s, ertek, forras, whisper}], horgonyok: {nev: {...}},
    szameltérés: [narráció számai, Whisper számai] vagy None, szovaltozas: [[narráció szava, hallott], …] vagy
    None (`valtozott_szavak`)}. Whisper-szavak nélkül minden szó becsült."""
    nszo, njel, horg = narracio_szavai_jellel(text)
    wsz = _osszevont_szet(whisper_szavai(words), nszo)
    nu = egysegek(nszo, njel)
    wu = whisper_egysegek([w["szo"] for w in wsz], [u["kanon"] for u in nu])
    ido: list = [None] * len(nszo)          # (kezd, veg, forras, whisper)
    par: dict[int, int] = {}                # Whisper-egység → a vele 1:1 párosított narrációs egység
    sajat: set[int] = set()                 # nem 1:1-es replace Whisper-egységei, ahol a narráció oldalán szám áll
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, [u["kanon"] for u in nu], [u["kanon"] for u in wu],
                                                      autojunk=False).get_opcodes():
        if op == "equal" or (op == "replace" and i2 - i1 == j2 - j1):
            for k in range(i2 - i1):
                _kioszt(nszo, nu[i1 + k]["idx"], wsz, wu[j1 + k]["idx"], ido, "whisper", wu[j1 + k]["ertek"])
                par[j1 + k] = i1 + k
        elif op == "replace":
            if any(u["ertek"] is not None for u in nu[i1:i2]):   # „3 2” = 3,2: a blokk saját száma kapja
                sajat.update(range(j1, j2))
            idx = [x for u in nu[i1:i2] for x in u["idx"]]
            # eltérő szóhatár elírással („körbe zárt” – „körbezár”, „metszet elemeit” – „meccetelemeit”): a sáv
            # Whisper-idő, ha szám nincs benne és a két oldal összefűzve közel azonos; különben becsült
            hasonlo = all(u["ertek"] is None for u in nu[i1:i2] + wu[j1:j2]) and difflib.SequenceMatcher(
                None, "".join(u["kanon"] for u in nu[i1:i2]), "".join(u["kanon"] for u in wu[j1:j2]),
                autojunk=False).ratio() >= SAV_HASONLO
            _kioszt(nszo, idx, wsz, [x for u in wu[j1:j2] for x in u["idx"]], ido, "whisper" if hasonlo else "becsult")
    _szammaradek(nu, wu, wsz, par, sajat, ido)
    _becsul(nszo, ido, beszed)
    ertek = {}
    for u in nu:
        ertek[u["idx"][0]] = u["ertek"]
    ki = []
    for n, (szo, (kezd, veg, forras, hallott)) in enumerate(zip(nszo, ido)):
        if forras == "whisper" and _gyanus(kezd, n, beszed, szunetek):
            forras = "gyanus"
        ki.append({"szo": szo, "kezd_s": round(kezd, 3), "veg_s": round(veg, 3), "ertek": ertek.get(n),
                   "forras": forras, "whisper": hallott})
    horgonyok = {nev: {"kezd_s": ki[i]["kezd_s"], "veg_s": ki[i]["veg_s"], "forras": ki[i]["forras"],
                       "whisper": ki[i]["whisper"]} for i, nev in horg.items()}
    n_sor, w_sor = szamsor(nu), szamsor(wu)
    valt = valtozott_szavak(nszo, [w["szo"] for w in wsz])
    return {"szavak": ki, "horgonyok": horgonyok, "szameltérés": None if n_sor == w_sor else [n_sor, w_sor],
            "szovaltozas": [[v["szo"], v["hallott"]] for v in valt] or None}


def _szammaradek(nu, wu, wsz, par, sajat, ido) -> None:
    """A párosított Whisper-szám után közvetlenül álló, párosítatlan Whisper-szám (beszúrás vagy egy replace
    illesztetlen maradéka: „15 ezer” = 15 000 után az „500”, „tizenöt” ↔ „15” után a „000”) a narrációs szám
    hallott szövegéhez fűződik, a Whisper saját szavaival („15 ezer 500”). A K10 így a teljes hallott számot méri, és
    ez nem a narráció száma; a maradék nem vész el beszúrásként. Párosított szám (a „tizenegyezer, kétszáznegyven”
    240-e) nem fűződik, és az sem, amely egy számot tartalmazó, nem 1:1-es replace-blokkban áll (`sajat`: a „15, 2 5”
    „2 5”-je a blokk saját 2,5-éé, azt a replace-ág már kiosztotta); ez a horgonyt is lezárja."""
    alap: dict[int, list[int]] = {}
    plusz: dict[int, list[int]] = {}
    horgony = None
    for j, u in enumerate(wu):
        if j in par:
            n = par[j]
            horgony = n if u["ertek"] is not None and nu[n]["ertek"] is not None else None
            if horgony is not None:
                alap[n] = list(u["idx"])
        elif u["ertek"] is None or j in sajat:
            horgony = None
        elif horgony is not None:
            plusz.setdefault(horgony, []).extend(u["idx"])
    for n, tobb in sorted(plusz.items()):
        i = nu[n]["idx"][0]
        if ido[i] is not None:
            k, v, f, _ = ido[i]
            ido[i] = (k, v, f, " ".join(wsz[x]["szo"] for x in alap[n] + tobb))


def _kioszt(nszo, nidx, wsz, widx, ido, forras, w_ertek=None) -> None:
    """A narráció szavai (nidx) a Whisper-szavak (widx) idejével: azonos szószámnál szóról szóra, különben
    betűarányosan a sávjukban. A `whisper` mező a hallott szó; többszavas hallott számkifejezésnél az első
    (az értéket hordozó) szónál az érték számjeggyel („mínusz három” → „-3”), hogy egy szóként olvasható legyen."""
    if len(nidx) == len(widx):
        for i, j in zip(nidx, widx):
            ido[i] = (wsz[j]["kezd"], wsz[j]["veg"], forras, wsz[j]["szo"])
    else:
        a, b = wsz[widx[0]]["kezd"], wsz[widx[-1]]["veg"]
        hallott = " ".join(wsz[j]["szo"] for j in widx)
        hossz, t = sum(len(nszo[i]) for i in nidx), a
        for i in nidx:
            v = t + (b - a) * len(nszo[i]) / hossz
            ido[i] = (t, v, forras, hallott)
            t = v
    if w_ertek is not None and len(widx) > 1:
        k, v, f, _ = ido[nidx[0]]
        ido[nidx[0]] = (k, v, f, str(w_ertek).replace(".", ","))


def _becsul(nszo, ido, beszed) -> None:
    """Az illesztetlen szavak a szomszédos ismert idők közé, betűarányosan (`becsult`, whisper: "")."""
    i = 0
    while i < len(nszo):
        if ido[i] is not None:
            i += 1
            continue
        j = i
        while j < len(nszo) and ido[j] is None:
            j += 1
        a = ido[i - 1][1] if i else beszed[0]
        b = ido[j][0] if j < len(nszo) else max(beszed[1], a)
        hossz, t = sum(len(w) for w in nszo[i:j]), a
        for k in range(i, j):
            v = t + (b - a) * len(nszo[k]) / hossz
            ido[k] = (t, v, "becsult", "")
            t = v
        i = j


def _gyanus(kezd: float, n: int, beszed, szunetek) -> bool:
    if n == 0 and abs(kezd - beszed[0]) > ELSO_SZO_TURES_S:
        return True
    return any(a + SZUNET_TURES_S < kezd < b - SZUNET_TURES_S for a, b in szunetek)
