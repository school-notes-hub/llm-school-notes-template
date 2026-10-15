import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { openBrowser, domSource, measure } from "../lib/usage-record.mjs";
import { measureCandidates } from "../usage-candidates.mjs";
const browserPath =
  process.env.STUDY_BROWSER ||
  path.join(
    os.homedir(),
    ".cache/ms-playwright/chromium-1208/chrome-linux64/chrome",
  );
const fixture = new URL("./fixtures/usage-selection.html", import.meta.url);
const actors = JSON.parse(
  (
    await fs.readFile(
      new URL("../../video/hasznalat/szereplok.json", import.meta.url),
      "utf8",
    )
  ).replaceAll("[[lecke]]", "Minta"),
);

test("figure role skips banners but keeps the first tall image; candidate measurements agree", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "usage-figures-"));
  const session = await openBrowser(browserPath);
  try {
    const page = await session.browser.newPage({
      viewport: { width: 1280, height: 720 },
    });
    await page.setContent(await fs.readFile(fixture, "utf8"));
    await page.evaluate(domSource);
    await page.evaluate(() =>
      Promise.all([...document.images].map((i) => i.decode())),
    );
    let result = await page.evaluate(measure, { actors, requested: ["abra"] });
    assert.equal(result.abra.count, 1);
    assert.deepEqual(result.abra.box.slice(2), [720, 1080]);
    assert.ok(result.abra.structures.includes("abra"));
    await page
      .locator('img.study-figure:not(.study-banner)')
      .evaluateAll((nodes) => nodes.forEach((n) => n.removeAttribute("class")));
    result = await page.evaluate(measure, { actors, requested: ["abra"] });
    assert.equal(result.abra.count, 0);
    assert.match(result.abra.reason, /nem fejléc/);
  } finally {
    await session.close();
  }
  try {
    await fs.mkdir(path.join(root, "site"));
    await fs.copyFile(fixture, path.join(root, "site/index.html"));
    await fs.writeFile(
      path.join(root, "payload.json"),
      JSON.stringify({
        base: "/fixture/",
        pages: [{ kind: "topic", route: "minta", url: "/fixture/" }],
      }),
    );
    const figures = await measureCandidates({
      build: root,
      out: root,
      browserPath,
    });
    assert.deepEqual(
      figures.minta.map((f) => f.fits),
      [false, true],
    );
    assert.equal(figures.minta[0].available, 632);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test("details role belongs to the selected lesson section, not the glossary", async () => {
  const session = await openBrowser(browserPath);
  try {
    const page = await session.browser.newPage();
    await page.setContent(await fs.readFile(fixture, "utf8"));
    await page.evaluate(domSource);
    const result = await page.evaluate(measure, {
      actors,
      requested: ["reszletesen", "jelmagyarazat-elso"],
    });
    assert.equal(result.reszletesen.text, "➡️ Részletesen: Minta");
    assert.deepEqual(result.reszletesen.hrefs, ["/minta/"]);
    assert.equal(result["jelmagyarazat-elso"].text, "💡 Magyarázat");
  } finally {
    await session.close();
  }
});

test("tall element measures only its visible part for occlusion", async () => {
  const session = await openBrowser(browserPath);
  try {
    const page = await session.browser.newPage({ viewport: { width: 1280, height: 720 } });
    await page.setContent(await fs.readFile(fixture, "utf8"));
    await page.evaluate(domSource);
    await page.evaluate(measure, { actors, requested: ["abra"] });
    await page.locator("[data-usage-abra]").evaluate((node) => {
      scrollBy(0, node.getBoundingClientRect().top - globalThis.__usageLayout().top);
    });
    let result = await page.evaluate(measure, { actors, requested: ["abra"] });
    assert.ok(Math.abs(result.abra.box[1] - 88) < 1);
    assert.equal(result.abra.box[3], 1080);
    assert.ok(result.abra.visible_uncovered.every(Boolean));
    assert.ok(result.abra.uncovered.includes(false));
    await page.evaluate(() => {
      const overlay = document.createElement("div");
      overlay.style.cssText = "position:fixed;inset:200px 0 0;background:white;z-index:99";
      document.body.append(overlay);
    });
    result = await page.evaluate(measure, { actors, requested: ["abra"] });
    assert.ok(result.abra.visible_uncovered.includes(false));
  } finally {
    await session.close();
  }
});

test("video before the figure never supplies its hidden poster as a figure", async () => {
  const session = await openBrowser(browserPath);
  try {
    const page = await session.browser.newPage();
    await page.setContent(await fs.readFile(fixture, "utf8"));
    await page.evaluate(domSource);
    await page.evaluate(() =>
      Promise.all([...document.images].map((i) => i.decode())),
    );
    const result = await page.evaluate(measure, { actors, requested: ["abra"] });
    assert.equal(result.abra.visible, true);
    assert.deepEqual(result.abra.box.slice(2), [720, 1080]);
    assert.ok(result.abra.structures.includes("abra"));
    const figures = await page.evaluate(() => globalThis.__usageFigures());
    assert.deepEqual(
      figures.map((f) => f.box.slice(2)),
      [[720, 1080], [500, 300]],
    );
    await page
      .locator(actors.abra.selector)
      .evaluateAll((nodes) => nodes.forEach((n) => n.remove()));
    const empty = await page.evaluate(measure, { actors, requested: ["abra"] });
    assert.equal(empty.abra.count, 0);
    assert.deepEqual(await page.evaluate(() => globalThis.__usageFigures()), []);
  } finally {
    await session.close();
  }
});
