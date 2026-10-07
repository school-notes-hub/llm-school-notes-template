#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { serveSite } from './lib/server.mjs';
import { generatePdfs, printFingerprint } from './lib/pdf.mjs';
import { exportSite } from './lib/export.mjs';

const root = path.dirname(fileURLToPath(import.meta.url));
const [command, ...args] = process.argv.slice(2);
const options = {};
for (let i = 0; i < args.length; i += 2) {
  if (!args[i].startsWith('--') || !args[i + 1]) throw new Error('Expected --option value pairs');
  options[args[i].slice(2)] = args[i + 1];
}
// Exit 3 marks a rendering error tied to one wiki page (the caller sends the writer back to it);
// any other failure exits 1.
process.on('uncaughtException', error => {
  if (error?.page) {
    console.error('study-site-page-error ' + JSON.stringify({ file: error.page, message: String(error.message).slice(0, 500) }));
    process.exit(3);
  }
  console.error(error?.stack || String(error));
  process.exit(1);
});
if (command === 'build') {
  if (!options.repo || !options.config || !options.output) throw new Error('build --repo PATH --config FILE --output NEW_DIRECTORY [--browser CHROMIUM] [--pdf-cache DIR] [--last-updated FILE]');
  const output = path.resolve(options.output);
  const config = JSON.parse(await fs.readFile(options.config, 'utf8'));
  const wantsPdf = config.collections?.some(c => c.pdf === true);
  if (wantsPdf && !options['pdf-cache']) throw new Error('PDF collections require --pdf-cache PRIVATE_DIRECTORY');
  if (wantsPdf) {
    const cache = path.resolve(options['pdf-cache']);
    const repo = await fs.realpath(options.repo);
    // Resolve existing ancestors as well, so a symlink cannot put PDFs in the repo.
    let ancestor = cache, suffix = [];
    while (true) {
      try { ancestor = await fs.realpath(ancestor); break; }
      catch (error) {
        if (error.code !== 'ENOENT') throw error;
        suffix.unshift(path.basename(ancestor)); ancestor = path.dirname(ancestor);
      }
    }
    const actual = path.join(ancestor, ...suffix);
    if (actual === repo || actual.startsWith(repo + path.sep) || actual === root || actual.startsWith(root + path.sep)) {
      throw new Error('PDF cache must be outside source repositories and the renderer package');
    }
    options['pdf-cache'] = actual;
  }
  const browserPath = options.browser || process.env.STUDY_BROWSER;
  const printEngine = wantsPdf ? await printFingerprint(browserPath) : undefined;
  // Per-page dates from the tool ({"wiki/x.md": ISO date}); the renderer has no Git access.
  const lastUpdated = options['last-updated'] ? JSON.parse(await fs.readFile(options['last-updated'], 'utf8')) : {};
  const { payload } = await exportSite({ repo: options.repo, config, output, browserPath, printEngine, lastUpdated });
  // Astro stages prerendered chunks under its working directory (inside outDir when outDir
  // is below it). Running it in the build directory keeps that staging per build, so two
  // learners' builds never share it, and on the output's filesystem; the node_modules link
  // lets the staged chunks resolve the renderer's dependencies.
  await fs.symlink(path.join(root, 'node_modules'), path.join(output, 'node_modules'));
  const child = spawn(process.execPath, [path.join(root, 'node_modules/astro/bin/astro.mjs'), 'build', '--root', root], {
    cwd: output, stdio: 'inherit',
    env: { ...process.env, ASTRO_TELEMETRY_DISABLED: '1', STUDY_PAYLOAD: path.join(output, 'payload.json'), STUDY_OUTPUT: path.join(output, 'site') }
  });
  const code = await new Promise(resolve => child.on('exit', resolve));
  await fs.unlink(path.join(output, 'node_modules'));
  if (code !== 0) throw new Error(`Astro build failed: ${code}`);
  // The PDF step's time, one line the tool reads into its JSONL log (school_notes2 site/build.py).
  // Measured here, not in lib/pdf.mjs: that file is part of the PDF cache fingerprint.
  const pdfStarted = Date.now();
  const pdfTime = failed => { if (wantsPdf) console.log(`PDF time: ${((Date.now()-pdfStarted)/1000).toFixed(1)} s${failed ? ' failed' : ''}`); };
  try { await generatePdfs({output,payload,browserPath,cacheDirectory:options['pdf-cache']}); }
  catch (error) { pdfTime(true); throw error; }
  pdfTime(false);
  console.log(`Built ${payload.pages.length} pages: ${path.join(output, 'site')}`);
} else if (command === 'serve') {
  const base = options.base || '/';
  const { origin } = await serveSite(options.directory, base, Number(options.port || 4321));
  console.log(`Local preview: ${origin}${base}`);
} else {
  console.log('study-site: build --repo PATH --config FILE --output NEW_DIRECTORY [--last-updated FILE]; serve --directory SITE [--port 4321] [--base /]');
  process.exitCode = command ? 1 : 0;
}
