// Browser capture is independent of speech. All measurements use CSS pixels.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { serveSite } from "./lib/server.mjs";
import { orderTour } from "./lib/usage-order.mjs";
import {
  digest,
  read,
  save,
  treeHashes,
  cachedCapture,
} from "./lib/usage-shots.mjs";
import {
  openBrowser,
  newState,
  recordStep,
  navigateAfter,
} from "./lib/usage-record.mjs";
export { measure, domSource } from "./lib/usage-record.mjs";

async function recorderCode() {
  const names = [
    "./capture-usage.mjs",
    "./lib/usage-shots.mjs",
    "./lib/usage-record.mjs",
    "./lib/usage-actions.mjs",
    "./lib/usage-measure.js",
    "./lib/usage-order.mjs",
    "../video/hasznalat/szereplok.json",
  ];
  return Promise.all(
    names.map(async (name) =>
      digest(await fs.readFile(new URL(name, import.meta.url))),
    ),
  );
}

async function replay(recorder, browser, script) {
  const states = new Map(),
    measurements = [];
  for (const scene of script.jelenetek) {
    if (!states.has(scene.nezet))
      states.set(
        scene.nezet,
        await newState(browser, scene.nezet, recorder.origin),
      );
    const state = states.get(scene.nezet);
    for (const step of scene.lepesek) {
      measurements.push(await recordStep(recorder, state, scene, step));
      await save(
        path.join(recorder.out, "dobozok-reszleges.json"),
        measurements,
      );
      await save(path.join(recorder.out, "kep-cache.json"), recorder.cache);
      await navigateAfter(state, step);
    }
  }
  return measurements;
}

async function captureWithBrowser(args, browser, origin) {
  const { build, out, script, actors, commit } = args;
  await orderTour(browser, origin, script, actors);
  await save(path.join(out, "forgatokonyv-kitoltott.json"), script);
  await save(path.join(out, "szereplok.json"), actors);
  await save(path.join(out, "felvetel.json"), args);
  const tree = await treeHashes(build),
    version = browser.version();
  const input = digest(
    JSON.stringify({
      tree,
      script,
      actors,
      version,
      code: await recorderCode(),
    }),
  );
  const cached = await cachedCapture(out, input);
  if (cached) return cached;
  const recorder = {
    out,
    origin,
    tree,
    version,
    actors,
    images: {},
    cache: {},
  };
  try {
    recorder.cache = await read(path.join(out, "kep-cache.json"));
  } catch {
    /* First run. */
  }
  const measurements = await replay(recorder, browser, script);
  await save(path.join(out, "dobozok.json"), measurements);
  await captureReceipt(out, version, commit, recorder.images, input);
  return measurements;
}

export async function capture(args) {
  await fs.mkdir(path.join(args.out, "kepek"), { recursive: true });
  args = {
    ...args,
    build: await fs.realpath(args.build),
    out: await fs.realpath(args.out),
  };
  const payload = await read(path.join(args.build, "payload.json"));
  const { server, origin } = await serveSite(
    path.join(args.build, "site"),
    payload.base,
  );
  let session;
  try {
    session = await openBrowser(args.browserPath);
    return await captureWithBrowser(args, session.browser, origin);
  } finally {
    try {
      if (session) await session.close();
    } finally {
      await new Promise((resolve) => server.close(resolve));
    }
  }
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  try {
    await capture(await read(process.argv[2]));
  } catch (error) {
    console.error(error);
    process.exitCode = 3;
  }
}

async function captureReceipt(out, version, commit, images, input) {
  await save(path.join(out, "felvetel-nyugta.json"), {
    chromium: version,
    commit,
    images,
    viewports: { asztal: [1280, 720, 3], telefon: [390, 844, 3] },
    input,
    fonts: await fs.readFile(
      new URL("./src/fonts/source-sans-3/provenance.json", import.meta.url),
      "utf8",
    ),
  });
}
