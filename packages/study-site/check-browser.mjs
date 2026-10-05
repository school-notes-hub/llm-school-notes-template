#!/usr/bin/env node
// Integration checks against a built site; no source modification or installation.
import fs from 'node:fs/promises';
import { chromium } from 'playwright';
import { linkProblems } from './lib/browser-links.mjs';
const [address, payloadPath, executablePath, reportPath, searchQuery, onlyPath] = process.argv.slice(2);
if (!reportPath) throw new Error('check-browser.mjs ORIGIN PAYLOAD CHROMIUM REPORT.json [QUERY] [ONLY.json]');
const payload = JSON.parse(await fs.readFile(payloadPath, 'utf8'));
// ONLY.json lists wiki paths (changed pages and their indexes); the others are not revisited.
const only = onlyPath ? new Set(JSON.parse(await fs.readFile(onlyPath, 'utf8'))) : null;
const checked = only ? payload.pages.filter(p => only.has(p.path)) : payload.pages;
const browser = await chromium.launch({ executablePath });
const report = { pages: [], errors: [], search: null };
const localLinks = new Map();
try {
  const page = await browser.newPage();
  for (const theme of ['light', 'dark']) {
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.emulateMedia({ colorScheme: theme });
      for (const entry of checked) {
        const response = await page.goto(new URL(entry.url, address).href);
        await page.locator('.study-content').waitFor();
        const result = await page.evaluate(async () => {
          document.querySelectorAll('.study-content details').forEach(d => d.open = true);
          const images = [...document.querySelectorAll('.study-content img')];
          await Promise.all(images.map(i => { i.loading = 'eager'; return i.decode().catch(() => {}); }));
          const brokenImages = images.filter(i => !i.naturalWidth).map(i => i.src);
          const anchorTargets = [...document.querySelectorAll('.study-content a[href^="#"]')].map(a => decodeURIComponent(a.hash.slice(1)));
          const missingAnchors = anchorTargets.filter(id => !document.getElementById(id));
          const ids = [...document.querySelectorAll('[id]')].map(e => e.id);
          const duplicates = ids.filter((id, i) => ids.indexOf(id) !== i);
          return { h1: document.querySelectorAll('h1').length, brokenImages, missingAnchors, duplicates,
            overflow: document.documentElement.scrollWidth > innerWidth + 2,
            formulaCount: document.querySelectorAll('mjx-container').length,
            inlineSvgDisplay: [...document.querySelectorAll('mjx-container:not([display]) > svg')].every(e => getComputedStyle(e).display === 'inline'),
            disclosureCount: document.querySelectorAll('.study-content details').length,
            labelCount: document.querySelectorAll('.study-label').length };
        });
        report.pages.push({ url: entry.url, path: entry.path, theme, width, ...result });
        if (theme === 'light' && width === 1440) {
          const links = await page.locator('a[href]').evaluateAll(a => a.map(e => e.href));
          for (const link of links) if (link.startsWith(address + '/')) {
            if (!localLinks.has(link)) localLinks.set(link, new Set());
            localLinks.get(link).add(entry.path);
          }
        }
        if (response.status() !== 200 || result.h1 !== 1 || result.brokenImages.length || result.missingAnchors.length || result.duplicates.length || result.overflow || !result.inlineSvgDisplay) report.errors.push({ url: entry.url, path: entry.path, theme, width, ...result });
      }
    }
  }
  const fetched = new Map();
  for (const [link, sources] of [...localLinks].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) {
    const url = new URL(link);
    const fragment = decodeURIComponent(url.hash.slice(1)); url.hash = '';
    if (!fetched.has(url.href)) {
      const response = await page.request.get(url.href);
      fetched.set(url.href, { status: response.status(), type: response.headers()['content-type'] || '', text: (response.headers()['content-type'] || '').includes('text/html') ? await response.text() : '' });
    }
    const result = fetched.get(url.href);
    const linkError = detail => report.errors.push(...linkProblems(link, sources, payload.pages, address, detail));
    if (result.status !== 200) linkError({ status: result.status });
    else if (fragment && result.type.includes('text/html')) {
      const exists = await page.evaluate(({ html, id }) => !!new DOMParser().parseFromString(html, 'text/html').getElementById(id), { html: result.text, id: fragment });
      if (!exists) linkError({ error: 'Missing cross-page fragment' });
    }
  }
  report.checkedLinks = localLinks.size;
  report.checkedPages = checked.map(p => p.path);
  await page.goto(new URL(payload.pages[0].url, address).href);
  report.search = await page.evaluate(async ({ base, query }) => {
    const index = await import(base + 'pagefind/pagefind.js');
    const result = await index.search(query);
    return { count: result.results.length, hits: await Promise.all(result.results.slice(0, 10).map(async hit => ({ url: (await hit.data()).url }))) };
  }, { base: payload.base, query: searchQuery || payload.pages[1]?.title || payload.title });
  if (!report.search.count || report.search.hits.some(h => h.url.includes('/nyomtatas/'))) report.errors.push({ search: report.search });
  const print = payload.collections.find(c => c.chapters.some(ch => ch.answers)) || payload.collections[0];
  if (print) {
    await page.goto(new URL(payload.base + 'nyomtatas/' + print.id + '/', address).href);
    report.print = await page.evaluate(() => ({ details: document.querySelectorAll('details').length, answers: document.querySelector('.print-answers')?.textContent.length, duplicateIds: [...document.querySelectorAll('[id]')].map(e => e.id).filter((id, i, a) => a.indexOf(id) !== i) }));
    if (report.print.details || report.print.duplicateIds.length || (print.chapters.some(ch => ch.answers) && !report.print.answers)) report.errors.push(report.print);
  }
} finally {
  await browser.close();
  await fs.writeFile(reportPath, JSON.stringify(report, null, 2) + '\n');
}
console.log(JSON.stringify({ checkedViews: report.pages.length, errors: report.errors, search: report.search, print: report.print }, null, 2));
if (report.errors.length) process.exitCode = 1;
