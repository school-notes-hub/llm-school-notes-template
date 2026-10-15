import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";

export const digest = (bytes) =>
  crypto.createHash("sha256").update(bytes).digest("hex");
export const save = (file, value) =>
  fs.writeFile(file, JSON.stringify(value, null, 2) + "\n");
export const read = async (file) => JSON.parse(await fs.readFile(file, "utf8"));

export async function treeHashes(build, dir = path.join(build, "site")) {
  const result = [];
  for (const entry of (await fs.readdir(dir, { withFileTypes: true })).sort(
    (a, b) => a.name.localeCompare(b.name, "en"),
  )) {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) result.push(...(await treeHashes(build, file)));
    else if (entry.isFile())
      result.push([
        path.relative(build, file),
        digest(await fs.readFile(file)),
      ]);
  }
  return result;
}

export async function cachedCapture(out, input) {
  try {
    const receipt = await read(path.join(out, "felvetel-nyugta.json"));
    if (receipt.input !== input) return null;
    for (const [file, hash] of Object.entries(receipt.images)) {
      if (digest(await fs.readFile(path.join(out, file))) !== hash) return null;
    }
    return await read(path.join(out, "dobozok.json"));
  } catch {
    return null;
  }
}

function pageState() {
  const strip = (html) =>
    html?.replace(/ data-usage-[^= >]+(?:="[^"]*")?/g, "");
  return JSON.stringify({
    html: strip(document.documentElement.outerHTML),
    scroll: [scrollX, scrollY],
    focus: strip(document.activeElement?.outerHTML),
    fields: [...document.querySelectorAll("input")].map((n) => n.value),
    popovers: [...document.querySelectorAll(":popover-open")].map((n) => n.id),
    width: innerWidth,
    height: innerHeight,
  });
}

export async function screenshot(recorder, page, step, suffix) {
  const file = `kepek/${step.id}${suffix}.png`;
  const key = digest(
    JSON.stringify({
      state: await page.evaluate(pageState),
      version: recorder.version,
      tree: recorder.tree,
    }),
  );
  let bytes;
  const cached = recorder.cache[key];
  if (cached) {
    try {
      const data = await fs.readFile(path.join(recorder.out, cached.path));
      if (digest(data) === cached.sha256) bytes = data;
    } catch {
      /* Removed or interrupted cache entry. */
    }
  }
  bytes ||= await page.screenshot({ animations: "disabled", caret: "hide" });
  const hash = digest(bytes);
  recorder.images[file] = hash;
  recorder.cache[key] = { path: file, sha256: hash };
  await fs.writeFile(path.join(recorder.out, file), bytes);
  return file;
}
