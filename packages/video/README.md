# School Notes videólánc

A Manim tanulóvideók gépi munkalépései. Az `sn`-hez hasonlóan a címkézett kiadásból fut
(`~/.local/share/school-notes/release/current/packages/video/`). Az író a narrációt és a
jelenetkódot készíti; a lánc végzi a beszédkészítést, a szóidők meghatározását, a kockatervet,
a rendert, a kaput (K1–K14), a kontaktlapokat, a nyitó- és zárókép hozzáfűzését és a nyugtázást.

| Útvonal | Feladat |
|---|---|
| `video.sh` | `video.sh <learner> <subject> <page>-<n> [--atadas [--valtozott] \| --vegleges \| --meres \| --kivagat <step>/<obj> \| --takarit]`; a `video.py` a helyi `packages/school-notes2` uv-környezetében fut |
| `manim.sh` | külön `manim-env`, saját TinyTeX; a jelenetkód `from videotar import ...` sorral használja az elemtárat |
| `video.py`, `lanc/` | beszéd, szavak, render, nyitó- és zárókép, mérés |
| `hang.py`, `idoterv.py` | hangsegédek és kockaterv |
| `kapu.py`, `tabla.py`, `lapok.py`, `szamnev.py` | kapu, időtábla, kontaktlapok és számnévolvasó ([interfész](kapu-interfesz.md)) |
| `videotar/` | jelenetelemek ([API](videotar/API.md)), Manim 0.22-höz |

Kilépési kód: 0 zöld, 1 piros, 2 megállás (bemenet, verzió, zár, keret vagy időkorlát), 3 renderhiba.
A munkamappa a tanulói repóban (`.school-notes/out/video/<subject>/<page>-<n>/`), a Manim gyorsítótára
a `~/.cache/school-notes/video/`, a kész videó a `~/jegyzet/video-kesz/` alatt van.
A fizetős hívásokat a `school_notes2` podcastnaplója, gyorsítótára és költségkerete kezeli.

## Tesztek (fizetős hívás nélkül)

```sh
cd packages/video
uv run --project ../school-notes2 python -m pytest -q lanc/teszt hasznalat/test
videotar-teszt/render.sh                         # két szintetikus jelenet és elemtártesztek
kapu-teszt/kapu-teszt.sh [--render]              # a kapu elfogadási és regressziós próbái
```

A `VIDEO_CSONK=1` és `--mappa <folder>` a TTS-t és a Whispert szintetikus tesztadatra cseréli.
A tesztmintákban nincs tanulói adat vagy forrásszöveg; ezt a `packages/school-notes2` semlegességi
tesztje is ellenőrzi. A teljes kaputeszt: `uv run --project ../school-notes2 python -m pytest -q kapu-teszt`.

## Szóhoz kötött változás, követhető mozgás

A K1 a kötött rajz vagy mozgás mért időeltérésére figyelmeztet. A Szora/Horgony szavát
a szakasz további elemei öröklik; az explicit kötés megelőzi a régi `szo` attribútumot.
A kötetlen változás a tábla saját lépéssorában lektori adatként látszik. Hogy melyik tagmondathoz
tartozik, azt a lektor dönti el (mérce 2. szabály); a kötés hiánya önmagában nem kapulelet.
Az új teljes képlet K2b-figyelmeztetése indokkal elfogadható. Az ilyen elfogadás külön sorban
is látszik a tábla fejlécében, hogy a lektor elbírálhassa.
A K2b a tag saját szavához méri a megjelenést, ha ez a szó elhangzik az adott lépésben.
Csak az elavult saját szó helyett használja az explicit vagy örökölt szakaszkötést.

A K14 a ledarálás ellenőrzését segíti (mérce 11. szabály, 8. magyarázó elem).
A diagnózisból átvett figyelmeztetési határ összekapcsolt képrészeknél 60°/s,
önálló forgatásnál 120°/s. A 24 px fölötti tartalmi eltolásnál a kb. 0,5 s-nál rövidebb
időre figyelmeztet, a napló 1920×1080-as méretében. Ezek eszközbeállítások, nem új
mérceszabályok. A tábla a mért utat és időt is kiírja.

A forgásszöget csak a sugár két állása közti kisebb szög adja; a szögív nem növeli ezt.
A végállapotokból a köztes gyorsulás és a teljes fordulat nem igazolható.
A hiányos pálya a `kapu.json` mérési adatai között marad, nem figyelmeztetés.
Az új mérések nem adnak blokkoló hibát. A pontos feltételek és korlátok a
[kapu interfészében](kapu-interfesz.md), a geometria a `kapu_mozgas.py` modulban,
a regressziók a `kapu-teszt/test_kapu_masodik.py` és `test_kapu_review.py` fájlban vannak.

## A kapu címke- és fps-ellenőrzése

A K4 a vonalhoz tapadó címkét érintkezés nélkül is jelzi: különálló szöveg és vonal
között legalább 12 px rés kell az 1920×1080-as naplóban. A `vonatkozik`-kal deklarált
jelölés (keret, áthúzás, régió, nyíl) és egy idegen felirat között 8 px rés elég.
Az üzenetben a mért rés és az alkalmazott küszöb is szerepel.
A saját csoport törtvonala és a kiemelés kisebb rése önmagában nem lelet. A deklarált
aláhúzás és fókuszkeret csak a saját céljai és azok csoportja mellett mentes; idegen címke mellett kell a rés.
A metszést és érintkezést továbbra is vizsgálja.

A K7 a címke és a cél megjelenési sorrendjét is ellenőrzi. A kapcsolatot így add meg:
`jelol(cimke, vonatkozik=[cel])`. A címke az egész cél elkészülte után jelenjen meg.
Csoportnál a most látható és a címke élettartamán belül érkező tagokat várja meg;
a korábban eltűnt tag nem okoz téves hiányjelzést. A teljesen hiányzó csoport továbbra is lelet.
Kapcsolat nélküli régi kódban a kapu a közeli, külön megjelölt képletsorból is becsülhet;
ezt az üzenetben jelzi. A szándékos előzetes címet és a becslés bizonytalanságát a lektor bírálja el.

A K1 eltérő átlagos fps esetén a szekció fájljának névleges fps-ét, kockaszámát és
hosszát is lekéri. A legfeljebb egy képkockányi konténerkerekítés helyes névleges fps
és kockaszám mellett nem hiba. A részletes határok és kivételek a
[kapu interfészében](kapu-interfesz.md) olvashatók.

A regressziós próbák a meglévő `kapu-teszt/test_kapu.py` részei: szűk és megfelelő rés,
ferde és kör alakú vonal, saját és idegen címke melletti jelölés, a különböző résküszöbök határértékei,
hét különböző címkeelrendezés deklarált és
becsült céllal, helyes sorrend, eltűnés és újramegjelenés, a csoport változó tagsága, valamint
fps-kerekítés és valódi sebesség- vagy hosszeltérés. Fizetős hívást nem használnak.

## Használati videó (képernyőképekből)

A `hasznalat.sh` és a `hasznalat/` a jegyzetoldal általános bemutatójának gépi lánca.
A tanuló saját `sn publish --build-only` buildjéből dolgozik; `--jeloltek` teljes jelöltlistát,
`--elonezet` hang és videó nélkül kontaktlapokat, kaput és review-kulcsot készít. A narráció
és a szerepek JSON-fájljai közösek; tanulói adat csak a munkamappában keletkezik.

```sh
./hasznalat.sh TANULO --jeloltek BUILD --out OUT
./hasznalat.sh TANULO --elonezet BUILD --tantargy TANTARGY --lecke LECKE --out OUT
# Külön gyártási engedély és érvényes review után:
./hasznalat.sh TANULO BUILD --tantargy TANTARGY --lecke LECKE --out OUT
./hasznalat.sh TANULO --vegleges --out OUT
```

A 70 lépéses sablon felvevője a `study-site/capture-usage.mjs` és a `lib/usage-*` modulok; a H1–H10 kapu külön jelöli az előnézetben
még nem mért hangot és végleges videót. Hibamentes előnézetnél `zold: true`, de
`kiadhato: false`; a `nem_mert` felsorolja a hiányzó H4/H6/H7 mérést. Piros kép vagy elavult accept után fizetős gyártás nem indul.
A kész videót az `sn hasznalat` illeszti a kezdőlapra. A részletes kézikönyv az ops-repó
`docs/helyi/README.md` 3.9 és 5.10 fejezete.

Az asztali részletkamera a fő szöveghasábot és a kis cél teljes sorát/sávját mutatja.
A címkék fölötti bekezdés is a kép része; magas blokknál az utolsó sorok és a címke
maradnak láthatók. A H2 kapu a böngészőben mért szótéglalapokkal ellenőrzi a
kivágás széleit, a címke szövegkörnyezetét és a kiemelés nélküli kép fókuszkeretét.
A magas ábra teteje fölött 24 CSS px hely marad a kivágásban; a keret felső
éle és sarkai zártak, csak alul nyitott. A H2 a kirajzolt felső élt is ellenőrzi.
A keresőmező gépelés után elveszíti a fókuszt. A kezdőlap új témaválasztó
lépése a gomb aktuális látható feliratát használja narrációként és horgonyként.
A lecke jogosultságához tankönyves Óra-sor kell; bizonytalan dátum nem feltétel.
Az E2 feltételhez címke nélküli törzsbekezdés is kell, amelynek lábjegyzete
órai forrásra mutat. A jelöltvizsgálat a build privát nyugtájának forráshashével
ellenőrzött Markdownból, feloldott lábjegyzetlink alapján választ (helyi
`lesson-notes` lap vagy `sources/` forrás; a lábjegyzet neve nem bizonyíték).
Az első, a nyilvános DOM-ban is pontosan egyező, címke nélküli bekezdést mutatja.
Az ellenőrzés csak olvassa a tanulói repót; a privát forráshelyek nem kerülnek a
weboldalba. Hiányzó vagy elavult bizonyítékkal a lecke nem jelölt.
A szövegrész-szerepek DOM Range alapján mérik a nyilat követő sort és a robotjelet,
a dátumlink pedig az előzőleg bemutatott órasor leszármazottja.
A szóhoz kötött lenyitások előtti állapot külön kontaktképet is kap.

A gyártás a feloldott lépéssorrendből és a felvett mozgásból újraszámolja az
átmenetek időigényét. Ha kell, meghosszabbítja az előző mondat utáni csendet
(a kurzor és a kattintás idejével együtt), majd ebből készíti a hangot és az
időtervet. A narráció, a kontaktlapok és a meglévő review-kulcs változatlan marad.

Az oldalsáv kerete a menülinkek listáját, az „itt tartunk” kerete az összes
megjelölt leckesor egyesített dobozát fogja. A nem magas kiemelések mind a négy
oldala a képszélen belül fut; a H2 a kirajzolt keret zártságát is ellenőrzi.
A `dom_sorrend` jelű, egyoldalas, interakció nélküli lépéscsoportot a felvevő
a DOM olvasási sorrendjébe rendezi, és helyük szerint újraszámozza a lépéseket.
A feloldott forgatókönyvet és szerepeket menti; a kapu, kontaktlap, hang és
videó egyaránt ebből dolgozik. Külső lépésazonosítós interakció nem mutathat
ilyen csoportba. A `sorozat` címkeszerepek a kezdő címke után az első megfelelő,
még nem használt elemet választják, mindig az előző cél után; a típusok sorrendje
is a DOM-ból következik. A robotjel a legelső gépi tartalomcímke 🤖 részlete.

Teszt: `uv run --project ../school-notes2 python -m pytest -q hasznalat/test`; a böngészős
és felület-szerződés tesztek a study-site `npm test` és a school-notes2 `pytest` részei is.
Minden fixture szintetikus, minden hang a meglévő csonkból jön; a teszt nem fizet.
