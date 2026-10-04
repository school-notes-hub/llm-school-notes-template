// The figure reviewer uses precisely the build's Mermaid renderer and SVG sanitizer.
import fs from 'node:fs/promises';
import { chromium } from 'playwright';
import { mermaidRenderer, safeSvg } from './lib/assets.mjs';

const [kind, source, output, executablePath, id] = process.argv.slice(2);
if (!['svg', 'mermaid'].includes(kind) || !id) throw new Error('Invalid figure render arguments');
const renderer = await mermaidRenderer(executablePath);
let browser;
try {
  const bytes = await fs.readFile(source);
  const svg = kind === 'mermaid' ? await renderer.render(bytes.toString(), id) : safeSvg(bytes);
  browser = await chromium.launch({ executablePath, headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
  await page.route('**/*', route => route.abort());
  await page.setContent('<!doctype html><body style="margin:0"></body>');
  await page.evaluate(async encoded => {
    const image = document.createElement('img');
    image.src = `data:image/svg+xml;base64,${encoded}`;
    document.body.append(image);
    await image.decode();
  }, svg.toString('base64'));
  await page.locator('img').screenshot({ path: output, animations: 'disabled' });
} finally {
  await browser?.close();
  await renderer.close();
}
