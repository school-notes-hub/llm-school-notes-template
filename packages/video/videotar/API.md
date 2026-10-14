# videotar – az elemtár API-ja (az író egyetlen elemtár-olvasmánya)

Manim CE 0.22. `from manim import *` után `from videotar import *`. A forrást ne olvasd. Ha ez a
leírás nem elég, vagy egy elem hibás, az eszközhiba: írd az `iro-jelentes.md`-be, és állj meg.

**Kötelező:** a `VideoJelenet` ütemező (`Horgony`, `Szora`) és a napló (`jelol`). **Minden más
segédlet:** ahol a téma mást kíván, írj saját Manim-kódot a `jelenetek.py`-ba. A napló a saját
objektumot is méri (kilógás, átfedés, betűméret, megjelenés ideje); a `jelol` adja meg, amit a
gép magától nem tudhat. Felirat és fejezetcím nincs, és nincs is rá elem.

## 1. Váz

```python
from manim import *
from videotar import *

class Halmazok(VideoJelenet):
    JELENETEK = ["s01", "s02"]               # a narracio.json jelenetei, sorrendben

    def jelenet_s01(self):                    # lépésenként egy lista; annyi lépés, ahány mondat
        self.v = Venn2(("A", "B"), kozep=DOWN * 0.4, nev="venn")
        return [
            [(0.9, lambda: self.v.kor_rajzol("a"))],                      # „Ez az A halmaz.”
            [(0.6, lambda: self.v.regio_kiemel("ab")),                    # „A közös rész a metszet,
             Szora(2, 0.5, lambda: FadeIn(self.v.regio_szam("ab", 2, nev="m")))],  #  benne két elem.”
        ]
```
Futtatás a lánccal (`video.sh`).
`CSAK=s02` csak ezt a jelenetet rajzolja (az állapot felépül); `IG=s02-03` a lépés végén megáll
(a `-s` kapcsolóval ez a lépés végállapotának képe).

## 2. Ütemező: a lépés elemei

Egy lépés pontosan a mondata hangjáig tart (`idoterv.json`). Az elemek:

| Elem | Mikor indul |
|---|---|
| `(rt, fv)` | az előző elem után; a lépés első eleme a beszéd kezdetén |
| `Szora(mit, rt, fv, hanyadik=1)` | a mondat `mit` szavának kimondásakor (0,1 s-mal előtte) |
| `Horgony(nev, rt, fv, tart=False)` | a narráció `{nev}` jelölésű szavánál |

- `fv` lusta: a lejátszáskor fut, és animációt vagy animációlistát ad vissza (üres lista is lehet).
- `rt` névleges idő (s). Ha a következő kötésig nem fér el, arányosan rövidül; a maradék várakozás.
- `Szora`: `mit` szám (`Szora(19, …)`: az a szó, amelynek értéke 19) vagy szó (kisbetű, ékezet
  nélkül egyezik, vagy legalább 4 betűs tő: `"unió"` ~ „uniója”). `hanyadik`: a lépésben a
  k-adik ilyen szó, vagy `"utolso"`. A „kétszer”-re `Szora("kétszer", …)`; az „egy” névelőt
  csak kifejezett sorszámmal kösd. A kötött elemek a szavak sorrendjében álljanak.
- `{}` horgonyt csak csattanóra használj; a szám és a képlettag `{}` nélkül, `Szora`-val kötődik.
  A kódban minden `{nev}`-nek pontosan egy `Horgony` (vagy `Szamolas`-eredmény) felel meg.
- Egy lépésben a lépés elején **legfeljebb egy kötetlen tartalmi csoport** jelenhet meg; minden
  további tartalom `Szora` vagy `Horgony` (K9). A kiemelés, keret, nyíl a meglévőre nem új tartalom.
- A kiemelések (`kiemel`, `korvonal`, `regio_kiemel`) a lépés végéig maradnak, és a következő
  lépés első animációjával tűnnek el; `Horgony(…, tart=True)` mellett már a következő kötésnél.
- `self.mind_ki()`: minden látható objektum `FadeOut`-ja (jelenetváltáskor).
- A `self.play`/`self.wait` közvetlen hívása hiba: minden képváltozás egy elem `fv`-jéből jön.

## 3. Napló és `jelol` (saját kódhoz)

Minden play után pillanatkép készül a jelenet összes objektumáról (doboz, betűméret, szín,
tartalom, vonalgeometria). A jelöletlen objektum automatikus nevet kap (`Text#7 „metszet”`), és
az általános szabályok vonatkoznak rá. A csoportja a legfelső objektum, amelyben a jelenetbe
került (egy `VGroup` egy csoport).

```python
jelol(obj, nev=None, szo=None, vonatkozik=(), cimke=None, ra=None, kivul=None,
      szamellenorzes=None, csoport=None)   # visszaadja az obj-t
```
- `nev`: egyedi név (a táblában és a kapuban így látszik). Foglalt név: hiba.
- `csoport`: egy tartalmi egység több része (nyíl + felirata) közös néven (K9).
- `vonatkozik=[…]`: amire rárajzolod (keret, nyíl, kiemelés). Ezeknek már a helyükön kell
  lenniük, és a megjelenés alatt nem mozoghatnak (K7).
- `cimke=`: a keret vagy alak felirata (a feliratos alak nem „csak színben” különbözik, K6b).
- `szo=`: a kimondott szó, amelyre a megjelenése tartozik (a táblában látszik).
- Elhallgató kapcsolók, **kötelező indokszöveggel** (üres indok: hiba): `ra="szám a régióban"`
  (szándékos átfedés, K4), `kivul="…"` (szándékosan a kép szélén túl, K3),
  `szamellenorzes="skálabeosztás"` (a szám nem a kimondáshoz kötött, K2). A lektor látja őket.

**Szövegcsere csak `atir(regi, uj)`-ral** (ReplacementTransform; az új objektum a régi nevét és
jelöléseit örökli, utána `uj`-t használd). A nyers `Transform` szövegen vagy számon futás közben
hibát ad, mert utána a régi szöveg maradna nyilvántartva.

## 4. Stílus

`HATTER`, `FEHER`, `SZURKE`, kategóriaszínek: `KEK`, `SARGA`, `ZOLD`, `PIROS` (színtévesztésben
és világosságban is elválnak; a jelentést mégis az alak hordozza). `MERET = {"S": 28, "M": 34,
"L": 44, "XL": 56}`: 28 alá ne menj (24 alatt hiba). `SAV = 0.05`: a kép szélén 5% (oldalt 0,71,
fent-lent 0,40 egység) szabadon marad; a tartalom `|x| ≤ 6,4`, `|y| ≤ 3,6` között.
`szoveg(s, meret="M", nev=None, szin=FEHER)`: `Text` a skála méretével, regisztrálva.

## 5. Kiemelés és rajzolás

| Függvény | Mit ad | Megjegyzés |
|---|---|---|
| `kore_rajzol(keret, elemek, anim=Create, nev=None)` | animáció | hiba, ha ugyanabban a play-ben egy elem mozog: előbb a helyére (külön elem), aztán köré |
| `kiemel(alak, vonatkozik=(), nev=None)` | `FadeIn` | vastag fehér körvonal + halvány kitöltés, tartós |
| `korvonal(alak, vonatkozik=(), nev=None)` | `Create` | csak körvonal, tartós |
| `villan(alak)` | `ShowPassingFlash` | átfutó fehér körvonal, nem marad |
| `pulzal(*mobok, sk=1.2)` | lista | `Indicate` fehérrel (a Manim sárga alapszíne kategóriaszín lenne) |
| `eltuntet(*mobok)` | lista | `FadeOut` darabonként |
| `atir(regi, uj)` | animáció | a szöveg- és számcsere egyetlen útja |

## 6. Kategóriák (alak + szín, K6a)

```python
kat = Kategoriak({"sport": ("haromszog", KEK, None), "zene": ("negyzet", SARGA, None),
                  "mindketto": ("haromszog", ZOLD, "keretes")})
e = kat.elem("sport", poz, nev="t01", csoport="tanulok")   # több elem egy lépésben: közös csoport
kat.atalakit(e, "zene")                                     # morph: alak és szín együtt
```
Alakok: `kor`, `haromszog`, `negyzet`, `otszog`, `rombusz`; minták: `None`, `"keretes"`, `"ures"`.
Két kategória azonos alakkal és mintával: létrehozáskor hiba.

## 7. Képlet tagonként szóra kötve (K2b)

```python
k = Keplet([(r"|A \cup B|", "unió"), ("=", "egyenlő"), ("|A|", ("A", 1)), ("+", "plusz"),
            ("|B|", "B"), ("-", "mínusz"), (r"|A \cap B|", "metszet")], hely=UP, meret="L", nev="kepl")
return [[*k.lepesek(rt=0.4)]]      # „Az unió egyenlő: A plusz B, mínusz a metszet.”
```
Minden tagnál kötelező a kimondott szó, vagy a kifejezett `None` (a tag a lépés elején jelenik
meg). `("A", 1)`: az első „A” szó. Egy tag: `k[i]`. Az egész egy tartalmi csoport. A tagok
sorrendje a kimondás sorrendje legyen; ha nem az, fogalmazd át a mondatot.

## 8. Venn2 (két halmaz, alaphalmaz)

```python
v = Venn2(nevek=("A", "B"), cimkek=("sport", "zene"), kozep=DOWN * 0.4, r=1.6, alaphalmaz=True, nev="venn")
```
Elemi régiók: `"a-b"` (csak A), `"ab"` (metszet), `"b-a"` (csak B), `"kivul"` (az alaphalmaz a
körökön kívül). Összetett: `"a"`, `"b"`, `"aub"` (unió); több kulcs együtt: a B komplementere
`("a-b", "kivul")`. A kör és betűje (és felirata) egy csoport, `cimke=`-viszonnyal.

| Metódus | Mit ad |
|---|---|
| `kor_rajzol(kulcs, tartalom=())` | lista: a kör a `tartalom` köré + betű, felirat |
| `alaphalmaz_keret(tartalom=())` | lista: az alaphalmaz kerete és az U |
| `regio(*kulcsok)` | a régió alakja |
| `regio_kiemel(*kulcsok, vonatkozik=())` | tartós kiemelés |
| `regio_pont(kulcs)` | az elemi régió felirathelye (lent) |
| `regio_szam(kulcs, ertek, ra=None, nev=None)` | szám a felirathelyen (megjelenítése a tiéd, `Szora`-val) |
| `hanyszor(kulcs, n, nev=None)` | „n×” a felirathelyen (0–3); váltás `atir`-ral, `Szora("kétszer")` |
| `helyek(kulcs, n)` / `elemek_helyre(elemek, regiok)` | rácspontok a régió felső részén / mozgatások |

Elrendezés `r = 1,6`-nál: a téglalap kb. 6,7 × 4,4 egység; a feliratok a téglalap fölött.
Sok körön kívüli elemnél szélesebb téglalap: `tobblet=2.6` (alap 1,6; a körökön kívüli sáv, egység).
A betűk és az U helyére elem nem kerül; a hosszú körfeliratok kifelé tolódnak.
Az elemeket előbb `elemek_helyre`, a következő elemben `kor_rajzol(kulcs, elemek)`.

## 9. Számolás, számláló, jelek

```python
sz = Szamolas(["6", "+ 5", "- 2"], "9", hely=DOWN * 0.4, nev="szamolas", pipa=True)
return [sz.lepesek(rt=0.5)]         # „Hat plusz öt, mínusz kettő, az kilenc.”
```
Minden számos tag a saját számnevére jelenik meg (azonos értéknél a k-adik a k-adikra). Az
eredmény (`=` és a szám, és a pipa) a lépés szabad `{}` horgonyára, ennek hiányában az érték
**utolsó** előfordulására jön; ha az nincs a tagok után, a render hibával áll le. A „− 6”
szóközzel műveleti jel, a „-3” előjel.

`Szamlalo(kezd, hely, meret, nev)`: `.fut(veg)` folyamatos számolás (a kapu a végét veti össze a
kimondással), `.valt(uj)` ugrás `atir`-ral. `pipa(poz)`, `kerdojel(poz)`, `hibas_kor(mob)` (kör a
szám körül és mellette egy X; a számot nem húzza át).

**Derékszög jele** (magyar jelölés: körív, benne pont; négyzetes sarok soha):
`derekszog(csucs, u1, u2, r=0.35, szin=FEHER, vastag=3, nev=None, csoport=None, vonatkozik=())`.
`u1`, `u2` a két szár iránya a csúcsból (bármilyen irány, pl. `B - A`; a sorrendjük mindegy): az ív a két
szár közti 90°-os tartományban fut, a pont a szögfelezőn a sugár felénél. Nem merőleges szárakra (±2°) hiba.
`vonatkozik=`: a szárak (előbb azok a helyükön, K7).

## 10. Amit a gép mér (a kapu, röviden)

Minden objektumra, elemtárból vagy saját kódból: **K1** horgony a szó előtt 0–0,2 s-mal;
**K2** a szám nem látszik 0,3 s-nál korábban, mint ahogy elhangzik (és nem előre, a következő
mondatból); **K2b** képlettag a szava előtt nem; **K3** semmi nem lóg ki, a sávba sem ér; **K4**
szöveg nem fed szöveget vagy jelölőt, vonal nem metszi a szöveget; **K5** betű ≥ 28; **K6** nem
csak színben; **K7** előbb a helyére; **K8** nincs felirat, a képen nincs öt egymást követő szó a
narrációból; **K9** egy lépés, egy kötetlen változás; **K10** a hang azt mondja, ami a szöveg;
**K11** ≤ 6,5 perc; **K12** kulcspont után megáll a kép (≥ 1,0 s).

## 11. Gyakori hibaüzenetek

| Üzenet | Teendő |
|---|---|
| `kötés kockája … nem az előző kötés után van` | a kötött elemek a szavak sorrendjében; vagy fogalmazd át a mondatot |
| `… k. előfordulása nincs a lépés szövegében` | a szó más alakban áll: más tő vagy szám, vagy `hanyadik` |
| `horgonyszerződés` | minden `{nev}`-hez pontosan egy `Horgony` (vagy `Szamolas`-eredmény) |
| `a kockaszámláló …, a terv kezd_kocka …` | az előző lépés túlfutott: kevesebb elem, rövidebb `rt` |
| `K7: kore_rajzol(…) ugyanabban a play-ben` | a mozgás és a köré rajzolás két külön elem |
| `nyers Transform szöveges objektumon` | `atir(regi, uj)` |
| `… indok nélkül` | a kapcsoló értéke egy rövid indokszöveg |
