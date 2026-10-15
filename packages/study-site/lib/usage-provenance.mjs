// Private source evidence stays in the preview work folder, never in the site.
import fs from 'node:fs/promises';
import path from 'node:path';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import { visit } from 'unist-util-visit';
import { splitMarkdown, renderMarkdown } from './markdown.mjs';
import { read, digest } from './usage-shots.mjs';

export async function classroomParagraphs(source, isClassroomLink) {
  const { body } = splitMarkdown(source);
  const tree = unified().use(remarkParse).use(remarkGfm).parse(body);
  const definitions = new Map();
  visit(tree, 'definition', n => definitions.set(n.identifier, n.url));
  const classroom = new Set();
  for (const note of tree.children.filter(n => n.type === 'footnoteDefinition')) {
    const links = [];
    visit(note, n => {
      if (n.type === 'link') links.push(n.url);
      if (n.type === 'linkReference') links.push(definitions.get(n.identifier));
    });
    for (const url of links.filter(Boolean)) {
      if (await isClassroomLink(url)) classroom.add(note.identifier);
    }
  }
  const html = [];
  for (const paragraph of tree.children.filter(n => n.type === 'paragraph')) {
    const refs = [];
    visit(paragraph, 'footnoteReference', n => refs.push(n.identifier));
    if (!refs.some(id => classroom.has(id))) continue;
    const fragment = body.slice(paragraph.position.start.offset, paragraph.position.end.offset);
    const notes = tree.children.filter(n => ['footnoteDefinition', 'definition'].includes(n.type))
      .map(n => body.slice(n.position.start.offset, n.position.end.offset)).join('\n\n');
    html.push((await renderMarkdown(fragment + '\n\n' + notes, {
      publicView: true, resolveUrl: async url => ({url}),
    })).html);
  }
  return html;
}

export async function sourceParagraphs(repo, build, payload) {
  if (!repo) return {};
  const receipt = await read(path.join(build, 'receipt.private.json'));
  const result = {};
  for (const page of payload.pages.filter(p => p.kind === 'topic')) {
    const entry = receipt.pages.find(p => p.route === page.route);
    if (!entry) continue;
    const file = path.resolve(repo, entry.input);
    if (!file.startsWith(path.resolve(repo, 'wiki') + path.sep)) continue;
    const source = await fs.readFile(file, 'utf8');
    if (digest(source) !== entry.sourceSha256) continue; // Stale evidence cannot qualify E2.
    result[page.route] = await classroomParagraphs(source, async url => {
      if (/^(?:[a-z]+:|\/|#)/i.test(url)) return false;
      const target = path.resolve(path.dirname(file), decodeURIComponent(url.split('#')[0]));
      if (target.startsWith(path.resolve(repo, 'sources') + path.sep)) return true;
      if (!target.startsWith(path.resolve(repo, 'wiki') + path.sep)) return false;
      try { return splitMarkdown(await fs.readFile(target, 'utf8')).metadata.type === 'lesson-notes'; }
      catch { return false; }
    });
  }
  return result;
}
