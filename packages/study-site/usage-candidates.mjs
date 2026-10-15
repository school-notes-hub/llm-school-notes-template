// Measured figure eligibility for every lesson, in payload order.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { serveSite } from "./lib/server.mjs";
import { digest, read, save, treeHashes } from "./lib/usage-shots.mjs";
import {
  openBrowser,
  newState,
  openPage,
  domSource,
} from "./lib/usage-record.mjs";

async function inspect(browser, origin, payload) {
  const state = await newState(browser, "asztal", origin);
  const result = {};
  for (const page of payload.pages.filter((p) => p.kind === "topic")) {
    await openPage(state, page.url, origin);
    result[page.route] = await state.page.evaluate(() =>
      globalThis.__usageFigures(),
    );
  }
  return result;
}

export async function measureCandidates({ build, out, browserPath }) {
  const payload = await read(path.join(build, "payload.json"));
  const { server, origin } = await serveSite(
    path.join(build, "site"),
    payload.base,
  );
  let session;
  try {
    session = await openBrowser(browserPath);
    const key = await measurementKey(build, session.browser.version());
    const file = path.join(out, "abra-meres.json");
    try {
      const cached = await read(file);
      if (cached.key === key) return cached.figures;
    } catch {
      /* First measurement. */
    }
    const figures = await inspect(session.browser, origin, payload);
    await save(file, { key, figures });
    return figures;
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
    await measureCandidates(await read(process.argv[2]));
  } catch (error) {
    console.error(error);
    process.exitCode = 3;
  }
}

async function measurementKey(build, version) {
  const files = ["./usage-candidates.mjs", "./lib/usage-record.mjs"];
  const code = await Promise.all(
    files.map((f) => fs.readFile(new URL(f, import.meta.url), "utf8")),
  );
  return digest(
    JSON.stringify([await treeHashes(build), version, domSource, code]),
  );
}
