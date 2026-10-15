// Measured figure eligibility for every lesson, in payload order.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { serveSite } from "./lib/server.mjs";
import { sourceParagraphs } from "./lib/usage-provenance.mjs";
import { digest, read, save, treeHashes } from "./lib/usage-shots.mjs";
import {
  openBrowser,
  newState,
  openPage,
  domSource,
} from "./lib/usage-record.mjs";

async function inspect(browser, origin, payload, sources) {
  const state = await newState(browser, "asztal", origin);
  const result = {}, classroom = {};
  for (const page of payload.pages.filter((p) => p.kind === "topic")) {
    await openPage(state, page.url, origin);
    result[page.route] = await state.page.evaluate(() =>
      globalThis.__usageFigures(),
    );
    classroom[page.route] = await state.page.evaluate(html => {
      const texts = html.flatMap(fragment => {
        const template = document.createElement('template');
        template.innerHTML = fragment;
        return [...template.content.children].filter(n => n.tagName === 'P').map(n => n.textContent.replace(/\s+/g, ' ').trim());
      });
      const actors = { source: {fajta:'css', selector:'.study-content > p', cimke_nelkul:true,
        ora_forras:true, forras_szovegek:texts} };
      globalThis.__usageMeasure({actors, requested:['source']});
      return [...document.querySelectorAll('[data-usage-source]')].map(n => n.innerText.replace(/\s+/g, ' ').trim());
    }, sources[page.route] || []);
  }
  return {figures: result, classroom};
}

export async function measureCandidates({ build, out, browserPath, repo }) {
  const payload = await read(path.join(build, "payload.json"));
  const sources = await sourceParagraphs(repo, build, payload);
  const { server, origin } = await serveSite(
    path.join(build, "site"),
    payload.base,
  );
  let session;
  try {
    session = await openBrowser(browserPath);
    const key = digest(JSON.stringify([await measurementKey(build, session.browser.version()), sources]));
    const file = path.join(out, "abra-meres.json");
    try {
      const cached = await read(file);
      if (cached.key === key) {
        await save(path.join(out, 'ora-forrasok.json'), cached.classroom);
        return cached.figures;
      }
    } catch {
      /* First measurement. */
    }
    const measured = await inspect(session.browser, origin, payload, sources);
    await save(file, { key, ...measured });
    await save(path.join(out, 'ora-forrasok.json'), measured.classroom);
    return measured.figures;
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
  const files = ["./usage-candidates.mjs", "./lib/usage-record.mjs", "./lib/usage-provenance.mjs", "./lib/markdown.mjs"];
  const code = await Promise.all(
    files.map((f) => fs.readFile(new URL(f, import.meta.url), "utf8")),
  );
  return digest(
    JSON.stringify([await treeHashes(build), version, domSource, code]),
  );
}
