import test from 'node:test';
import assert from 'node:assert/strict';

test('an empty jump-target anchor keeps its plain id for links from other pages', async () => {
  const { renderMarkdown } = await import('../lib/markdown.mjs');
  const out = await renderMarkdown('# T\n\nSzöveg.\n\n<a id="pdf-13-oldal"></a>\n\n## 13. oldal\n\n[ugrás](#pdf-13-oldal)\n', { resolveUrl: async h => h });
  const html = out.html ?? String(out);
  assert.ok(html.includes('id="pdf-13-oldal"'), html);
  assert.ok(html.includes('href="#pdf-13-oldal"'), html);
});

test('a jump-target anchor with an accented Hungarian id keeps its plain id', async () => {
  const { renderMarkdown } = await import('../lib/markdown.mjs');
  const out = await renderMarkdown('# T\n\n<a id="2-dia---a-földművelés-térképe"></a>\n\n## A földművelés elterjedése\n', { resolveUrl: async h => h });
  const html = out.html ?? String(out);
  assert.ok(html.includes('id="2-dia---a-földművelés-térképe"'), html);
  assert.ok(!html.includes('user-content-2-dia'), html);
});

test('an mp4 image becomes a video with its PNG poster; print keeps only the poster', async () => {
  const { renderMarkdown, printSection } = await import('../lib/markdown.mjs');
  const resolveUrl = async h => h.replace('../assets/', 'assets/');
  const out = await renderMarkdown('# T\n\n![Az inga mozgása](../assets/inga/figure.mp4)\n', { resolveUrl });
  assert.match(out.html, /<span class="study-video"><video controls preload="metadata" playsinline poster="assets\/inga\/figure.png" src="assets\/inga\/figure.mp4" aria-label="Az inga mozgása" class="study-video-player">Az inga mozgása<\/video><img src="assets\/inga\/figure.png" alt="Az inga mozgása" loading="eager" decoding="async" class="study-figure study-video-poster"><\/span>/);
  assert.deepEqual(out.audit.images, ['assets/inga/figure.png']);
  assert.equal((await renderMarkdown('# T\n\n![Az inga mozgása](../assets/inga/figure.mp4)\n', { resolveUrl })).html, out.html);
  const printed = (await printSection(out.html, 'p1-')).html;
  assert.doesNotMatch(printed, /<video/);
  assert.match(printed, /<img src="assets\/inga\/figure.png"[^>]*study-video-poster/);
});

test('public view: private photo lists, private footnotes and the grade prefix are left out', async () => {
  const { renderMarkdown } = await import('../lib/markdown.mjs');
  const resolveUrl = async h => /(^|\/)(sources|references)\//.test(h) ? { citationOnly: true } : h;
  const source = [
    '---', 'title: Matematika', '---', '# 📘 9. évfolyam: Halmazok', '', 'A [4. füzetfotón](../../sources/a/04.jpg) X áll.[^fuzet] Lásd még.[^web]', '',
    '# Fotók', '', '* [1. fotó](../../sources/a/01.jpg) - Venn-diagram', '* [2. fotó](../../sources/a/02.jpg) - szita', '',
    '<br />', '', '# Kérdések', '', 'Egy kérdés.', '',
    '[^fuzet]: Füzet, 4. fotó, [eredeti](../../sources/a/04.jpg).',
    '[^web]: OpenStax: [Sets](https://openstax.org/sets); [mentett másolat](../../references/b/README.md).', '',
  ].join('\n');
  const out = await renderMarkdown(source, { resolveUrl, publicView: true });
  assert.match(out.html, /📘 Halmazok/);
  assert.doesNotMatch(out.html, /évfolyam|Fotók|1\. fotó|Venn|Füzet, 4\. fotó|nem nyilvános|sources\/|references\//);
  assert.match(out.html, /A 4\. füzetfotón X áll\. Lásd még\./);
  assert.match(out.html, /href="https:\/\/openstax\.org\/sets"/);
  assert.match(out.html, /mentett másolat/);
  assert.equal((out.html.match(/data-footnote-ref/g) || []).length, 1);
  assert.deepEqual(out.headings.map(h => h.text), ['📘 Halmazok', 'Kérdések']);
  assert.equal(out.title, 'Matematika');
  assert.equal((await renderMarkdown('---\ntitle: "📘 9. évfolyam: Halmazok"\n---\nSzöveg.\n', { resolveUrl, publicView: true })).title, '📘 Halmazok');
  assert.equal((await renderMarkdown(source, { resolveUrl, publicView: true })).html, out.html);
  // The private preview keeps everything.
  const preview = await renderMarkdown(source, { resolveUrl: async h => h });
  assert.match(preview.html, /9\. évfolyam: Halmazok/);
  assert.match(preview.html, /1\. fotó/);
  assert.equal((preview.html.match(/data-footnote-ref/g) || []).length, 2);
});

test('public view: footnotes stay consistent when private items, headings or citations go', async () => {
  const { renderMarkdown } = await import('../lib/markdown.mjs');
  const resolveUrl = async h => /(^|\/)(sources|references)\//.test(h) ? { citationOnly: true } : h;
  const render = source => renderMarkdown('---\ntitle: T\n---\n' + source, { resolveUrl, publicView: true });
  // A kept web footnote that starts with a private link keeps its item and its reference.
  let out = await render('Szöveg.[^t]\n\n[^t]: [Tankönyv 12. o.](../references/tk/README.md); online: [OpenStax](https://openstax.org/x)\n');
  assert.match(out.html, /data-footnote-ref[^>]*>1<\/a>/);
  assert.match(out.html, /Tankönyv 12\. o\.; online: <a href="https:\/\/openstax\.org\/x">OpenStax<\/a>/);
  // A footnote referenced only from a dropped list item goes; the others are renumbered.
  out = await render('Első.[^a]\n\n* [1. fotó](../sources/a/01.jpg) - Venn[^w]\n\nHarmadik.[^b]\n\n[^a]: [A](https://a.example)\n[^w]: [W](https://w.example)\n[^b]: [B](https://b.example)\n');
  assert.doesNotMatch(out.html, /w\.example|fn-w|Venn/);
  assert.deepEqual([...out.html.matchAll(/data-footnote-ref[^>]*>(\d+)<\/a>/g)].map(m => m[1]), ['1', '2']);
  assert.equal((out.html.match(/<li id="[^"]*fn-/g) || []).length, 2);
  // A footnote referenced twice, once from a dropped item: it stays, its dead back-reference goes.
  out = await render('Első.[^a]\n\n* [1. fotó](../sources/a/01.jpg) - kép[^a]\n\n[^a]: [A](https://a.example)\n');
  assert.equal((out.html.match(/data-footnote-ref/g) || []).length, 1);
  assert.equal((out.html.match(/data-footnote-backref=""/g) || []).length, 1);
  // Only a private footnote: no footnote section at all.
  out = await render('Szöveg.[^f]\n\n[^f]: Füzet, 3. fotó.\n');
  assert.doesNotMatch(out.html, /footnote|Források/);
  // A parent heading emptied by its emptied sub-headings goes as well; nested lists too.
  out = await render('# Fotók\n\n## Óra 1\n\n* [a](../sources/a.jpg)\n  * [b](../sources/b.jpg)\n\n## Óra 2\n\n* [c](../sources/c.jpg)\n\n# Kérdések\n\nX\n');
  assert.deepEqual(out.headings.map(h => h.text), ['Kérdések']);
  assert.doesNotMatch(out.html, /Fotók|Óra|<ul/);
  // A web source written as a reference link or raw HTML stays.
  out = await render('A.[^r] B.[^h]\n\n[^r]: [OpenStax][os]\n[^h]: <a href="https://h.example">H</a>\n\n[os]: https://openstax.org\n');
  assert.equal((out.html.match(/data-footnote-ref/g) || []).length, 2);
  // A title that is only a grade prefix keeps its text.
  assert.equal((await renderMarkdown('# 9. évfolyam: *Halmazok*\n', { resolveUrl, publicView: true })).title, '9. évfolyam: ');
});

test('the footnote list has a visible heading', async () => {
  const { renderMarkdown } = await import('../lib/markdown.mjs');
  const out = await renderMarkdown('---\ntitle: T\n---\n# Nyitott kérdések\n\nKérdés.[^w]\n\n[^w]: [W](https://w.example)\n', { resolveUrl: async h => h, publicView: true });
  assert.match(out.html, /<section data-footnotes="" class="footnotes"><h2 id="user-content-footnote-label">Források<\/h2>/);
  assert.doesNotMatch(out.html, /sr-only/);
});


test('web keeps real-gap notices while print and PDF chapters omit every pending notice', async () => {
  const { renderMarkdown, printSection } = await import('../lib/markdown.mjs');
  const source = '# Tananyag\n\n⏳ Ehhez a részhez ábra készül.\n\n⏳ Ezt az oldalt még ellenőrizzük.\n\n⏳ Ez a téma az órán folytatódik; a jegyzet az eddig tanult részt tartalmazza.\n\nMegtanulható állítás.\n';
  const marked = source.replace(/(^⏳.*$)/gm, '<!-- school-notes:generated pending -->\n$1\n<!-- /school-notes:generated -->');
  const rendered = await renderMarkdown(marked);
  assert.match(rendered.html, /⏳/);
  const print = await printSection(rendered.html, 'p-');
  assert.doesNotMatch(print.html + print.answers, /⏳/);
  assert.match(print.html, /Megtanulható állítás/);
});


test('cross-page accented anchor failures identify both source pages and the target', async () => {
  const { linkProblems } = await import('../lib/browser-links.mjs');
  const { renderMarkdown } = await import('../lib/markdown.mjs');
  const anchor = '2-dia---a-földművelés-térképe';
  const target = await renderMarkdown(`# Téma\n\n<a id="${anchor}"></a>\n`);
  assert.ok(target.html.includes(`id="${anchor}"`));
  const link = `http://localhost/jegyzet/tema/#${encodeURIComponent(anchor)}`;
  const pages = [{path:'wiki/t/tema.md',url:'/jegyzet/tema/'}];
  const problems = linkProblems(link, new Set(['wiki/t/b.md','wiki/t/a.md']), pages, 'http://localhost', {error:'Missing cross-page fragment'});
  assert.deepEqual(problems.map(p => [p.path,p.target]), [
    ['wiki/t/a.md','wiki/t/tema.md'], ['wiki/t/b.md','wiki/t/tema.md']]);
  assert.ok(problems.every(p => p.link === link));
});


test('print preserves an authored hourglass paragraph', async () => {
  const { printSection, renderMarkdown } = await import('../lib/markdown.mjs');
  const rendered = await renderMarkdown('# Idő\n\n⏳ Mérd meg az időt!\n');
  const print = await printSection(rendered.html, 'p-');
  assert.match(print.html, /⏳ Mérd meg az időt!/);
});

test('a lesson date is a quiet meta item; an uncertain one keeps its range only as tooltip (sn 0.3.8)', async () => {
  const { renderMarkdown } = await import('../lib/markdown.mjs');
  const md = '# T\n\n* [Pótolt óra](a.md) <span class="study-when study-when-unsure" title="Dátum nélküli óra: szept. 23. – okt. 4.">~szept. vége</span>\n\n'
    + '| Dátum | Óra |\n|---|---|\n| <span class="study-when">szept. 22.</span> | X |\n\n'
    + '<span class="evil" onclick="x()" title="t">y</span>\n';
  for (const publicView of [false, true]) {
    const out = await renderMarkdown(md, { resolveUrl: async h => h, publicView });
    const html = out.html ?? String(out);
    assert.ok(html.includes('<span class="study-when study-when-unsure" title="Dátum nélküli óra: szept. 23. – okt. 4.">~szept. vége</span>'), html);
    assert.ok(html.includes('<span class="study-when">szept. 22.</span>'), html);
    assert.ok(!html.includes('evil') && !html.includes('onclick'), html);
  }
  const fs = await import('node:fs');
  const css = fs.readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8');
  assert.match(css, /\.study-content \.study-when \{[^}]*font-size: \.85rem[^}]*var\(--sl-color-gray-3/);
  assert.match(css, /\.study-content \.study-when::before \{[^}]*background-color: currentColor[^}]*mask:/);
  assert.match(css, /@media print[\s\S]*\.study-content \.study-when-unsure \{ display: none; \}/);
});
