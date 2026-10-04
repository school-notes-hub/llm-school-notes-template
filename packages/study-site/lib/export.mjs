import fs from 'node:fs/promises';
import path from 'node:path';
import { sha256, readInside, relativeFile, routeFor, normalizeBase, urlFor } from './paths.mjs';
import { renderMarkdown, printSection } from './markdown.mjs';
import { safeSvg, mermaidRenderer } from './assets.mjs';

export async function exportSite({ repo, config, output, browserPath, printEngine, lastUpdated = {} }) {
  const root = await fs.realpath(repo);
  const out = path.resolve(output);
  // Never overwrite source or an existing successful build.
  if (out === root || out.startsWith(root + path.sep) || root.startsWith(out + path.sep)) throw new Error('Output must be outside the input repository');
  try { await fs.lstat(out); throw new Error('Output already exists; choose a new build directory'); } catch (e) { if (e.code !== 'ENOENT') throw e; }
  if (!['private-preview', 'public'].includes(config.mode)) throw new Error('Explicit export mode required');
  const isPublic = config.mode === 'public';
  // The public site shows every wiki page: no per-page review, filtering or hand edits; the
  // renderer leaves out only what points to private files (lib/markdown.mjs).
  if (isPublic && !/^https:\/\/[^/]+$/.test(config.site || '')) throw new Error('Public site origin required');
  const base = normalizeBase(config.base);
  if (!Array.isArray(config.pages) || !config.pages.length) throw new Error('Explicit ordered page allowlist required');
  if (typeof config.title !== 'string' || !config.title.trim()) throw new Error('Site title required');
  const pageMap = new Map();
  const routes = new Set();
  for (const p of config.pages) {
    relativeFile(p.path);
    if (p.path === 'wiki/log.md') throw new Error('Private wiki log cannot be exported');
    const route = routeFor(p.path);
    if (routes.has(route)) throw new Error(`Duplicate route: ${route}`);
    if (!/^[a-f0-9]{64}$/.test(p.sha256)) throw new Error(`Page hash required: ${p.path}`);
    for (const retired of ['omitSections', 'publicEdits']) {
      if (p[retired]?.length) throw new Error(`${retired} is no longer supported (the public site is the wiki 1:1): ${p.path}`);
    }
    if (p.navigationLabel !== undefined && (typeof p.navigationLabel !== 'string' || !p.navigationLabel.trim() || p.navigationLabel.length > 160)) throw new Error('Invalid navigation label');
    pageMap.set(p.path, { ...p, route }); routes.add(route);
  }
  const assets = new Map();
  for (const a of config.assets || []) {
    relativeFile(a.path);
    if (a.path.startsWith('wiki/assets/orai/')) throw new Error('Teacher-material copies cannot be exported; replace with an independently authored or licensed asset');
    if (!a.path.startsWith('wiki/assets/') || !/\.(svg|webp|png|jpg|jpeg|gif|mp4)$/i.test(a.path)) throw new Error(`Unsupported asset: ${a.path}`);
    if (!/^[a-f0-9]{64}$/.test(a.sha256)) throw new Error(`Asset hash required: ${a.path}`);
    if (isPublic && !['authored', 'generated', 'licensed', 'public-domain', 'standard'].includes(a.rights)) throw new Error(`Asset rights class required: ${a.path}`);
    assets.set(a.path, a);
  }
  const payload = { version: 1, mode: config.mode, title: config.title, base, ...(isPublic ? {site:config.site} : {}), pages: [], collections: [] };
  if (config.feedbackRepository !== undefined) {
    if (typeof config.feedbackRepository !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9-]*\/[A-Za-z0-9][A-Za-z0-9._-]*$/.test(config.feedbackRepository)) throw new Error('Invalid public feedback repository');
    payload.feedbackRepository = config.feedbackRepository;
  }
  if (config.license !== undefined) {
    const { id, attribution } = config.license;
    const codes = { 'CC BY 4.0': 'by', 'CC BY-SA 4.0': 'by-sa', 'CC BY-NC-SA 4.0': 'by-nc-sa' };
    if (!Object.hasOwn(codes, id) || typeof attribution !== 'string' || !attribution.trim() || attribution.length > 120) throw new Error('Explicit supported license and attribution required');
    payload.license = { id, attribution, url: 'https://creativecommons.org/licenses/' + codes[id] + '/4.0/' };
  }
  if (config.sourceNote !== undefined) {
    // One short line under every public page and in every PDF: what the notes are based on.
    if (typeof config.sourceNote !== 'string' || !config.sourceNote.trim() || config.sourceNote.length > 300) throw new Error('Invalid source note');
    if (isPublic) payload.sourceNote = config.sourceNote.trim();
  }
  const receipt = { mode: config.mode, configSha256: sha256(JSON.stringify(config)), pages: [], assets: [], privateLinks: [] };
  const cache = new Map();
  const renderer = await mermaidRenderer(browserPath);
  await fs.mkdir(path.join(out, 'public', 'media'), { recursive: true, mode: 0o700 });
  const saveAsset = async (key, bytes, ext, banner = false) => {
    const name = `${banner ? 'banner-' : ''}${sha256(bytes)}${ext}`;
    await fs.writeFile(path.join(out, 'public', 'media', name), bytes);
    receipt.assets.push({ input: key, output: `media/${name}`, outputSha256: sha256(bytes), bytes: bytes.length });
    return base + 'media/' + name;
  };
  try {
    if (config.branding) {
      payload.branding = {};
      for (const theme of ['light', 'dark']) {
        const icon = config.branding[theme];
        if (!icon || !/^publication\/assets\/[^/]+\.png$/.test(icon.path) || !/^[a-f0-9]{64}$/.test(icon.sha256)) throw new Error('Branding needs hash-bound light and dark PNGs in publication/assets');
        const bytes = await readInside(root, icon.path, icon.sha256);
        if (bytes.length > 1024 * 1024 || !bytes.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10]))) throw new Error('Brand icon must be a PNG smaller than 1 MiB');
        payload.branding[theme] = await saveAsset(icon.path, bytes, '.png');
      }
    }
    for (const p of pageMap.values()) {
      const raw = await readInside(root, p.path, p.sha256);
      const resolveUrl = async (url, image) => {
        if (url.startsWith('#')) return url;
        if (/^https?:\/\//.test(url)) {
          if (image) throw new Error(`External image needs a reviewed local asset: ${url}`);
          return url;
        }
        if (/^[a-z]+:|^\/\//i.test(url)) throw new Error(`Unsupported URL: ${url}`);
        const [pathname, fragment] = url.split('#', 2);
        const file = path.posix.normalize(path.posix.join(path.posix.dirname(p.path), decodeURIComponent(pathname)));
        relativeFile(file);
        if (pageMap.has(file) && !image) return urlFor(base, pageMap.get(file).route) + (fragment ? '#' + fragment : '');
        if (assets.has(file)) {
          if (!cache.has(file)) {
            cache.set(file, (async () => {
              const a = assets.get(file);
              const bytes = await readInside(root, file, a.sha256);
              const ext = path.extname(file).toLowerCase();
              return saveAsset(file, ext === '.svg' ? safeSvg(bytes) : bytes, ext, file.includes('/banner/'));
            })());
          }
          return await cache.get(file) + (fragment ? '#' + fragment : '');
        }
        if (!image && isPublic && config.citationOnlyLinks?.includes(file)) { receipt.privateLinks.push(file); return { citationOnly: true }; }
        const privateLink = config.privateLinks?.[file];
        if (!image && privateLink && !isPublic && /^https:\/\/github.com\//.test(privateLink)) {
          receipt.privateLinks.push(file); return { url: privateLink + (fragment ? '#' + fragment : ''), private: true };
        }
        throw new Error(`Unapproved ${image ? 'image' : 'link'} in ${p.path}: ${url}`);
      };
      let rendered;
      try {
        rendered = await renderMarkdown(raw.toString(), {
          resolveUrl,
          publicView: isPublic,
          mermaid: async code => {
            const key = 'mermaid:' + sha256(code);
            if (!cache.has(key)) cache.set(key, (async () => saveAsset(key, await renderer.render(code, 'm' + sha256(code).slice(0, 16)), '.svg'))());
            return cache.get(key);
          }
        });
      } catch (error) {
        // A rendering error is tied to its page, so the caller can send the writer back to it.
        error.page = p.path; throw error;
      }
      const { title, html, headings, audit } = rendered;
      const updated = lastUpdated[p.path];
      if (updated !== undefined && Number.isNaN(Date.parse(updated))) throw new Error(`Invalid last-updated date: ${p.path}`);
      payload.pages.push({ route: p.route, path: p.path, title, navigationLabel: p.navigationLabel, html, headings, group: p.group || '', navigation: p.path === 'wiki/index.md' ? 'home' : /^wiki\/[^/]+\/index\.md$/.test(p.path) ? 'subject' : p.navigation === 'info' ? 'info' : null, url: urlFor(base, p.route), ...(updated ? { lastUpdated: updated } : {}) });
      receipt.pages.push({ input: p.path, sourceSha256: p.sha256, route: p.route, audit });
    }
    const collectionMap = new Map((config.collections || []).map(c => [c.id, c]));
    if (collectionMap.size !== (config.collections || []).length) throw new Error('Duplicate collection ID');
    for (const collection of config.collections || []) {
      if (collection.group) {
        const parent = collectionMap.get(collection.group);
        if (!collection.pdf || !parent?.pdf || parent.group || parent === collection) throw new Error('A PDF group must reference a top-level PDF collection');
      }
      if (!/^[a-z0-9-]+$/.test(collection.id)) throw new Error('Invalid collection ID');
      const chapters = [];
      for (const [index, file] of collection.pages.entries()) {
        const p = pageMap.get(file);
        if (!p) throw new Error(`Collection page not allowed: ${file}`);
        const page = payload.pages.find(page => page.route === p.route);
        chapters.push({ title: page.title, ...await printSection(page.html, `c${index}-`) });
      }
      const inputs = collection.pages.map(file => ({ path:file, sha256:pageMap.get(file).sha256 }));
      const value = { id: collection.id, title: collection.title, group: collection.group || '', chapters, routes: collection.pages.map(file => pageMap.get(file).route), inputs };
      if (collection.pdf === true) {
        if (!printEngine) throw new Error('PDF collection needs a verified print renderer');
        const key = sha256(JSON.stringify({mode:config.mode,printEngine,base,title:value.title,chapters,inputs,license:payload.license,sourceNote:payload.sourceNote}));
        value.pdf = { key, filename:collection.id+'-'+key.slice(0,12)+'.pdf' };
      }
      payload.collections.push(value);
    }
    await fs.writeFile(path.join(out, 'payload.json'), JSON.stringify(payload));
    // Assets are saved as their reads finish; the receipt lists them in a fixed order.
    const byKey = (a, b) => a.input < b.input ? -1 : a.input > b.input ? 1 : a.output < b.output ? -1 : a.output > b.output ? 1 : 0;
    receipt.assets.sort(byKey);
    await fs.writeFile(path.join(out, 'receipt.private.json'), JSON.stringify(receipt, null, 2) + '\n');
    return { payload, receipt };
  } finally { await renderer.close(); }
}
