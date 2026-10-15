import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { chromium } from "playwright";
import {
  recordAction,
  scroll,
  anchoredAction,
  locator,
} from "./usage-actions.mjs";
import { screenshot, digest, read } from "./usage-shots.mjs";

const [roles, measureSource] = await Promise.all([
  read(new URL("../../video/hasznalat/szereplok.json", import.meta.url)),
  fs.readFile(new URL("./usage-measure.js", import.meta.url), "utf8"),
]);
export const domSource = `{
  const figureSelector = ${JSON.stringify(roles.abra.selector)};
  ${measureSource}
}`;
export const measure = (args) => globalThis.__usageMeasure(args);

export async function openBrowser(browserPath) {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), "usage-browser-"));
  const cwd = process.cwd(),
    oldTmp = process.env.TMPDIR;
  process.chdir(temporary);
  process.env.TMPDIR = "/proc/self/cwd"; // Short socket names; cwd is disposable, never the hand-over.
  const restore = async () => {
    process.chdir(cwd);
    if (oldTmp === undefined) delete process.env.TMPDIR;
    else process.env.TMPDIR = oldTmp;
    await fs.rm(temporary, { recursive: true, force: true });
  };
  const env = Object.fromEntries(
    ["PATH", "HOME", "LANG", "FONTCONFIG_FILE", "XDG_CACHE_HOME", "TMPDIR"]
      .filter((k) => process.env[k])
      .map((k) => [k, process.env[k]]),
  );
  env.XDG_CONFIG_HOME = path.join(temporary, "config");
  try {
    const browser = await chromium.launch({
      executablePath: browserPath,
      headless: true,
      env,
    });
    return {
      browser,
      close: async () => {
        try {
          await browser.close();
        } finally {
          await restore();
        }
      },
    };
  } catch (error) {
    await restore();
    throw error;
  }
}

export async function newState(browser, view, origin) {
  const mobile = view === "telefon";
  const context = await browser.newContext({
    viewport: mobile
      ? { width: 390, height: 844 }
      : { width: 1280, height: 720 },
    deviceScaleFactor: 3,
    isMobile: mobile,
    hasTouch: mobile,
    colorScheme: "light",
    reducedMotion: "reduce",
    locale: "hu-HU",
    timezoneId: "Europe/Budapest",
  });
  await context.addInitScript({ content: domSource });
  const page = await context.newPage(),
    errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error")
      errors.push(message.text().replaceAll(origin, ""));
  });
  return { page, errors, url: null, status: 0 };
}

export async function openPage(state, url, origin) {
  if (state.url !== url) {
    state.errors.length = 0;
    const response = await state.page.goto(origin + url, {
      waitUntil: "networkidle",
    });
    state.status = response.status();
    state.url = url;
  }
  await state.page.evaluate(async () => {
    document.documentElement.dataset.theme = "light";
    await document.fonts.ready;
    await Promise.all(
      [...document.images].map(async (image) => {
        image.loading = "eager";
        try {
          await image.decode();
        } catch {
          /* Measured as a broken image. */
        }
      }),
    );
  });
}

async function contentState(page, origin) {
  const content = await page.evaluate(() => ({
    theme: document.documentElement.dataset.theme,
    content: !!document.querySelector(".study-content")?.innerText.trim(),
    layout: globalThis.__usageLayout(),
    text_rects: globalThis.__usageText(),
    focus_visible: globalThis.__usageFocus(),
    broken: [...document.images]
      .filter((i) => !i.complete || !i.naturalWidth)
      .map((i) => i.getAttribute("src")),
    images: [...document.images]
      .filter((i) => {
        const r = i.getBoundingClientRect();
        return r.bottom > 0 && r.top < innerHeight;
      })
      .map((i) => i.getAttribute("src")),
  }));
  content.assets = [];
  for (const src of content.images) {
    const url = new URL(src, page.url());
    if (url.origin !== origin) throw Error("external visible image: " + src);
    const response = await page.request.get(url.href);
    content.assets.push({
      path: url.pathname,
      sha256: digest(await response.body()),
    });
  }
  delete content.images;
  return content;
}

export async function recordStep(recorder, state, scene, step) {
  const { page } = state;
  const requested = requestedRoles(step);
  await openPage(state, step.url, recorder.origin);
  const get = () =>
    page.evaluate(measure, { actors: recorder.actors, requested });
  const ctx = {
    page,
    motion: [],
    shot: (suffix) => screenshot(recorder, page, step, suffix),
  };
  let boxes = await get();
  for (const action of (step.allapot || []).filter(
    (a) => !a.horgony && a.muvelet !== "koppint",
  )) {
    await recordAction(ctx, action);
    boxes = await get();
  }
  await scroll(ctx, step, boxes);
  const before = await anchoredAction(ctx, step);
  boxes = await get();
  const content = await contentState(page, recorder.origin);
  return {
    id: step.id,
    url: step.url,
    actualUrl: new URL(page.url()).pathname,
    nezet: scene.nezet,
    viewport: page.viewportSize(),
    roles: boxes,
    image: await ctx.shot(""),
    before_image: before.image,
    anchor_cursor: before.cursor,
    frames: ctx.motion.map((m) => m.image),
    motion: ctx.motion,
    status: state.status,
    errors: [...state.errors],
    ...content,
  };
}

export async function navigateAfter(state, step) {
  if (!step.kurzor?.kattint) return;
  const loc = locator(state.page, step.kurzor.szereplo);
  if (await loc.count()) {
    await loc.click();
    await state.page.waitForLoadState("networkidle");
    state.url = new URL(state.page.url()).pathname;
  }
}

function requestedRoles(step) {
  return [
    ...new Set(
      [
        step.gorget?.szereplo,
        step.kurzor?.szereplo,
        ...(step.kiemel || []).map((c) => c.szereplo),
        ...(step.allapot || []).map((a) => a.szereplo),
      ].filter(Boolean),
    ),
  ];
}
