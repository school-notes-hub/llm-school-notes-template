import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { DOMParser } from '@xmldom/xmldom';
import { mermaidRenderer } from '../lib/assets.mjs';

const execute = promisify(execFile);
const script = fileURLToPath(new URL('../figure-render.mjs', import.meta.url));
const browser = process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium';

for (const kind of ['svg', 'mermaid']) {
  test(`real ${kind} rasterization produces a nonempty PNG of the figure size`, async () => {
    const folder = await fs.mkdtemp(path.join(os.tmpdir(), 'figure-render-'));
    try {
      const source = path.join(folder, `source.${kind}`);
      const output = path.join(folder, 'output.png');
      const content = kind === 'svg'
        ? '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60" viewBox="0 0 120 60"><rect width="120" height="60" fill="white"/><text x="10" y="30">Erő</text></svg>'
        : 'flowchart LR\n A[Első] --> B[Második]\n';
      await fs.writeFile(source, content);
      await execute(process.execPath, [script, kind, source, output, browser, 'test-figure'], { timeout: 120000 });
      const png = await fs.readFile(output);
      assert.equal(png.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
      const width = png.readUInt32BE(16), height = png.readUInt32BE(20);
      if (kind === 'svg') assert.deepEqual([width, height], [120, 60]);
      else {
        const renderer = await mermaidRenderer(browser);
        try {
          const svg = await renderer.render(content, 'test-figure');
          const root = new DOMParser().parseFromString(svg.toString(), 'image/svg+xml').documentElement;
          const box = root.getAttribute('viewBox').split(/[\s,]+/).map(Number);
          assert.deepEqual([width, height], box.slice(2).map(Math.ceil));
          assert.ok(width > height && height >= 40, `${width}x${height} is not the horizontal graph`);
        } finally { await renderer.close(); }
      }
    } finally { await fs.rm(folder, { recursive: true, force: true }); }
  });
}
