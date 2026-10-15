# School Notes video chain

The machine steps of a Manim teaching video, run from the tagged release worktree like `sn`
(`~/.local/share/school-notes/release/current/packages/video/`). The writer agent writes the
narration and the scene code; this chain does the rest without an LLM: speech (TTS per step),
word timing (Whisper per step, number reader), frame plan, render, gate (K1-K13), contact sheets,
final render with opening and closing card, receipt and measurement.

| Path | What it is |
|---|---|
| `video.sh` | the one command: `video.sh <learner> <subject> <page>-<n> [--atadas [--valtozott] \| --vegleges \| --meres \| --kivagat <step>/<obj> \| --takarit]`; runs `video.py` in this tree's `packages/school-notes2` uv environment |
| `manim.sh` | Manim from the separate `manim-env` with its own TinyTeX; puts this folder on `PYTHONPATH`, so scene code imports `from videotar import ...` |
| `video.py`, `lanc/` | the chain: speech, words, render, opening/closing card, measurement |
| `hang.py`, `idoterv.py` | speech helpers and the frame plan |
| `kapu.py`, `tabla.py`, `lapok.py`, `szamnev.py` | the gate, its time table, contact sheets and the number reader ([interface](kapu-interfesz.md)) |
| `videotar/` | the element library for scene code ([API](videotar/API.md)), pinned to Manim 0.22 |

Exit codes: 0 green, 1 red, 2 stopped (input, version, lock, budget, time limit), 3 render crash.
Working folders stay in the learner repository (`.school-notes/out/video/<subject>/<page>-<n>/`),
the Manim cache under `~/.cache/school-notes/video/`, finished videos under `~/jegyzet/video-kesz/`.
Paid calls go through the podcast ledger, cache and budget of `school_notes2`.

## Tests (no paid call)

```sh
cd packages/video
uv run --project ../school-notes2 python -m pytest -q lanc/teszt   # chain, number reader, gate rules; renders the test scenes through video.sh with VIDEO_CSONK=1
videotar-teszt/render.sh                                             # renders the two test scenes (synthetic sound), then the videotar tests in manim-env
kapu-teszt/kapu-teszt.sh [--render]                                  # gate acceptance on the test scenes
```

`VIDEO_CSONK=1` with `--mappa <folder>` replaces TTS and Whisper with the synthetic stub of
`videotar-teszt/szintetikus.py`. Every fixture is synthetic: no learner, page, narration or source
text (the neutrality test of `packages/school-notes2` scans this whole folder).

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
