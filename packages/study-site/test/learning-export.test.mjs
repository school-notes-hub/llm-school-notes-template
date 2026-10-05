import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { openSync, closeSync, readFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { exportSite } from '../lib/export.mjs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

function publicConfig(repo, learner) {
  const python = process.env.SCHOOL_NOTES_PYTHON || fileURLToPath(new URL('../../school-notes2/.venv/bin/python', import.meta.url));
  const code = `import json, sys
from pathlib import Path
from school_notes2.wiki import public
repo = Path(sys.argv[1])
print(public.dumps(public.build(repo, public.render_rights(repo), existing={
    "title": "Jegyzetek", "mode": "public", "site": "https://example.test", "base": "/" + sys.argv[2] + "/"})))`;
  const output = path.join(repo, 'public.json');
  const fd = openSync(output, 'w');
  try { execFileSync(python, ['-c', code, repo, learner], {stdio:['ignore', fd, 'inherit']}); }
  finally { closeSync(fd); }
  return JSON.parse(readFileSync(output, 'utf8'));
}

async function subject(repo) {
  await fs.mkdir(path.join(repo, 'wiki/tananyag'), {recursive:true});
  await fs.writeFile(path.join(repo, 'wiki/index.md'), '# Jegyzetek\n');
  await fs.writeFile(path.join(repo, 'wiki/tananyag/index.md'),
    '---\nchapters: [{id: alapok, title: Alapok}]\n---\n# Tananyag\n');
}

for (const learner of ['learner-a', 'learner-b']) {
  test(`${learner}: decisions and question anchors stay out of public and print exports`, async () => {
    const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'study-learning-'));
    const repo = path.join(tmp, 'repo');
    const body = `---
type: topic
chapter: alapok
order: 1
title: Tananyag
decisions:
  - id: private-decision-canary
    claim: PRIVATE_CLAIM_CANARY
    answer: PRIVATE_ANSWER_CANARY
    by: family
    on: 2026-09-29
status: draft
draft_tracking: {since: '2026-09-29', lessons: [PRIVATE_LESSON_CANARY]}
---
# Tananyag

<!-- school-notes:generated pending -->
⏳ Ez a téma az órán folytatódik; a jegyzet az eddig tanult részt tartalmazza.
<!-- /school-notes:generated -->

Nyilvános tananyag.[^private-note][^web]

[^private-note]: PRIVATE_FOOTNOTE_CANARY, 3. dia. [Forrás](../../sources/private.png)
[^web]: [Nyilvános hivatkozás](https://example.test/reference)

# Nyitott kérdések

<!-- q: private-question-canary -->
1. Melyik jelölést használjuk? Addig az itt bevezetett jelöléssel számolj.

<!-- figure: private-figure-canary -->
<!-- figure-request: private-request-canary -->
<!-- image: private-image-canary -->
`;
    const log = `---
type: lesson-notes
chapter: alapok
order: 2
title: Az óra
lessons:
  - {date: 2026-09-29, topics: [tema.md], materials: ['A polisz (prezentáció)']}
---
<!-- school-notes:generated lesson-sources -->
📎 Füzet: 2026. 09. 29. · Tanári anyag: A polisz (prezentáció)
<!-- /school-notes:generated -->

🔖 Tankönyv: 2. lecke, 13–15. oldal
`;
    try {
      await subject(repo);
      await fs.mkdir(path.join(repo, 'docs/review'), { recursive: true });
      await fs.mkdir(path.join(repo, 'sources'), { recursive: true });
      await fs.writeFile(path.join(repo, 'sources/private.png'), 'PRIVATE_SOURCE_CANARY');
      await fs.writeFile(path.join(repo, 'wiki/log.md'), 'PRIVATE_LOG_CANARY');
      await fs.writeFile(path.join(repo, 'wiki/tananyag/tema.md'), body);
      await fs.writeFile(path.join(repo, 'wiki/tananyag/ora.md'), log);
      await fs.writeFile(path.join(repo, 'docs/review/dontesek.md'), 'PRIVATE_OVERVIEW_CANARY');
      const config = publicConfig(repo, learner);
      const out = path.join(tmp, 'build');
      const { payload } = await exportSite({ repo, config, output: out, printEngine: 'test-engine' });
      const print = JSON.stringify(payload.collections.map(c => c.chapters));
      for (const text of [JSON.stringify(config), JSON.stringify(payload), print,
                         await fs.readFile(path.join(out, 'payload.json'), 'utf8')]) {
        assert.doesNotMatch(text, /canary|decisions|draft_tracking|<!--|dontesek/i);
      }
      assert.match(payload.pages.find(p => p.path === 'wiki/tananyag/tema.md').html, /Melyik jelölést használjuk/);
      assert.match(print, /Nyilvános hivatkozás/);
      assert.match(print, /Melyik jelölést használjuk/);
      assert.doesNotMatch(print, /⏳/);
      assert.match(payload.pages.find(p => p.path === 'wiki/tananyag/ora.md').html, /📎 Füzet: 2026\. 09\. 29\./);
      assert.match(print, /A polisz \(prezentáció\)/);
      assert.match(print, /🔖 Tankönyv: 2\. lecke/);
      assert.deepEqual(await fs.readdir(path.join(out, 'public')), ['media']);
      assert.equal(await fs.readFile(path.join(repo, 'wiki/tananyag/tema.md'), 'utf8'), body);
    } finally { await fs.rm(tmp, { recursive: true, force: true }); }
  });
}

// The controller supplies its installed Chromium. No network resources are used.
for (const learner of ['learner-a', 'learner-b']) {
  test(`${learner}: actual HTML, PDF and site files contain no private canaries`,
    { skip: !process.env.STUDY_BROWSER }, async () => {
      const { execFileSync } = await import('node:child_process');
      const { fileURLToPath } = await import('node:url');
      const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'study-public-build-'));
      const repo = path.join(tmp, 'repo');
      const source = `---
type: topic
chapter: alapok
order: 1
title: Tananyag
decisions:
  - {id: private-decision, claim: PRIVATE_CLAIM_CANARY, answer: PRIVATE_ANSWER_CANARY, by: family, on: 2026-10-04}
---
# Tananyag

A mértékegység megadja a mérés alapját.[^private]

[^private]: PRIVATE_FOOTNOTE_CANARY. [Forrás](../../sources/private.png)

<!-- q: private-question-canary -->
<!-- figure: private-figure-canary -->
<!-- figure-request: private-request-canary -->
<!-- image: private-image-canary -->
`;
      try {
        for (const dir of ['wiki', 'sources', 'docs/review']) await fs.mkdir(path.join(repo, dir), {recursive:true});
        await subject(repo);
        await fs.writeFile(path.join(repo, 'wiki/tananyag/tema.md'), source);
        await fs.writeFile(path.join(repo, 'wiki/log.md'), 'PRIVATE_LOG_CANARY');
        await fs.writeFile(path.join(repo, 'sources/private.png'), 'PRIVATE_SOURCE_CANARY');
        await fs.writeFile(path.join(repo, 'docs/review/report.md'), 'PRIVATE_REVIEW_CANARY');
        const config = publicConfig(repo, learner);
        const configPath = path.join(tmp, 'public.json');
        await fs.writeFile(configPath, JSON.stringify(config));
        const out = path.join(tmp, 'build');
        execFileSync(process.execPath, [fileURLToPath(new URL('../cli.mjs', import.meta.url)), 'build',
          '--repo',repo,'--config',configPath,'--output',out,'--browser',process.env.STUDY_BROWSER,
          '--pdf-cache',path.join(tmp,'pdf-cache')], {stdio:'pipe',timeout:180000});
        const files = await fs.readdir(path.join(out,'site'), {recursive:true,withFileTypes:true});
        let pdfs = 0;
        for (const file of files) {
          if (!file.isFile()) continue;
          const full = path.join(file.parentPath, file.name);
          assert.doesNotMatch(path.relative(path.join(out,'site'),full), /^(sources|references|docs)\//);
          const text = file.name.endsWith('.pdf')
            ? (pdfs++, execFileSync('pdftotext',[full,'-'],{encoding:'utf8'}))
            : await fs.readFile(full,'utf8');
          assert.doesNotMatch(text, /PRIVATE_\w+_CANARY|private-(?:question|figure|request|image)-canary|"decisions"\s*:|<!--\s*(?:q|figure|figure-request|image):/i);
        }
        assert.equal(pdfs,1);
        assert.doesNotMatch(await fs.readFile(configPath,'utf8'), /canary|decisions/i);
      } finally { await fs.rm(tmp,{recursive:true,force:true}); }
    });
}

test('private log and review paths cannot be added to the public page list', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'study-private-path-'));
  try {
    const repo = path.join(tmp,'repo');
    await fs.mkdir(repo);
    for (const file of ['wiki/log.md','docs/review/private.md','sources/private.md']) {
      const config = {title:'T',mode:'public',site:'https://example.test',pages:[{path:file,sha256:'a'.repeat(64)}]};
      await assert.rejects(exportSite({repo,config,output:path.join(tmp,'out')}), /Private wiki log|Not a wiki Markdown/);
    }
  } finally { await fs.rm(tmp,{recursive:true,force:true}); }
});
