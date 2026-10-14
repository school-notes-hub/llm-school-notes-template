# A kapu interfésze a láncnak (2a → 2b)

A kapu (K1–K13), a tábla, a lapok és a lépéskulcs a `kapu.py`, `tabla.py`, `lapok.py` és `szamnev.py`
modulban van. Manimot nem importálnak; a standard könyvtár mellett csak a Pillow kell (a lapokhoz),
ez a `school_notes2` uv-környezetében megvan. Elfogadási próba: `kapu-teszt/kapu-teszt.sh [--render]`.

## Hívás

```python
import kapu                        # sys.path: packages/video (a kiadott fában)
kod, sorok = kapu.futtat(mappa, atadas=False, valtozott=False)   # kod: 0 zöld, 1 piros
```
vagy parancssorból: `python kapu.py <mappa> [--atadas [--valtozott]]` (kiírja a sorokat, a kilépési kód ugyanaz).

- **alap mód** (az író 480p-s futása, és minden más futás): `kapu.json`, `tabla.txt`, `szoveg.md`. Kb. 0,1 s.
- **`atadas=True`** (a vezérlő 1080p-s átadása, a render után): ezen felül `kockak/`, `lapok/`, `kivagat/`,
  `lepeskulcs.json`. A kockák a `render_naplo.json` felbontásán, a Manim mp4-jéből jönnek
  (`media/videos/<modul>/<magasság>p<fps>/<Jelenet>.mp4`). Mért idő 1080p-n: 76 s-os videó, 25 kocka 2,9 s;
  egy 5 perces videó kb. 10 s.
- **`valtozott=True`** (csak `atadas` mellett): `lapok-valtozott/` a `lepeskulcs-1.json`-hoz képest
  változott lépésekre és a rájuk következő lépésre.
- **`sorok`**: az összefoglaló kapu-része (a KAPU sor, legfeljebb 6 HIBA és 12 FIGY sor, együtt 14, „… k további”,
  az állapotsor), a tábla sora (`tábla tabla.txt (…) · szoveg.md`), átadáskor a lapok sora. Ezt a lánc
  változtatás nélkül fűzi az összefoglalójába; együtt legfeljebb 20 sor.
- Hiányzó kötelező bemenet (`narracio.json`, `hangido.json`, `idoterv.json`): `FileNotFoundError`; ezt
  a lánc 2-es kódra fordítja. A hiányzó vagy elavult render (`render_naplo.json`, szekcióindex, a
  bemenetek hash-e) K1-hiba, nem kivétel.

## Bemenet (a munkamappában)

| Fájl | Kell | Mit használ belőle |
|---|---|---|
| `narracio.json` | igen | lépések szövege, `kulcspont` (K12), K8b |
| `hangido.json` | igen | `rate`, lépésenként `minta`, `beszed_kezd_s`, `beszed_veg_s` (K1, K2b, K9) |
| `idoterv.json` | igen | `fps`, `kocka_osszes`, lépések kockái, `horgonyok` (`kocka`, `szo_s`, `forras`), **`szavak`** (`szo`, `ertek`, `szo_s` abszolút, `forras`) a K2-höz |
| `szavak.json` | K10-hez | lépésenként a szavak; a **`whisper`** mező (amit a Whisper hallott) nélkül a K10 kimarad |
| `render_naplo.json` | igen (különben K1-hiba) | a `videotar/naplo-sema.json` szerint; a `bemenet` hash-eit a kapu újraszámolja |
| `media/…/sections/<Jelenet>.json`, `<Jelenet>.mp4` | igen | K1: szekciónevek, kockaszámok; átadáskor a kockák |
| `hang.wav` | igen | K1: hossz |
| `kezi.json` | ha van | a tábla „kézi” sora |
| `kapu-kivetel.json` | ha van | lásd lent |

A szavak `ertek` mezőjét a lánc a `szamnev.ertekek(szavak)` függvénnyel töltse (0–99, nulla, száz,
ezer, fél, toldalékok, -an/-en, -szor/-szer; „mínusz három”, „két egész öt tized”: az érték a kifejezés
első szaván). A K10 ugyanezzel olvassa a Whisper-szót. Ha az `idoterv.json` lépésében nincs `szavak`,
a kapu a `szavak.json`-ból számol (`kezd_kocka/fps + kezd_s`).

K10 lépésenként egy lelet: **hiba**, ha egy szám értéke más; **figy**, ha a Whisper egy narrációs szó helyén
kiejtés szerint is más szót hallott (`lanc.szavak.valtozott_szavak`; egy betű is számít: „számokat” →
„sámokat”), vagy ha a karakteres eltérés 20% fölött van. Szóváltozásnál a lánc már újrakérte a Whispert,
majd a hangot a pontos ejtés kérésével (`lanc/hangok.py`, mint a számnál); ami így is marad, az a nyugta
`k10_ketseges`-ébe kerül (lépés, idő, narrált szó, hallott alak, `fajta`: `szam`/`szo`), a tulajdonos csak
ezeket az időpontokat hallgatja meg. Ha a Whisper egy lépésre minden próbára szó nélkül válaszolt, az is
**figy** (`nincs_szo` mező), és a nyugtába kerül (`fajta`: `nincs_szo`, a lépés szövege, a beszéd kezdete).
A szóváltozás és a szó nélküli lépés figyelmeztetése `elfogad`-dal nem zárható (érvénytelen kivétel); a
lelet `szovaltozas` mezője a változott szavak száma. Zaj, nem lelet: a kiejtés szerinti írás
(`hangalak`: ly = j, i/í, u/ú, ü/ű hossza, zöngésség a torlódásban, t + sz = c, hosszú mássalhangzó csak
torlódásban: „halmaszt”, „meccet”, „minusz”), a betűnév („zé” – „Z”), a mértékegység jele a kimondott
neve helyett, toldalékkal és összetett egységgel is (`mertekegyseg`: „newtonméter” – „Nm”, „kilonewtont” –
„kN-t”, „fokos” – „°-os”, „méter per szekundum” – „m/s”), a „newton” kiejtés szerinti írása („nyúton”), az eltérő szószámú csere („efnek” –
„f nek”), és az egyenlő szószámú csere, amely egybefűzve azonos, vagy amelynek egy párja nem is hasonlít
(eltolt szóhatár). Lelet: a/á, e/é, o/ö, u/ü, o/ó, ö/ő („kör” – „kor”, „tört” – „tőrt”), a hosszú
mássalhangzó magánhangzók között („kell” – „kel”), más mértékegység („newton” – „kN”, „méter” – „cm”), és
az egyenlő szószámú csere minden eltérő párja
(„a számokat” – „az sámokat”: két szó).

## `kapu.json`

```json
{"sema": "videotar-kapu/1", "jelenet": "HibasJelenet", "minoseg": "480p30", "lepesek": 16, "kockak": 1533, "fps": 30.0,
 "bemenet": {"narracio.json": "<sha256>", "idoterv.json": "…", "szavak.json": "…", "render_naplo.json": "…"},
 "zold": false, "atadhato": false,
 "szamok": {"hiba": 8, "figy": 7, "elfogadva": 0, "teves_hiba": 0, "felulbiralva": 0},
 "allapot": "szinkron ✗ szám ✗ tag ! egy-változás ✗ kilógás ✗ átfedés ! betű ✗ szín ! helyére ! felirat ✗ hang ✗ hossz ✓ álló !",
 "leletek": [{"lepes": "h01-01", "kod": "K1", "sulyossag": "hiba", "obj": "h_pont1", "uzenet": "…"},
             {"lepes": "h01-10", "kod": "K4", "sulyossag": "figy", "obj": "h_felirat", "uzenet": "…",
              "doboz": [1139, 515, 1321, 565], "allapot": "vege"}],
 "ervenytelen_kivetelek": [], "jelzesek": [{"lepes": "h01-02", "uzenet": "rövidítés 0,44 (< 0,7): …"}]}
```
- A leletek sorrendje: lépés-id (a lépés nélküli, például K11, elöl), kód (K1, K2, K2b, K3 … K12, K13), objektumnév.
  `(lépés, kód, objektum)`-onként egy lelet, a súlyosabb. Bájtra azonos futásról futásra (nincs időbélyeg).
- `zold`: nincs felül nem bírált hiba. `atadhato`: zöld, vagy minden nyitott hiba „téves hiba?” jelölésű.
- `allapot`: ✓ nincs lelet, `!` csak figyelmeztetés, ✗ hiba.
- `jelzesek`: nem lelet, csak a táblában látszik (a 0,7 alatti rövidítés).
- **K13 üres kép** (mérce 9., „no empty screen”): a fő render (`media/…/<Jelenet>.mp4`, a nyitó- és
  zárókártya nélkül; azokat és az áttűnésüket a `--vegleges` fűzi elé és mögé, ezért nem lelet) egy
  ffmpeg-menetben, két `blackdetect`-ággal, 480 px magasra kicsinyítve (a 480p-s és az 1080p-s render
  ugyanazt kapja): `pix_th=0.10`, `d=1.0`; **hiba**, ha a kép legalább 99,95%-a sötét (`pic_th=0.9995`,
  üres kép), **figy**, ha legalább 99,9%-a (`pic_th=0.999`, szinte üres: egy kis jel a fekete képen; az üres
  szakaszokon kívüli darab számít, darabonként ≥ 1 s). A lelet a szakasz (darab) kezdő lépésén van, az üzenet az időtartományt és az
  érintett lépéseket adja („üres kép 0:05,5–0:11,9 (6,4 s; s01-02–s01-03)”). Lépésenként egy lelet; ha
  egy lépésben több szakasz kezdődik, egy üzenetben. Önálló kód, mert a K1–K12 egyike sem a kép
  egészét nézi; a K12 (álló idő) a változás hiányát méri, nem az ürességet. Költség: 480p-n kb. 2 s egy
  6 perces videón, 1080p-n kb. 10 s (a dekódolás). Mért: egy 6:05-ös kész videón figy 0:05,5–0:11,9 („A =”
  egyedül a fekete képen), a mintavideón nincs lelet. `kapu.sotet_szakaszok(mp4, hossz_s)`
  a mérés, `kapu.k13(mu, szakaszok=None)` a lelet.
- **K4 vonal és szöveg:** a vonal metszi a szöveget (a doboz 4 px-es belsejében), vagy a szélén fut (a
  doboztól legfeljebb 2 px-re, `ERINT_PX`: a vonás a betűkhöz ér; méretvonal a címkén, címke a test élén). A
  `ra` kapcsoló a `vonatkozik`-kal deklarált jelölésen (fókuszkeret, kiemelés, nyíl) csak a saját céljait menti
  fel (amit körülvesz), más feliratot nem; `vonatkozik` nélkül mindent (szám a régióban).
  **K4 fókuszkeret** (`keret` töröttvonallal és `vonatkozik`-kal; a halmazkör nem): két keret rése legalább
  3 px (`KERET_RES_PX`; különben „összeér” vagy „egymásba lóg”; a beágyazott keret nem lelet), és a keret éle
  nem fut 40 px-nél hosszabban 6 px-en belül egy másik, nem jelölt elem vonalán (`PARHUZ_PX`, `PARHUZ_HOSSZ`:
  egybeolvad vele; a merőleges keresztezés, a kiemelés és az ugyanarra vonatkozó jel nem lelet).
- **K7 üres keret:** a keret vagy kiemelés marad, de minden célja (`vonatkozik`, ismert név) eltűnt.
  **K7 végső hely:** új vonal jelenik meg egy másik elem mozgása alatt, és a vége a mozgó elem végső helyéhez
  igazodik (ugyanabban az oszlopban vagy sorban, 2 px-en és 150 px-en belül, vagy hozzáér), a kiinduló
  helyéhez nem (a mozgást követő nyom nem lelet).
- **K1 kapcsolt jel (figy.):** egy vonal eltűnik, mialatt az elem, amelyhez a vége kapcsolódik (a lépés elején
  3 px-en belül a vonalán, vagy `vonatkozik`), még mozog: a változás előrefut. Nem lelet a keret, a kiemelés, a
  lépésben maga is mozgó (követő) jel és az áttűnéses csere (ugyanolyan fajtájú új elem ugyanakkor).
  Mért (2026-10-14, a kész videókon): hét kész videó új K4-leletei mind valósak
  (kivágaton ellenőrizve), új K7- és K1-lelet nincs; a lektori kapurés-leletek régi változatain mind megjelennek.
- K8a a `--vegleges` dolga: `kapu.k8a(mp4) -> list[lelet]` (ffprobe: 1 videó- és 1 hangsáv, se fejezet,
  se felirat, se cím-metaadat); üres lista = rendben.

## `kapu-kivetel.json` (az író és a vezérlő írja)

```json
{"elfogad":     [{"lepes": "s02-05", "kod": "K4", "obj": "szam_ab", "indok": "a szám a régió felirata"}],
 "teves_hiba":  [{"lepes": "s03-04", "kod": "K2", "obj": "szam_19", "indok": "a 19 a tizenkilenc szóra jön"}],
 "felulbiral":  [{"lepes": "s03-04", "kod": "K2", "obj": "szam_19", "indok": "eszközhiba: …"}]}
```
- `elfogad`: az író, **csak figyelmeztetésre**, indokkal. `teves_hiba`: az író, hibára; a kapu piros
  marad, de `atadhato`. `felulbiral`: **csak a vezérlő**, hibára; a hiba nem számít a zöldbe. Gépileg is csak vezérlőmódban
  (`--atadas`, `--vegleges`) számít; az író 480p-s futásában érvénytelen kivétel („csak a vezérlő, --atadas”).
  Az összefoglaló minden felülbírálást soronként mutat (`FELÜLBÍRÁLVA`).
- Az illesztés pontosan `(lepes, kod, obj)`; `obj` lehet `null`. Üres indok, nem létező lelet vagy rossz
  súlyosság: `ervenytelen_kivetelek`, és a tábla is mutatja. Minden elfogadás, jelölés és felülbírálás
  indokkal a táblában és a `kapu.json`-ban látszik.

## Átadás: lapok, kivágatok, lépéskulcs

- `kockak/<jelenet>-eleje.png`, `<lépés>@<horgony>.png` (a horgonyos szakasz utolsó kockája),
  `<lépés>-eredmeny.png` (a `Szamolas` eredménye, ha nem a vége-kocka), `<lépés>-vege.png`.
- `lapok/NN-<jelenet>[-b|-c…].png`: 1920×1140, 3×3, cellánként 640×360 + 20 px címkesáv
  (`t02-05 @metszet 0:32,0`, `t02-05 vége 0:33,2`, `t01 eleje 0:00,0`); `!` és sárga címke annak a lépésnek
  a kockáin, amelyen nyitott (nem elfogadott, nem felülbírált) lelet van. A jelenet új lapon kezdődik.
- `lapok-iro/NN-<jelenet>[-<jelenet>].png` (az író 480p-s futása, nem átadás): ugyanazok a kockák sűrűbben,
  4×4 cella 480×270 + 20 px címkesáv (1920×1160), a lapok jelenethatáron is folyamatosan telnek; a lánc lábsora
  megadja az útjukat. Az író átadás előtt egy üzenetben nézi meg őket (10. és 12. szabály).
- `kivagat/<lépés>-<obj>.png`: minden K4, K6b, K7 figyelmeztetésre, a lelet `doboz`-ára + 40 px margó,
  legalább 600×400, a lelet állapotának kockájából, a render felbontásán.
- Az író `--kivagat <lépés>/<obj>`-ja: a lánc rendereli az állóképet (`IG=<lépés>`, `-qh -s`), és
  `lapok.iro_kivagat(mappa, lepes, obj, kep_png)` vágja ki (`kivagat/iro-<lépés>-<obj>.png`; az `obj`
  lehet csoportnév is).
- `lepeskulcs.json`: lépésenként `szoveg`, `esemenyek` (a lépéshez mért relatív idők, a kötött szavak),
  `vege` (objektumok 2 px-re kerekített dobozzal); az automatikus sorszám (`Text#7`) nem számít.
  **Forgatás:** átadáskor a régi `lepeskulcs.json` `lepeskulcs-1.json` lesz, ha az új eltér tőle (azonos
  újrafuttatás nem forgat). A `--valtozott` a `lepeskulcs-1.json`-hoz mér; ha az nincs, minden lépés változott.

## Ami nem a kapué

Render, hang, Whisper, zár, keret, `--vegleges` összefésülés, `meres`: a lánc (2b). A rendert nem érő
kódok (K6a, futásidejű K7) a `videotar-teszt` pytestjében vannak.
