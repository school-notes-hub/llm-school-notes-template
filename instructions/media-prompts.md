# Reusable learning-media prompts

These shared prompts implement [media workflows](media-workflows.md) under [AGENTS.md](../AGENTS.md). Read only the prompt for the requested stage. Fill placeholders from the current request, local profile and verified sources; the template supplies no learner, subject, account or spending authorization. The original Hungarian prompt language is preserved as functional text; `{wiki_nyelv}` is the configured learner-facing language. Never pass raw private profile details that are irrelevant to a generation request.

## Content scope

```text
Feladat: {keres}. Tanuló: {relevans_profil}. Források: {wikioldalak_es_verziok}. Aktuális tanulási döntés és célzott követelményhelyek: {tanulasi_hatokor_es_kovetelmenyek}.
Olvasd végig az érintett jegyzeteket és kövesd a szükséges forráshivatkozásokat. Ne generálj médiát.
Készíts rövid munkalapot ezekkel a mezőkkel:
CONTEXT: Mi ez a téma, milyen tágabb kérdésbe tartozik, miért érdemes megérteni? Csak a megértéshez szükséges háttérdimenziókat válaszd ki a forrásból.
Történelmi témánál a CONTEXT kötelező része az igazolt korszak/időszak és a földrajzi hely: tágabb régió, és ha segít, a mai elhelyezkedés. Ne keverd a lecke dátumával; a különböző korszakokat válaszd szét. Ez látható/hallható tanulási tartalom, nem rejtett metaadat.
SCOPE: Először használd újra a lecke érvényes döntését. Új követelményolvasás csak fennmaradó prioritás-, mélység- vagy alkalmazhatósági kérdésnél indokolt. A curriculum nem tantárgyi tényforrás. Ellenőrizd a tanulási döntést az aktuális leckével: relevancia, elvárt műveleti mélység, indokolt emelt szint, opcionális kitekintés. Követelményből csak pontos helyhez és szinthez kötött elvárást használj, ne adj hozzá teljes tantervi témakört.
GOAL: Mit tudjon a tanuló az anyag után saját szavaival elmagyarázni vagy elvégezni?
BRIDGE: Mely előfeltételek szükségesek? Mi igazoltan ismert a profilból, és mit kell itt röviden megtanítani?
CORE: A tanulási célhoz nélkülözhetetlen állítások, kapcsolatok vagy műveleti lépések, rövid azonosítóval. Mindegyikhez forráshely, megőrzendő feltétel és bizonyossági státusz tartozzon.
QUESTIONS: Mely fontos miért/hogyan/mikor kérdésekre adjon választ az anyag? Írd melléjük a forrásból alátámasztott válasz lényegét.
OPTIONAL: Másodlagos részletek, saját szemléltető példák és indokolt kihagyások.
GAPS: Hiányzó bizonyítékok, ellentmondások, bizonytalan olvasatok. Nevezd meg pontosan, mi hiányzik és melyik forrásból; különítsd el az olvashatatlan vagy levágott részletet a tényleges hiánytól és a feladat szándékos ismeretlenjétől. Írd mellé a megalapozott feloldást vagy a tanulási feladatra gyakorolt következményt; a kihagyás okát ne találd ki.
FOGALMI PONTOSSÁG: Minden tantárgyban a szakkifejezéseket a megfelelő jelentésükben használd. Pontosan nevezd meg a fogalmat, tárgyat, tulajdonságot, mennyiséget vagy kapcsolatot, és mondd ki a szükséges feltételeket. Például nem mindegy, hogy erőről, az erő nagyságáról vagy előjeles komponenséről beszélsz. Ugyanez a pontosság kell a prózában, képfeliratban, összefoglalóban és válaszban is.
OLVASÁSI SORREND: Mire egy állításhoz, ábrához vagy számoláshoz ér a tanuló, ismerje a megértéséhez szükséges fogalmakat, jelöléseket és feltételeket. Ha az „érték”, „méret”, „ez” vagy más utalás vonatkozása a helyén nem egyértelmű, nevezd meg a mennyiséget vagy tárgyat; a világos rövidítést ne cseréld gépiesen. A megértéshez szükséges rövid feloldás helyben szerepeljen, ne csak egy későbbi részben vagy linken. A forráshiány részlete privát lábjegyzetbe vagy bizonyítékrekordba kerüljön; a tanulást érintő korlát tárgyi magyarázata a kép mellett legyen; a képre a tanuláshoz szükséges jelölések kerüljenek. A tartalmi bizonytalanság maradjon látható, a technikai háttér ne terhelje a tanulót.
A fontosságot a felhasználói cél, az órai hangsúly és a megértési függőség határozza meg, ne a látványosság.
A saját példát jelöld példaként; feltételezést és kiegészítést ne emelj észrevétlenül biztos tananyagi ténnyé.
Ha egy nélkülözhetetlen hiány nem tisztázható a rendelkezésre álló bizonyítékból, állj meg a véglegesítés előtt és nevezd meg, mi szükséges.
```

## Representation and drawing plan

Use this stage for a new visual or a changed representation. Reuse an applicable decision; record the relevant detail in the existing compact visual plan. The [selection guide](technical-visuals.md) owns the detailed rules. This is an internal planning stage, not an additional approval gate: continue authorized production after resolving the plan.

```text
Feladat és érvényes tanulási cél: {keres_es_scope_goal_core}. Források/feltételek: {forrashelyek}. Közönség/előismeret és megjelenítés: {relevans_kontextus_es_meret}. Ismert elérhető eszközök: {eszkozok}.
A technical-visuals.md alapján tervezd meg, milyen ábrázolásból tudja a tanuló a vállalt műveletet elvégezni. A kontextus, téma, tanult jelölés, tartalom jellege, szükséges pontosság és olvasási méret együtt döntsön; a tantárgynév ne válasszon automatikusan eszközt.
Minden füzet- és kézi táblarajz kötelező: ugyanazt mutassa, ugyanabban a szerepben, helyesen. Csak a jelentést hordozó elrendezés kötött; nincs rekonstrukciófelirat vagy füzetre utalás az ábrán. Új képhez a művészi illusztráció, pontos konstrukció, összetett ábra, meglévő kép vagy szöveg/táblázat egyaránt mérlegelhető; egyik sem győz alapértelmezetten. Csak jelentős határesetnél indokold röviden a valóban alkalmas alternatívák közötti választást.
Nevezd meg a forma fontos hallgatólagos állításait és azt is, amit nem tud megmutatni a feladatból. Ne sugallj igazolatlan sorrendet, egyidejűséget, folytonosságot, kizáró kategóriát, arányt, okságot vagy pontos helyet. A bizonytalanságot láthatóan kezeld vagy változtass formát.
A képességalapú eszköztárból válassz megvalósítást; alapműveletekből listán nem szereplő ábra is építhető. Matplotlibnél adatot/függvényt és leképezést, formális diagramnál a cselekvés, állapot, üzenetsorrend és időtartam helyes jelentését tervezd. Renderelést ne keverj a számítással vagy fizikai szimulációval.
A meglévő képtervet egészítsd ki a szükséges konkrét rajzi specifikációval: elemek/adatok és feltételek; jelentés → rajzi elem megfeleltetés; fókusz/nézet/elrendezés; pontos kötelező feliratok; előállítási műveletek/export; ténylegesen ellenőrizhető viszonyok és félreolvasási kockázat. Ne készíts külön rekordot vagy kötelező üres mezőket.
A fallback ugyanazt a tanulói műveletet, szükséges hűséget és olvashatóságot támogassa, az adott viewerben/nyomtatásban is. Ha nincs ilyen elérhető út, nevezd meg a valódi hiányt. Ne állíts kipróbált működést pusztán dokumentációból; a választás nem új telepítési vagy költési engedély.
Add vissza a kivitelezhető tervet és a releváns ellenőrzések módját. Ez a lépés még ne rendereljen vagy indítson szolgáltatói hívást.
```

## Visual decision and provider-prompt assembly

```text
A lecke érvényes SCOPE–GOAL–BRIDGE–CORE–OPTIONAL döntéséből és a megfelelő rajzi tervből indulj. A reprezentációt a Representation and drawing plan lépés és a technical-visuals.md szerint válaszd ki; meglévő érvényes tervet használj újra. Ez a lépés a kiválasztott generált kép szolgáltatói promptját állítja össze.
Először azonosítsd és őrizd meg a tananyag szükséges pontos ábráit. Ezután döntsd el, ad-e külön tanulási értéket meglévő kép vagy új infografika; egy oldalon a pontos ábra és a hasznos infografika együtt is szerepelhet. Egyetlen tantárgynál sincs kizárva az infografika: az ábra szerepe és pontosságigénye dönt. Bannernél konkrét bevezető szerepet, kapcsolódó motívumot vagy dekorációt válassz.
Indokold a hozzáadott tanulási értéket. Két képet csak két külön, hasznos tanulói feladathoz tervezz.
A füzet és a tanulandó tanári anyag minden pontosságot igénylő tanítóábráját, matematikai/formális szerkezetét, nyelvi elemzését, mennyiségi grafikonját és műszaki rajzát rajzold újra ugyanabban a szerepben, szakmailag helyesen, pontos, szerkeszthető formában; a biztos hibát tartós javításcímke jelöli, az eredeti eltérés privát bizonyítékba kerül. A tartalomhoz válassz önállóan szerkeszthető, determinisztikusan megjelenített SVG-t, kódot, adatdiagramot vagy szedett jelölést; az ábra maradjon az oldalon elérhető. A generált újrarajzolás akkor sem megőrzés, ha pontos referenciából készült. Őrizd meg az órán tanult jelölésrendszert, az eseteket és jelentést hordozó sorrendjüket, a jelentést hordozó tájolást, kapcsolatokat, szükséges geometriát, skálákat és feltételeket; a forrás és a kész oldal lefedettségét a meglévő kétirányú önellenőrzési rekordban vesd össze. Más jelölés csak megnevezett alternatívaként jelenjen meg. Bizonytalan részletet ellenőrizz vagy jelölj nyitottnak; ne találd ki és ne hagyd el észrevétlenül.
Írd meg a képen látható kontextust: mi ez a rendszer, tárgy vagy szöveg; mi a kérdés; mit jelent a nélkülözhetetlen fogalom vagy számozott hivatkozás.
A kötelező szöveget végleges formában, olvasási sorrendben add meg. A generátor ne válasszon tényeket, példát vagy prioritást.
A tanulói feladathoz válassz nézőpontot és kivágást; a lényegi rész legyen látható. Szükség szerint használj megkülönböztetett részletnézetet vagy metszetet. Összehasonlításnál tartsd közösen a helyes értelmezéshez szükséges skálát, nézetet, egységet és jelölést.
Nevezd meg a stílust indokló releváns témabeli/kontextuális támpontot, és ebből válassz képi világot és palettát, ne csak tantárgycímkéből. Ha hasznos, örököld az összetartozó témakör/képsor stílusát. Őrizd meg az olvashatóságot és a közös fogalmak szín-/jelölésazonosságát; lényegi különbséget ne csak szín mutasson. Korszak, hely, mű világa, anyag, viselet vagy hangulat csak releváns, alátámasztott részletet irányítson; bizonytalanságot ne tölts ki kitalált hitelességgel. A hangulat ne torzítsa a magyarázatot.
Bármely eszköznél nevezd meg a tanulási állítást hordozó pontos részletet és annak ellenőrzési módját: forrás/jelölésszabály, paraméter, tényleges geometria, kapcsolat vagy mozgási feltétel. A fogprofil, menet, faljelölés vagy más lényegi részlet helyességét a szép render nem bizonyítja. A végső nézetet külön is ellenőrizd; animációnál az előírt mozgást ne nevezd fizikai szimulációnak.
A képi tervben csak a feladathoz releváns döntéseket részletezd: goal = tanulói művelet; composition = fókusz, nézet és szerkezet; style = indokolt képi világ/paletta; constraints = tényleges pontossági és félreérthetőségi korlátok. A teljes mérlegelési listát ne másold a generáló promptba.
A sorrend jelentését, összehasonlítás szempontjait, csoportosítást, topológiát vagy metaforát csak akkor részletezd, ha a választott kép használja. MÁS/ELSE: tervezz indokolt új vagy vegyes megjelenítést.
Példánál rögzítsd az ellenőrzött esetet, feltételeket, következményt és megengedett tanulságot. Válassz életszerű, felismerhető problémát vagy különbséget: miért számít itt a tanított összefüggés? Hasonlíts össze lehetséges példákat; a fizikailag helyes, de a hasznot elfedő vagy mesterkélt helyzet helyett válassz egyértelműbbet. A banner a témát mutatja, nem annak egy példáját. Mérlegeld, hogy az elv másik esete jobban tanítja-e az általánosítást.
A szolgáltatónak átadott prompt: cél/felhasználás; látható bevezetés; pontos kötelező tartalom és kompozíció; opcionális motívumok; stílus/méret; releváns korlátok. A privát profil, forrásútvonalak és belső munkalap maradjanak a munkarekordban.
```

## Banner

```text
Készíts {méret/képarány} széles, alacsony fejlécillusztrációt a {téma} tanulási oldalhoz, {célközönség} számára.
A banner feladata: {a téma bevezető/áttekintő megmutatása vagy semleges dekoráció}. A témát mutassa, ne a példát vagy a forrást; a {legfiatalabb fő olvasó a PROFILE *Audience* szerint} már az oldal megnyitásakor, olvasás előtt értse. A felirat tényét a próza is tanítsa.
Fő motívum vagy szerkezet: {ellenőrzött képi terv}. Nézőpont és kivágás: {a lényegi rész láthatóságát biztosító nézet}. Fókusz és olvasási sorrend: {telefonon is felismerhető fő olvasat}.
Kötelező látható szövegek, pontosan: {végleges rövid címek/kontextus, vagy nincs}.
Kapcsolódó elhagyható részletek: {motívumok}. Stílus: {a témához indokolt képi világ, paletta, anyagkezelés és hangnem; releváns közös jelölések és kerülendő mellékjelentések}.
A kép legyen szép, elnézegethető, szellős; maradjon alacsony banner. Ne apró betűvel helyezd el, ami nem fér bele. Ne adj hozzá új tényt vagy feliratot.
Ábrázolás jellege: {szemléltető/műbeli/metaforikus/forrással igazolt}. {Csak releváns: metaforikus megfeleltetés és kerülendő mellékjelentés; pontos sorrend, időarányosság, kapcsolatok vagy összehasonlítás.}
{A konkrét képnél szükséges pontossági korlátok.}
```

## Podcast script

The „Képben vagy?” script is written by the podcast writer under its role text (`school-notes-ops/docs/helyi/szerepek/podcastiro.md`) and handed over as `adas.json` ([Helyi menet](helyi-menet.md) *Podcast episodes*); the rules in short are in [Media workflows](media-workflows.md) *Podcast*. A prompt for it:

```text
Írj egy „Képben vagy?” adást {wiki_nyelv} nyelven a(z) {témalap} témalapról, a {profil} tanulójának: 2–5 perc beszélgetés Dani (műsorvezető) és a tantárgy vendége, {vendég} között. Egy adás egy téma.
A vendég köszön be, azután Dani viszi a műsort. Konkrét helyzettel nyiss, a fogalom erre feleljen; beszéljétek meg, miért fontos és mire jó. A végén: mit kell ebből biztosan tudni a dolgozatra (2–3 pont), aztán Dani elköszön.
Igazi beszélgetés legyen: egymásra reagálnak, összekötnek, visszamondják a saját szavukkal. Nincs „gondold végig” szünet, kikérdezés, előre tudott válaszú kérdés, szándékos tévedés vagy kijavítás, töltelékmondat.
Minden nevet, fogalmat és utalást az első előfordulásakor vezess be. Csak a témalap tényei; forrásra ne utalj. Számolós tárgynál levezetés nincs.
A felolvasói változatban mindent úgy írj ki, ahogy kimondjuk (szám, dátum, sorszám, római szám, rövidítés); a nevekhez add meg az elfogadott kiejtést.
```

## Presentation storyboard

```text
A {tartalmi_szerzodes} alapján tervezz önállóan tanulható, {wiki_nyelv} nyelvű PDF-et a {profil} tanulójának. Őrizd meg a célnyelvi példák és funkcionális szövegek eredeti nyelvét. Diaszám: {kert_vagy_javasolt}.
Először a TELJES storyboardot add vissza. Oldalanként: cím, egy összetartozó tanulási pont, pontos látható szöveg, vizuális magyarázat, CORE-azonosítók/forráshelyek, kapcsolat az előző és következő oldallal.
Az első oldalakon röviden helyezd el a témát és vezesd be a szükséges alapokat. Ezután magyarázz fokozatosan; a fontos kérdésekre az oldalak tartalma adjon választ.
Egy oldal több összetartozó részletet is taníthat. Az olvasó külső előadó és rejtett jegyzet nélkül értse a magyarázatot, az ábrák jelentését és a következtetést.
Ne készíts darabszámkitöltő címlapot vagy záróoldalt. Ellenőrizd a teljes lefedettséget és a követhető sorrendet, mielőtt egyedi képpromptokat írsz.
Rögzíts közös megjelenést: címhely, szöveghierarchia, következetes fogalomszínek, illusztráció és forrásjelölés. A tartalom határozza meg az oldal kompozícióját.
```

## Infographic layout

```text
A {tartalmi_szerzodes} és a releváns {profil} alapján tervezz {wiki_nyelv} nyelvű tanulási ábrát. Még ne generálj képet. Őrizd meg a célnyelvi példák eredeti nyelvét.
Előbb írd meg a képen látható bevezetést és a szükséges fogalmi hidat. Ne keverd a sorrendet az oksággal, a változást szükségszerű javulással, a kontinuumot két kizáró kategóriával. Példát csak ellenőrzött adatokkal, feltételekkel és megengedett tanulsággal adj; a generátor ne találjon ki esetet.
Mondd meg röviden: mit tudjon a tanuló a képből felismerni, elmagyarázni, összehasonlítani vagy elvégezni; ehhez milyen tartalmat kell láthatóvá tenni.
Ezután válassz formát. Támpont lehet feliratozott tárgy/jelenet vagy metszet, térbeli ábra, idővonal, összehasonlítás, mennyiségi diagram, csoportosítás, lépéssor, mechanizmus, kapcsolati rendszer vagy ezek indokolt kombinációja. Ezek példák, nem zárt lista.
MÁS/ELSE: ha egyik sem megfelelő, nevezd meg a tartalom tényleges természetét, és tervezz hozzá saját vagy vegyes ábrázolást. Ha új kép nem ad érdemi tanulási többletet, válassz újrafelhasználást vagy kép nélküli megoldást.
Adj rövid tervet: cél és fő üzenet; forma és indoka; kompozíció/olvasási sorrend; pontos feliratok és CORE-forráshelyek; szükséges vizuális állítások; méret és ellenőrzendő pontok. Csak a feladathoz szükséges mezőket részletezd. A pontosságot igénylő geometriát, formális/nyelvi szerkezeteket, képleteket és adatábrákat tartsd ellenőrizhető szerkesztett alapokon. A külön pontos ábra megmarad; összetett képben a generátor ne rajzolja újra a pontos réteget, inkább utólagos ellenőrzött összeállítást vagy külön ábrát válassz. Egy beküldött referenciakép önmagában nem igazolja a végső pontosságot.
Csak kapcsolati ábránál tervezz topológiát: csillagpontos, valóban körkörös, láncszerű, hierarchikus, összetett hálózatos vagy más, a tartalomból felismert szerkezetet. Rögzítsd a kapcsolatok jelentését, végpontjait, irányítottságát és feltételeit. Egy közös rendszert ne darabolj szét a nyilak egyszerűsítése kedvéért. Panelt akkor válassz, ha segíti a feladatot. Körforgást csak igazolt körfolyamathoz használj: a központ körüli oda-vissza csere önmagában nem körforgás.
Lehet részletgazdag, nézegetésre hívó jelenet, ha a részletek tananyagi fogalmakat tesznek felismerhetővé és nem takarják el a lényeget. Ne találj ki történeti vagy szakmai állítást a látvány kedvéért.
Történelemnél írd meg a képen belüli rövid, igazolt idő- és helymegjelölést.
A kötelező tartalmat ne hagyd ki és ne zsugorítsd olvashatatlanra. Ha nem fér el, a fizetős generálás előtt rendezd a fókuszt vagy a bontást.
```

## Printable study notes

```text
Készíts nyomtatható tanulási jegyzetet a {tartalmi_szerzodes} és az aktuális {wikioldalak_es_verziok} alapján, a {profil} tanulójának. Kért oldalkeret: {keret_vagy_nincs}.
Először tervezz fejezetsorrendet és becsült terjedelmet. Legyen rövid eligazítás, tanulási cél, a szükséges alapfogalmak bevezetése, összefüggő magyarázat és indokolt kidolgozott példa. A CORE minden elemének legyen helye; a BRIDGE magyarázata ne maradjon link mögött.
Őrizd meg a tanult tartalom, a magyarázat és az opcionális mélyítés forrásjelölését. Emelt követelmény ne bővítse automatikusan a lecke magját. A {wiki_nyelv} nyelvű magyarázat mellett őrizd meg a célnyelvi példákat és funkcionális szövegeket.
Válaszd ki azokat a ténylegesen ellenőrzött ábrákat, amelyek a papíron tanuláshoz szükségesek; magyarázd meg a jelöléseket a szövegben. Pontos szakmai ábra maradhat SVG/vektoros eredetű. A fejezetek ne igényeljenek kattintást, rejtett kommentet vagy külső előadót a megértéshez.
Zárj rövid összefoglalóval és néhány célhoz illő önellenőrző kérdéssel. A számozott válaszok és a megoldásmenet külön utolsó részbe kerüljenek, lehetőleg új oldalon. A kérdés tanítsa vagy ellenőrizze a vállalt célt, ne hozzon be új, meg nem magyarázott tananyagot.
A kimenet álló A4-es, kijelölhető és kereshető törzsszövegű PDF legyen. Ne generált képként készítsd el az egész oldalakat. Használj takarékos, szürkeárnyalatban is értelmezhető megjelenést és szerény jegyzetelési helyet. Ha a kért terjedelem szűk, ne zsugorítsd a betűt és ne hagyj ki szükséges lépést; jelezd a természetes bontást vagy szűkebb fókuszt.
Ellenőrizd a forrásokkal a teljes szöveget, a kérdés-válasz párokat és a CORE lefedettségét. A kész PDF minden oldalát rendereld és nézd meg, továbbá ellenőrizd a szövegkinyerést. Add vissza a dokumentumot, a forrásváltozatokat és az ellenőrzés rövid rekordját.
```

## Image generation

```text
Készíts egy {infografika_vagy_dia} képet ebből az ellenőrzött tervből: {ellenorzott_terv}.
Először a terv látható bevezetése orientálja az olvasót. Különítsd el a kötelező szövegeket az elhagyható motívumoktól; az előbbiek nem hagyhatók el helyhiány miatt.
Kövesd a választott kompozíciót, pontos feliratokat, vizuális állításokat és olvasási sorrendet. Ne adj hozzá új tényt vagy kapcsolatot.
Megjelenés: {a témához választott stílus, paletta és releváns jelölések}. Pontos szöveg és nyelve: {szoveglista}. Méret/tájolás: {a4_tajolas}. Biztonsági margó: legalább 10 mm az A4-es elhelyezésben. A végleges nyomtatási méretben legyen olvasható minden kötelező felirat; a megfelelő képrész közelében helyezd el. Őrizd meg az ékezeteket, számokat és célnyelvi példákat.
Csak ha a terv kapcsolatokat tartalmaz: irányítatlan viszonyhoz ne adj nyílhegyet; egyirányú kapcsolaton csak a célnál legyen nyílhegy. Eltérő jelentésű oda- és visszaáramlást külön feliratozott nyilak mutassanak. A végpont, címke és feltétel egyértelműen összetartozzon.
A megnevező segédvonal, a lépéssorrend és a tartalmi kapcsolat jelölése ne legyen összetéveszthető. Ne feltételezz minden feladathoz topológiát.
A tervben megadott lényegi rész maradjon látható a választott nézőpontból; a címke ne takarja. Az összevetett nézeteknél őrizd meg a terv közös skáláját és jelölését. A hangsúlyozás, méret és csoportosítás ne sugalljon új mennyiséget, rangsort vagy kapcsolatot.
A részletek támogassák a terv tanulási célját. A szemléltető jelenet ne állítson igazolatlan rekonstrukciót, pontos földrajzot vagy méretarányt.
```

## Independent review and repair

```text
Vizsgáld meg a {tenyleges_kimenet} teljes tartalmát. Az összehasonlítás alapja a {tartalmi_szerzodes} és az eredeti {forrashelyek}, ne csak a generáló prompt legyen.
Először ellenőrizd, hogy a szerződés hű-e a forrásokhoz; a hibás tervet a pontos képgenerálás sem javítja meg.
Olvasd végig a kész anyagot a tanuló sorrendjében: időben megkapja-e az előfeltételeket, és minden fogalom, mennyiség, jelölés és utalás pontosan azonosítható-e? A terminusokat a szakterületi jelentésükben használja-e? A tanulást érintő hiány és a szükséges feloldás vagy korlát tárgyi nyelven, a megfelelő helyen látható-e, miközben a forráshely és az eredeti hiba privát marad? A homályos részt ott javítsd, ahol először megakasztja a megértést.
Keresd a kihagyott CORE-elemeket, hozzáadott állításokat, elveszett feltételeket, hibás neveket/számokat, képi irányokat, magyarázat nélkül használt fogalmakat és ugrásokat.
Vizsgáld meg, hogy a scope vállalt mélysége, magja és szükséges hídja megmaradt-e, és nem lett-e opcionális részletből kötelező tananyag. Példánál a tanulság következzen a látható esetből; metafora ne váljon hamis tényállítássá.
Az érintett teljes oldalon ellenőrizd, hogy a forrás minden pontosságot igénylő tanítóábrája, formális/nyelvi szerkezete és külön esete megmaradt-e pontos formában. Egy általános infografika nem helyettesíti az ábraszerkezetet; nem kell viszont minden infografikában újra szerepelnie a mellette megőrzött teljes elemzésnek vagy számításnak. A szemléltető jelenetben tényleg felismerhető-e a probléma vagy különbség, amely miatt az összefüggés fontos?
Válaszold meg kizárólag a kész anyagból a tanulási célt és a kulcskérdéseket. Ne egészítsd ki fejben hiányzó háttértudással. A modell válasza ellenőrzési jelzés, nem tanulói megértés bizonyítéka.
Képnél a technical-visuals.md alapján előbb a választás alkalmasságát ellenőrizd: a kontextushoz, tanulói művelethez, előismerethez és tartalomhoz ez a forma/nézet/mélység illik-e? A pontosság mellett keresd a célt tévesztő formalizmust és a hiányzó felismerési/áttekintési értéket is; nincs általános eszközrangsor.
A forma hallgatólagos állításai igazoltak vagy láthatóan bizonytalannak jelöltek-e? A promptban megígért, de a képből nem kiolvasható jelentést ne olvasd hozzá. Fallbacknél ugyanaz a tanulói művelet és a szükséges hűség/olvashatóság megmaradt-e a célmegjelenítőn?
A releváns numerikus/formális/geometriai ellenőrzést a kiválasztott módszerhez igazítsd. A rekord a tényleges számolt értéket, összevetést vagy megfigyelést tartalmazza, ne a checklist felmondását. A nem elvégzett ellenőrzést jelöld külön.
Képnél értékeld a formát a tanulói feladat alapján: a látható képből megoldható-e a vállalt feladat? Ne követelj kapcsolati hálót attól, ami más természetű tartalmat tanít. Formafüggően ellenőrizd a részek azonosítását, térbeli helyeket, időrendet, összehasonlítási szempontokat, arányokat, skálákat vagy folyamatlépéseket.
Ellenőrizd a választott nézetet, kivágást, stílust és olvashatóságot: tényleg látható-e a lényeg, következetes-e a jelölés, és nem állít-e kitalált hitelességet vagy torzító hangulatot a kép? A méret, közelség, csoportosítás és hangsúly nyíl nélkül is sugallhat állítást. Ahol félreérthető, nevezd meg a valószínű téves következtetést és vizsgáld meg, hogy a kész kép elkerüli-e. A pontos és szemléltető részek viszonya legyen követhető; ahol együtt szerepelnek, a cím/felirat tegye világossá az infografika tanulási szerepét és a megértést érintő egyszerűsítést. Végső összeállítás után a pontos réteget vesd össze a szerkesztett alappal, ellenőrizd a külön pontos ábra elérhetőségét, az órai jelölést és a jelentést hordozó sorrendet/tájolást.
MINDEN tényleges nyilat külön vizsgálj: mit jelent; honnan indul; hol és merre áll a nyílhegy; mi a célja; mely felirat és feltétel tartozik hozzá. A tartalmi kapcsolatot a forrás igazolja; a megnevező jelölés a helyes tárgyrészhez mutasson. Keresd a hiányzó, többlet-, fordított, tévesen kétirányú és félreérthető nyilakat. A helyes nyíllista önmagában nem bizonyít jó tanulási tervet.
Nézd meg az egész képet és szükség szerint részleteit telefonos megjelenésben és tényleges A4-es méretben. Jelezd, ha nagyítás kell; az OCR önmagában nem képi ellenőrzés. PDF-nél minden oldalt és a teljes sorrendet, a kijelölhető szöveget, szürkeárnyalatos olvashatóságot és a külön válaszrészt is ellenőrizd. Hangnál a szöveghűséget, érthetőséget, kiejtést, hangazonosságot és illesztéseket.
Különítsd el a tartalmi hibát, tanulási alkalmassági problémát, exporthibát, fennmaradó korlátot és puszta ízlésbeli eltérést; az utóbbi önmagában nem indok újragenerálásra. Képi hibánként add meg: pontos hely, megfigyelés, forrás szerinti helyes állapot, szükséges változtatás. A megértést érintő szöveges találatnál a note-formatting.md közös formátumát kövesd: hely és idézet → pontatlanság vagy hiányzó kapcsolat → várható félreértés → legkisebb megalapozott javítás. Az el nem érhető bizonyítékot jelöld ellenőrizetlennek.
Ha megfelel, állj meg. Javításhoz csak konkrét hibából indulj ki, nevezd meg a megőrzendő helyes részeket. Utána az egész érintett képet/oldalt/szegmenst és a kapcsolódó átmeneteket vizsgáld újra.
```

## Speech synthesis

Use the show's stable speaker names (the host Dani and each subject's own guest) and their voices throughout an episode; the speech request is `sn podcast`'s (one call per scene, each turn with its own tone instruction). Check pronunciation aids against evidence before the script goes to the reviewer.

```text
A megadott megszólalást mondd el természetesen, nyugodt, érdeklődő hangon. Alapnyelv: {wiki_nyelv}; a jelölt idegen nyelvű példákat saját nyelvükön mondd. Őrizd meg a szöveget; a szereplő nevét, azonosítóját és technikai jelzéseit ne olvasd fel. Kiejtési támpontok: {ellenorzott_kiejtesek}.
```
