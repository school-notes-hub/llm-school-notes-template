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
        .replaceAll("[[tantargy]]", "Próba")
        .replaceAll("[[lecke]]", "Minta")
        .replaceAll("[[osszefoglalo]]", "Összefoglaló"),
    );
    await page.evaluate(domSource);
    const result = await page.evaluate(measure, {
      actors,
      requested: Object.keys(actors),
    });
    for (const [name, role] of Object.entries(result))
      assert.ok(role.count > 0, name);
    assert.ok(result["mobil-toc"].visible);
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
    assert.equal(result["hogyan-hasznald"].text, "Leírás");
    assert.ok(result["hogyan-hasznald"].box[3] < 200);
    assert.equal(result["kerdes-elso"].text, "Kérdés");
    assert.ok(result["kerdes-elso"].structures.includes("kerdes"));
  } finally {
    await session.close();
  }
});
