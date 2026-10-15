import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { capture, domSource } from "../capture-usage.mjs";

const browserPath =
  process.env.STUDY_BROWSER ||
  path.join(
    os.homedir(),
    ".cache/ms-playwright/chromium-1208/chrome-linux64/chrome",
  );
test("usage capture: deterministic pixels, missing role, mobile tooltip and sticky header", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "usage-test-"));
  try {
    await fs.mkdir(path.join(root, "site"));
    await fs.copyFile(
      new URL("./fixtures/usage.html", import.meta.url),
      path.join(root, "site/index.html"),
    );
    await fs.writeFile(
      path.join(root, "payload.json"),
      JSON.stringify({ base: "/fixture/" }),
    );
    const actors = {
      target: { fajta: "css", selector: "#target" },
      label: { fajta: "css", selector: "small" },
      missing: { fajta: "css", selector: ".missing" },
    };
    const script = {
      jelenetek: [
        {
          id: "1",
          nezet: "telefon",
          lepesek: [
            {
              id: "1-01",
              url: "/fixture/",
              gorget: { szereplo: "target", igazit: "felso" },
              allapot: [{ szereplo: "label", muvelet: "koppint" }],
              kiemel: [
                { szereplo: "target" },
                { szereplo: "label" },
                { szereplo: "missing" },
              ],
            },
          ],
        },
      ],
    };
    const a = path.join(root, "one"),
      b = path.join(root, "two");
    const args = {
      build: root,
      script,
      actors,
      browserPath,
      commit: "fixture",
    };
    const first = await capture({ ...args, out: a });
    const second = await capture({ ...args, out: b });
    assert.deepEqual(first, second);
    assert.equal(first[0].roles.missing.count, 0);
    assert.equal(first[0].roles.label.tooltip, true);
    assert.equal(first[0].roles.label.box[2], 220);
    assert.ok(first[0].roles.label.uncovered.every(Boolean));
    assert.ok(first[0].roles.target.box[1] >= 76);
    assert.deepEqual(
      await fs.readFile(path.join(a, "kepek/1-01.png")),
      await fs.readFile(path.join(b, "kepek/1-01.png")),
    );
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test("usage surface contract tracks the current template, including touch restrictions", async () => {
  const root = new URL("../../../", import.meta.url);
  const contract = JSON.parse(
    await fs.readFile(
      new URL("../../video/hasznalat/felulet.json", import.meta.url),
    ),
  );
  for (const row of contract.szovegek)
    assert.ok(
      (await fs.readFile(new URL(row.file, root), "utf8")).includes(row.text),
      row.text,
    );
  assert.equal(contract.forras_sha256, undefined);
  assert.deepEqual(
    contract.interakciok.map((r) => r.lepes),
    ["4-06", "5-05"],
  );
  const template = JSON.parse(await fs.readFile(new URL('../../video/hasznalat/forgatokonyv.json', import.meta.url)));
  for (const rule of [...contract.interakciok, ...contract.valasztok]) {
    const step = template.jelenetek.flatMap(s => s.lepesek).find(s => s.id === rule.lepes);
    assert.ok(step && !step.dom_sorrend, 'external interaction IDs must stay outside reordered groups');
    assert.ok([...step.kiemel, ...(step.allapot || [])].some(c => c.szereplo === rule.szereplo));
  }
});

test("every production role resolves on the neutral surface fixture", async () => {
  const { chromium } = await import("playwright");
  const { measure } = await import("../capture-usage.mjs");
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), "usage-roles-"));
  const cwd = process.cwd(),
    oldTmp = process.env.TMPDIR;
  process.chdir(await fs.realpath(tmp));
  process.env.TMPDIR = "/proc/self/cwd";
  const browser = await chromium.launch({
    executablePath: browserPath,
    env: {
      PATH: process.env.PATH,
      HOME: process.env.HOME,
      TMPDIR: "/proc/self/cwd",
      XDG_CONFIG_HOME: path.join(await fs.realpath("."), "config"),
    },
  });
  try {
    const page = await browser.newPage();
    await page.setContent(
      await fs.readFile(
        new URL("./fixtures/usage-roles.html", import.meta.url),
        "utf8",
      ),
    );
    const text = await fs.readFile(
      new URL("../../video/hasznalat/szereplok.json", import.meta.url),
      "utf8",
    );
    const actors = JSON.parse(
      text
        .replaceAll("[[projekt]]", "A projektről")
        .replaceAll("[[tantargy]]", "Próba")
        .replaceAll("[[lecke]]", "Minta")
        .replaceAll("[[osszefoglalo]]", "Összefoglaló"),
    );
    actors["cimke-nelkuli"].forras_szovegek = ["Órai bekezdés."];
    await page.evaluate(domSource);
    const result = await page.evaluate(measure, {
      actors,
      requested: Object.keys(actors),
    });
    for (const [name, role] of Object.entries(result))
      assert.ok(role.count > 0, name);
    assert.ok(result["mobil-toc"].visible);
    assert.equal(result.morzsa.text, "Kezdőlap");
    assert.equal(result.temavalaszto.text, 'Auto');
    assert.deepEqual(result.temavalaszto.options, ['Sötét', 'Világos', 'Auto']);
    assert.equal(result.temavalaszto.count, 1);
    await page.locator('header starlight-theme-select select').selectOption({label: 'Világos'});
    const changedTheme = await page.evaluate(measure, {actors, requested: ['temavalaszto']});
    assert.equal(changedTheme.temavalaszto.text, 'Világos');
    assert.equal(result["jelmagyarazat-cimkek"].text, "Magyarázat Kiegészítés Javítás A tankönyv alapján");
    assert.ok(result["cimke-nelkuli"].structures.includes("cimke-nelkuli"));
  } finally {
    await browser.close();
    process.chdir(cwd);
    if (oldTmp === undefined) delete process.env.TMPDIR;
    else process.env.TMPDIR = oldTmp;
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

test("usage recording preserves action frames, visible text and disposable browser profiles", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "usage-actions-"));
  const oldTmp = process.env.TMPDIR;
  try {
    process.env.TMPDIR = root;
    await fs.mkdir(path.join(root, "site"));
    await fs.copyFile(
      new URL("./fixtures/usage-actions.html", import.meta.url),
      path.join(root, "site/index.html"),
    );
    await fs.writeFile(
      path.join(root, "payload.json"),
      JSON.stringify({ base: "/fixture/" }),
    );
    const actors = {
      menu: { fajta: "css", selector: "button" },
      input: { fajta: "css", selector: "input" },
      sidebar: { fajta: "css", selector: "nav" },
    };
    const script = {
      jelenetek: [
        {
          id: "1",
          nezet: "telefon",
          lepesek: [
            {
              id: "1-01",
              url: "/fixture/",
              allapot: [
                { szereplo: "menu", muvelet: "nyit" },
                { szereplo: "menu", muvelet: "zar" },
                { szereplo: "input", muvelet: "gepel", text: "minta" },
              ],
              kiemel: [{ szereplo: "sidebar" }],
            },
          ],
        },
      ],
    };
    const result = await capture({
      build: root,
      out: path.join(root, "out"),
      script,
      actors,
      browserPath,
      commit: "fixture",
    });
    assert.equal(result[0].roles.sidebar.text, "Menü");
    assert.deepEqual(result[0].focus_visible, []);
    const typed = result[0].motion.find(m => m.image.includes('-gepel-kesz'));
    assert.notDeepEqual(await fs.readFile(path.join(root, 'out', typed.image)),
      await fs.readFile(path.join(root, 'out', result[0].image)),
      'typing frames keep focus, but the final highlight frame loses it');
    const pixels = await Promise.all(
      result[0].motion
        .slice(0, 4)
        .map((m) => fs.readFile(path.join(root, "out", m.image))),
    );
    assert.notDeepEqual(
      pixels[1],
      pixels[3],
      "native popover open/closed states need different cache keys",
    );
    assert.ok(result[0].motion.some((frame) => frame.ring));
    assert.ok(result[0].frames.some((file) => file.includes("-gepel-")));
    assert.ok(
      result[0].motion.filter((frame) => frame.seconds === 0.1).length === 5,
    );
    assert.ok(
      !(await fs.readdir(root)).some((name) =>
        name.startsWith("usage-browser-"),
      ),
    );
    assert.ok(
      !(await fs.readdir(path.join(root, "out"))).includes("browser-config"),
    );
  } finally {
    if (oldTmp === undefined) delete process.env.TMPDIR;
    else process.env.TMPDIR = oldTmp;
    await fs.rm(root, { recursive: true, force: true });
  }
});

test("guide role excludes its preceding player and chapters; quiz ignores earlier details", async () => {
  const { openBrowser } = await import("../lib/usage-record.mjs");
  const session = await openBrowser(browserPath);
  try {
    const page = await session.browser.newPage();
    await page.setContent(`<main class="study-content"><h2>Hogyan használd</h2>
   <p><video style="height:900px"></video></p><p>Fejezetek</p><ul><li>Leírás</li></ul>
   <details><summary>Másik lista</summary>Másik</details><h2>Kérdezd ki magad</h2>
   <details><summary>Kérdés</summary>Válasz</details></main>`);
    await page.evaluate(domSource);
    const actors = JSON.parse(
      await fs.readFile(
        new URL("../../video/hasznalat/szereplok.json", import.meta.url),
      ),
    );
    const { measure } = await import("../capture-usage.mjs");
    const result = await page.evaluate(measure, {
      actors,
      requested: ["hogyan-hasznald", "kerdes-elso"],
    });
    assert.equal(result["hogyan-hasznald"].text, "Hogyan használd");
    assert.ok(result["hogyan-hasznald"].box[3] < 200);
    assert.equal(result["kerdes-elso"].text, "Kérdés");
    assert.ok(result["kerdes-elso"].structures.includes("kerdes"));
  } finally {
    await session.close();
  }
});

test("usage context keeps inline and separate labels with their prose, and escape clears focus", async () => {
  const { openBrowser } = await import("../lib/usage-record.mjs");
  const { recordAction, scroll } = await import("../lib/usage-actions.mjs");
  const session = await openBrowser(browserPath);
  try {
    const page = await session.browser.newPage({ viewport: { width: 1280, height: 720 } });
    await page.setContent(`<style>
      header {position:fixed;top:0;height:72px;background:white;width:100%}
      main {margin-left:300px;width:660px;padding-top:800px}
      p {font:20px/1.6 sans-serif} small {font:14px sans-serif}
      button:focus-visible {outline:3px solid orange}
    </style><header>Header</header><button>Search</button><main class="study-content">
      <p id="plain">A plain teaching paragraph.</p>
      <p id="inline">A labelled paragraph with its own explanation.<br><small class="study-label">💡 explanation</small></p>
      <p id="prose">Another teaching paragraph.</p><p><small class="study-label" id="separate">📗 textbook</small></p>
      <p style="height:1200px">Next paragraph</p></main>`);
    await page.evaluate(domSource);
    const actors = {
      inline: { fajta: 'css', selector: '#inline small' },
      separate: { fajta: 'css', selector: '#separate' },
      plain: { fajta: 'css', selector: '.study-content > p', cimke_nelkul: true, n: 0 },
    };
    const get = () => page.evaluate((actors) => globalThis.__usageMeasure({actors, requested: Object.keys(actors)}), actors);
    let measured = await get();
    assert.ok(measured.inline.context[1] < measured.inline.box[1]);
    assert.ok(measured.separate.context[1] < measured.separate.box[1]);
    assert.equal(measured.plain.text, 'A plain teaching paragraph.');
    const ctx = {page, motion: [], shot: async () => 'fixture.png'};
    await scroll(ctx, {nezet:'asztal', kamera:'elem', dom_sorrend:true,
      gorget:{szereplo:'plain', igazit:'felso'}}, measured);
    measured = await get();
    assert.ok(measured.plain.box[1] > 300, 'ordered plain text shares label framing');
    await scroll(ctx, {nezet:'asztal', kamera:'elem', gorget:{szereplo:'inline', igazit:'felso'}}, measured);
    measured = await get();
    assert.ok(measured.inline.context[1] >= 88);
    assert.ok(measured.inline.box[1] > 300);
    assert.ok((await page.evaluate(() => globalThis.__usageText())).some(w => w.text === 'labelled'));
    await page.locator('button').focus();
    assert.equal((await page.evaluate(() => globalThis.__usageFocus())).length, 1);
    await recordAction(ctx, {szereplo:'unused', muvelet:'esc'});
    assert.deepEqual(await page.evaluate(() => globalThis.__usageFocus()), []);
    await page.locator('#inline').evaluate((n) => {
      n.firstChild.textContent = 'A long explanation. '.repeat(300);
    });
    await scroll(ctx, {nezet:'asztal', kamera:'elem', gorget:{szereplo:'inline', igazit:'felso'}}, await get());
    measured = await get();
    assert.ok(measured.inline.context[1] < 88);
    assert.ok(measured.inline.box[1] > 300 && measured.inline.box[1] + measured.inline.box[3] < 720);
  } finally {
    await session.close();
  }
});

test('review roles bind the same date, classroom prose and exact text ranges', async () => {
  const { openBrowser } = await import('../lib/usage-record.mjs');
  const session = await openBrowser(browserPath);
  try {
    const page = await session.browser.newPage();
    await page.setContent(`<main class="study-content">
      <p><small class="study-label">🗓️ Óra: <a href="/subject/#ora-first">szept. 29.</a> · Tankönyv</small></p>
      <p>Unreferenced introduction.</p><p>Book material.</p><p>Classroom material.</p>
      <p>Explanation.<br><small class="study-label">💡 🤖 gépi magyarázat</small></p>
      <p>More explanation.<br><small class="study-label">💡 🤖 gépi magyarázat</small></p>
      <p>Correction.<br><small class="study-label">⚠️ 🤖 gépi javítás</small></p>
      <p>Book.<br><small class="study-label">📗 A tankönyv alapján</small></p>
      <p>Extra.<br><small class="study-label">➕ 🤖 gépi kiegészítés</small></p>
      <small class="study-label">🗓️ Óra: <a href="/subject/#ora-later"><span class="study-when">~ősz</span></a></small>
      <ul><li><a id="ora-first"></a>Lesson title · date<br>→ <a href="/one/">First</a> · <a href="/two/">Second</a></li></ul>
    </main>`);
    const actors = JSON.parse(await fs.readFile(new URL('../../video/hasznalat/szereplok.json', import.meta.url), 'utf8'));
    actors['cimke-nelkuli'].forras_szovegek = ['Classroom material.', 'Explanation.💡 🤖 gépi magyarázat'];
    await page.evaluate(domSource);
    const requested = ['ora-sor', 'datum-link', 'cimke-elso', 'cimke-kieg', 'robot-jel', 'ora-elso', 'ora-nyil', 'cimke-nelkuli'];
    const m = await page.evaluate(({actors, requested}) => globalThis.__usageMeasure({actors, requested}), {actors, requested});
    assert.equal(m['datum-link'].text, 'szept. 29.');
    assert.deepEqual(m['datum-link'].context, m['ora-sor'].context);
    assert.ok(m['datum-link'].structures.includes('datum-link'));
    assert.equal(m['cimke-elso'].text, '💡 🤖 gépi magyarázat');
    assert.equal(m['cimke-nelkuli'].text, 'Classroom material.');
    assert.equal(m['robot-jel'].text, '🤖');
    assert.equal(m['robot-jel'].dom_order, m['cimke-elso'].dom_order);
    assert.ok(m['robot-jel'].box[2] < m['cimke-kieg'].box[2] / 3);
    assert.equal(m['ora-nyil'].text, '→ First · Second');
    assert.ok(m['ora-nyil'].box[1] > m['ora-elso'].box[1]);
    actors['cimke-nelkuli'].forras_szovegek = [];
    const missing = await page.evaluate(actors => globalThis.__usageMeasure({actors, requested:['cimke-nelkuli']}), actors);
    assert.equal(missing['cimke-nelkuli'].count, 0);
  } finally { await session.close(); }
});

test('tour targets follow DOM order, skip used labels and union all current lessons', async () => {
  const { openBrowser } = await import('../lib/usage-record.mjs');
  const session = await openBrowser(browserPath);
  try {
    const page = await session.browser.newPage();
    const actors = JSON.parse(await fs.readFile(new URL('../../video/hasznalat/szereplok.json', import.meta.url), 'utf8'));
    await page.setContent(`<nav id="starlight__sidebar" style="height:700px">
      <a>Home</a><a>Subject</a><a>About</a></nav><main class="study-content">
      <small class="study-label">🗓️ Óra</small>
      <small class="study-label" id="first">📗 A tankönyv alapján</small>
      <small class="study-label" id="robot">⚠️ 🤖 gépi javítás</small>
      <small class="study-label">➕ 🤖 gépi kiegészítés</small>
      <p><small class="study-label">🤖 Gépi hang</small></p>
      <p><small class="study-label">💡 🤖 gépi magyarázat</small></p>
      <p><small class="study-label">⚠️ 🤖 gépi javítás</small></p>
      <p><small class="study-label">📗 A tankönyv alapján</small></p>
      <p><small class="study-label">➕ 🤖 gépi kiegészítés</small></p>
      <ul><li>Earlier</li><li id="current1">One ◀ itt tartunk</li><li id="current2">Two ◀ itt tartunk</li></ul>
    </main>`);
    await page.evaluate(domSource);
    const { orderTargets } = await import('../lib/usage-order.mjs');
    const ordered = ['cimke-elso', 'cimke-javitas', 'cimke-kieg', 'cimke-magyarazat', 'cimke-tankonyv'];
    await orderTargets(page, actors, ordered);
    const m = await page.evaluate(({actors, requested}) => globalThis.__usageMeasure({actors, requested}),
      {actors, requested: [...ordered, 'robot-jel', 'oldalsav', 'itt-tartunk']});
    assert.equal(m['cimke-elso'].text, '📗 A tankönyv alapján');
    assert.ok(ordered.slice(1).every((role, i) => m[role].dom_order > m[ordered[i]].dom_order));
    assert.ok(m.oldalsav.box[3] < 100);
    assert.equal(m['itt-tartunk'].count, 1);
    assert.equal(m['itt-tartunk'].text, 'One ◀ itt tartunk Two ◀ itt tartunk');
    const rects = await page.locator('#current1, #current2').evaluateAll(nodes => nodes.map(n => {
      const r = n.getBoundingClientRect(); return [r.y, r.bottom];
    }));
    assert.equal(m['itt-tartunk'].box[1], rects[0][0]);
    assert.equal(m['itt-tartunk'].box[1] + m['itt-tartunk'].box[3], rects[1][1]);
    await page.locator('[data-usage-cimke-magyarazat]').evaluate(n => n.remove());
    const missing = await page.evaluate(actors => globalThis.__usageMeasure({actors, requested:['cimke-tankonyv']}), actors);
    assert.equal(missing['cimke-tankonyv'].count, 0); // Never fall back upwards.
  } finally { await session.close(); }
});

test('tour planning follows different label layouts and persists positional IDs', async () => {
  const { openBrowser } = await import('../lib/usage-record.mjs');
  const { orderTour } = await import('../lib/usage-order.mjs');
  const { serveSite } = await import('../lib/server.mjs');
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'usage-order-'));
  const session = await openBrowser(browserPath);
  const {server, origin} = await serveSite(root, '/');
  const labels = {book:'📗 A tankönyv alapján', explanation:'💡 🤖 gépi magyarázat',
    correction:'⚠️ 🤖 gépi javítás', addition:'➕ 🤖 gépi kiegészítés'};
  try {
    for (const layout of [
      ['book', 'correction', 'addition', 'explanation', 'book'],
      ['explanation', 'explanation', 'correction', 'book', 'addition'],
    ]) {
      await fs.writeFile(path.join(root, 'index.html'), '<main class="study-content">' +
        layout.map(label => `<p>Prose<small class="study-label">${labels[label]}</small></p>`).join('') + '</main>');
      const actors = JSON.parse(await fs.readFile(new URL('../../video/hasznalat/szereplok.json', import.meta.url), 'utf8'));
      const requested = ['cimke-elso', 'robot-jel', 'cimke-magyarazat', 'cimke-javitas', 'cimke-tankonyv', 'cimke-kieg'];
      const script = {jelenetek:[{id:'1', nezet:'asztal', lepesek:requested.map((role, i) => ({
        id:`1-0${i+1}`, url:'/', dom_sorrend:true, kiemel:[{szereplo:role}], gorget:{szereplo:role}, text:role,
      }))}]};
      await orderTour(session.browser, origin, script, actors);
      const steps = script.jelenetek[0].lepesek;
      assert.deepEqual(steps.map(s => s.id), requested.map((_, i) => `1-0${i+1}`));
      const roleNames = {book:'cimke-tankonyv', explanation:'cimke-magyarazat', correction:'cimke-javitas', addition:'cimke-kieg'};
      assert.deepEqual(steps.filter(s => s.text !== 'robot-jel').map(s => s.text),
        ['cimke-elso', ...layout.slice(1).map(label => roleNames[label])]);
      assert.ok(steps.every(s => s.text === s.kiemel[0].szereplo && s.gorget.szereplo === s.text));
      const once = JSON.stringify({script,actors});
      await orderTour(session.browser, origin, script, actors);
      assert.equal(JSON.stringify({script,actors}), once);
    }
  } finally {
    await session.close();
    await new Promise(resolve => server.close(resolve));
    await fs.rm(root, {recursive:true, force:true});
  }
});
