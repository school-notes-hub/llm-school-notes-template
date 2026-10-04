import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { exportSite } from '../lib/export.mjs';
import { sha256 } from '../lib/paths.mjs';

for (const learner of ['benedek', 'barna']) {
  test(`${learner}: decisions and question anchors stay out of public and print exports`, async () => {
    const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'study-learning-'));
    const repo = path.join(tmp, 'repo');
    const body = `---
type: topic
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

# Nyitott kérdések

<!-- q: private-question-canary -->
1. Melyik jelölést használjuk? Addig az itt bevezetett jelöléssel számolj.

<!-- figure: private-figure-canary -->
<!-- figure-request: private-request-canary -->
<!-- image: private-image-canary -->
`;
    const log = `---
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
      await fs.mkdir(path.join(repo, 'wiki'), { recursive: true });
      await fs.mkdir(path.join(repo, 'docs/review'), { recursive: true });
      await fs.writeFile(path.join(repo, 'wiki/tema.md'), body);
      await fs.writeFile(path.join(repo, 'wiki/ora.md'), log);
      await fs.writeFile(path.join(repo, 'docs/review/dontesek.md'), 'PRIVATE_OVERVIEW_CANARY');
      const config = {
        title: 'Jegyzetek', mode: 'public', site: 'https://example.com', base: `/${learner}/`,
        pages: [{ path: 'wiki/tema.md', sha256: sha256(body) }, { path: 'wiki/ora.md', sha256: sha256(log) }],
        collections: [{ id: 'tananyag', title: 'Tananyag', pages: ['wiki/tema.md', 'wiki/ora.md'], pdf: true }]
      };
      const out = path.join(tmp, 'build');
      const { payload } = await exportSite({ repo, config, output: out, printEngine: 'test-engine' });
      const print = JSON.stringify(payload.collections[0].chapters);
      for (const text of [JSON.stringify(config), JSON.stringify(payload), print,
                         await fs.readFile(path.join(out, 'payload.json'), 'utf8')]) {
        assert.doesNotMatch(text, /canary|decisions|draft_tracking|<!--|dontesek/i);
      }
      assert.match(payload.pages[0].html, /Melyik jelölést használjuk/);
      assert.match(print, /Melyik jelölést használjuk/);
      assert.match(print, /⏳ Ez a téma az órán folytatódik/);
      assert.match(payload.pages[1].html, /📎 Füzet: 2026\. 09\. 29\./);
      assert.match(print, /A polisz \(prezentáció\)/);
      assert.match(print, /🔖 Tankönyv: 2\. lecke/);
      assert.deepEqual(await fs.readdir(path.join(out, 'public')), ['media']);
      assert.equal(await fs.readFile(path.join(repo, 'wiki/tema.md'), 'utf8'), body);
    } finally { await fs.rm(tmp, { recursive: true, force: true }); }
  });
}
