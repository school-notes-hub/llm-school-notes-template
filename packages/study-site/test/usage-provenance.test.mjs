import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { classroomParagraphs, sourceParagraphs } from '../lib/usage-provenance.mjs';
import { digest } from '../lib/usage-shots.mjs';

test('source paragraphs follow resolved footnotes, not footnote names or unlabelled appearance', async () => {
  const source = `Introduction.\n\nBook.[^fuzet]\n\nClassroom **fact**.[^arbitrary]\n\n[^fuzet]: [Book](references/book.md)\n[^arbitrary]: [Lesson][lesson]\n\n[lesson]: notes.md\n`;
  const html = await classroomParagraphs(source, async url => url === 'notes.md');
  assert.equal(html.length, 1);
  assert.match(html[0], /Classroom <strong>fact<\/strong>\./);
  assert.doesNotMatch(html[0], /footnote|notes.md/);
});

test('E2 provenance uses the source hash in the build receipt and lesson-notes type', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'usage-evidence-'));
  try {
    await fs.mkdir(path.join(root, 'wiki'));
    const source = 'Classroom.[^x]\n\n[^x]: [Lesson](lesson.md)\n';
    await fs.writeFile(path.join(root, 'wiki/topic.md'), source);
    await fs.writeFile(path.join(root, 'wiki/lesson.md'), '---\ntype: lesson-notes\n---\n');
    await fs.writeFile(path.join(root, 'receipt.private.json'), JSON.stringify({pages:[{route:'topic',input:'wiki/topic.md',sourceSha256:digest(source)}]}));
    const payload = {pages:[{route:'topic',kind:'topic'}]};
    assert.equal((await sourceParagraphs(root, root, payload)).topic.length, 1);
    await fs.writeFile(path.join(root, 'wiki/lesson.md'), '---\ntype: topic\n---\n');
    assert.deepEqual((await sourceParagraphs(root, root, payload)).topic, []);
    await fs.writeFile(path.join(root, 'wiki/topic.md'), source + '\nChanged');
    assert.deepEqual(await sourceParagraphs(root, root, payload), {});
  } finally { await fs.rm(root, {recursive:true, force:true}); }
});
