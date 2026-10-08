import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { renderMarkdown, printSection } from '../lib/markdown.mjs';
import { exportSite } from '../lib/export.mjs';
import { sha256, readInside } from '../lib/paths.mjs';
import { safeSvg } from '../lib/assets.mjs';
const fixture = fileURLToPath(new URL('./fixtures/', import.meta.url));
const resolveUrl = async s => s;
async function settings() {
  return {
    title: 'Minta', mode: 'private-preview', base: '/pelda/',
    pages: await Promise.all(['wiki/index.md', 'wiki/tema.md'].map(async p => ({ path: p, sha256: sha256(await fs.readFile(path.join(fixture, p))) }))),
    assets: [{ path: 'wiki/assets/diagram.svg', sha256: sha256(await fs.readFile(path.join(fixture, 'wiki/assets/diagram.svg'))) }],
    collections: [{ id: 'minta', title: 'Minta', pages: ['wiki/index.md', 'wiki/tema.md'] }]
  };
}
test('Markdown source remains untouched; metadata/comments do not reach the payload', async () => {
  const config = await settings();
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'study-export-'));
  try {
    const { payload, receipt } = await exportSite({ repo: fixture, config, output: path.join(tmp, 'build') });
    const serialized = JSON.stringify(payload);
    assert.ok(!serialized.includes('CANARY'));
    assert.ok(!serialized.includes('private_path'));
    assert.ok(!serialized.includes('/private/'));
    assert.match(payload.pages[0].html, /href="\/pelda\/tema\/#azonos-c%C3%ADm"/);
    assert.match(payload.pages[1].html, /href="\/pelda\/"/);
    assert.equal(payload.pages[0].headings.filter(h => h.text === 'Azonos cím').length, 2);
    assert.ok(payload.pages[0].headings.some(h => h.slug === 'azonos-cím-1'));
    assert.match(payload.pages[0].html, /H<sub>2<\/sub>O/);
    assert.match(payload.pages[0].html, /<small class="study-label">💡 Példa🤖 magyarázata<\/small>/);
    assert.doesNotMatch(payload.pages[0].html, /\[!TIP\]|<h1/);
    assert.match(payload.pages[0].html, /<mjx-container/);
    assert.equal(receipt.pages[0].audit.formulas.length, 2);
    const svg = await fs.readFile(path.join(tmp, 'build/public', receipt.assets[0].output), 'utf8');
    assert.ok(!svg.includes('CANARY'));
    assert.match(svg, /Balról jobbra/);
    assert.match(svg, /M 10 30 L 110 30/);
    for (const p of config.pages) assert.equal(sha256(await fs.readFile(path.join(fixture, p.path))), p.sha256);
  } finally { await fs.rm(tmp, { recursive: true, force: true }); }
});
test('source hashes, asset allowlists and unreviewed publication fail closed', async () => {
  const config = await settings();
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'study-boundary-'));
  try {
    await assert.rejects(exportSite({ repo: fixture, config: { ...config, mode: 'public' }, output: path.join(tmp, 'public') }), /Public site origin required/);
    await assert.rejects(exportSite({ repo: fixture, config: { ...config, assets: [] }, output: path.join(tmp, 'missing') }), /Unapproved image/);
    await assert.rejects(exportSite({ repo: fixture, config: { ...config, pages: [{ ...config.pages[0], sha256: '0'.repeat(64) }] }, output: path.join(tmp, 'changed') }), /Changed input/);
    await assert.rejects(exportSite({ repo: fixture, config, output: fixture }), /outside/);
    await assert.rejects(readInside(fixture, '../outside'), /Unsafe/);
    await fs.symlink('/etc/hosts', path.join(tmp, 'escape'));
    await assert.rejects(readInside(tmp, 'escape'), /escapes/);
  } finally { await fs.rm(tmp, { recursive: true, force: true }); }
});
test('active HTML and SVG never survive; real subscript and details do', async () => {
  const r = await renderMarkdown('# Test\n\n<script>alert(1)</script><iframe src="https://example.com"></iframe><img src="image.svg" onerror="alert(1)"><sub>2</sub>', { resolveUrl });
  assert.doesNotMatch(r.html, /script|iframe|onerror|alert/);
  assert.match(r.html, /<sub>2<\/sub>/);
  assert.throws(() => safeSvg(Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"><script>oops</script></svg>')), /active/);
  assert.throws(() => safeSvg(Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"><use href="https://example.com/x"/></svg>')), /reference/);
});
test('Mermaid graph line breaks and relationship source are preserved', async () => {
  const graph = 'flowchart TD\n A --> B\n B --> C\n';
  let observed;
  await renderMarkdown('```mermaid\n' + graph + '```', { resolveUrl, mermaid: async code => { observed = code; return '/diagram.svg'; } });
  assert.equal(observed, graph);
});
test('an invalid or HTML-producing formula cannot become a silently wrong page', async () => {
  await assert.rejects(renderMarkdown('$\\thisMacroDoesNotExist{a}$', { resolveUrl }), /Math rendering failed/);
  await assert.rejects(renderMarkdown('$\\href{javascript:alert(1)}{x}$', { resolveUrl }), /Math rendering failed/);
});
test('print moves complete answers and prefixes footnote IDs without losing references', async () => {
  const source = await fs.readFile(path.join(fixture, 'wiki/index.md'), 'utf8');
  const r = await renderMarkdown(source, { resolveUrl });
  const print = await printSection(r.html, 'chapter-');
  assert.doesNotMatch(print.html, /<details|2F/);
  assert.match(print.answers, /2F/);
  const combined = print.html + print.answers;
  const ids = [...combined.matchAll(/\sid="([^"]+)"/g)].map(m => m[1]);
  for (const [, href] of combined.matchAll(/href="#([^" ]+)"/g)) assert.ok(ids.includes(href), `Missing print anchor ${href}`);
});

test('PDF keys reuse unchanged topics and invalidate only affected dependencies', async () => {
  const tmp=await fs.mkdtemp(path.join(os.tmpdir(),'study-pdf-keys-'));
  try {
    const repo=path.join(tmp,'repo');await fs.cp(fixture,repo,{recursive:true});
    const config=await settings();config.collections=config.pages.map((p,i)=>({id:'topic-'+i,title:'Topic '+i,pages:[p.path],pdf:true}));
    let sequence=0;
    const keys=async (engine='engine-1')=>(await exportSite({repo,config,output:path.join(tmp,'build-'+sequence++),printEngine:engine})).payload.collections.map(c=>c.pdf.key);
    const original=await keys();assert.deepEqual(await keys(),original);
    config.collections[1].group="topic-0";assert.deepEqual(await keys(),original);
    const changed=config.pages[1];await fs.appendFile(path.join(repo,changed.path),'\nÚj mondat.\n');changed.sha256=sha256(await fs.readFile(path.join(repo,changed.path)));
    const text=await keys();assert.equal(text[0],original[0]);assert.notEqual(text[1],original[1]);
    const asset=config.assets[0];const file=path.join(repo,asset.path);await fs.writeFile(file,(await fs.readFile(file,'utf8')).replace('Balról jobbra','Másik felirat'));asset.sha256=sha256(await fs.readFile(file));
    const image=await keys();assert.notEqual(image[0],text[0]);assert.equal(image[1],text[1]);
    const engine=await keys('engine-2');assert.ok(engine.every((k,i)=>k!==image[i]));
  } finally {await fs.rm(tmp,{recursive:true,force:true});}
});

test('print keeps image captions together and ignores lazy-loading fluctuations', async()=>{
  const a=await printSection('<p><em>Saját térkép.</em></p><p><img src="/figure.svg" loading="lazy"></p><p><small>Forrás</small></p>','c-');
  const b=await printSection('<p><em>Saját térkép.</em></p><p><img src="/figure.svg" loading="eager"></p><p><small>Forrás</small></p>','c-');
  assert.equal(a.html,b.html);assert.match(a.html,/<figure class="print-figure"><p><em>Saját térkép/);assert.match(a.html,/<small>Forrás<\/small><\/p><\/figure>/);
});

test('formulas in HTML disclosure questions render in both question and answer headings', async()=>{
 const r=await renderMarkdown('<details><summary>Mi az erő, ha $g=10\\ \\text{m}/\\text{s}^2$?</summary>\n\nVálasz.\n\n</details>',{resolveUrl});
 assert.match(r.html,/<summary>.*<mjx-container/);assert.equal(r.audit.formulas.length,1);
 const printed=await printSection(r.html,'p-');assert.match(printed.answers,/<h3>.*<mjx-container/);assert.doesNotMatch(printed.answers,/\$g=/);
});

// Legacy folder is prohibited even in private previews; renaming is addressed by rights review.
test('teacher slide copies cannot enter an asset allowlist', async () => {
  const config = await settings();
  config.assets.push({ path: 'wiki/assets/orai/slide.png', sha256: '0'.repeat(64) });
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'study-rights-'));
  try {
    await assert.rejects(exportSite({ repo: fixture, config, output: path.join(tmp, 'build') }), /Teacher-material copies/);
  } finally { await fs.rm(tmp, { recursive: true, force: true }); }
});

test('feedback uses only an explicit public repository name', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'study-feedback-'));
  try {
    const config = await settings(); config.feedbackRepository = 'example/public-notes';
    const { payload } = await exportSite({ repo: fixture, config, output: path.join(tmp, 'good') });
    assert.equal(payload.feedbackRepository, 'example/public-notes');
    config.feedbackRepository = 'https://github.com/example/private?token=secret';
    await assert.rejects(exportSite({ repo: fixture, config, output: path.join(tmp, 'bad') }), /Invalid public feedback/);
  } finally { await fs.rm(tmp, { recursive: true, force: true }); }
});

// Preserve acquired standard symbols byte-for-byte, including GIF originals.
test('approved GIF symbols export unchanged and are served as images', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'study-gif-'));
  let server;
  try {
    const repo = path.join(tmp, 'repo'); await fs.cp(fixture, repo, {recursive:true});
    const gif = Buffer.from([71,73,70,56,57,97,1,0,1,0,128,0,0,0,0,0,255,255,255,33,249,4,1,0,0,0,0,44,0,0,0,0,1,0,1,0,0,2,2,68,1,0,59]);
    const file='wiki/assets/symbol.gif'; await fs.writeFile(path.join(repo,file),gif);
    await fs.appendFile(path.join(repo,'wiki/tema.md'),'\n![Jel](assets/symbol.gif)\n');
    const config=await settings();config.pages[1].sha256=sha256(await fs.readFile(path.join(repo,'wiki/tema.md')));
    config.assets.push({path:file,sha256:sha256(gif)});
    const output=path.join(tmp,'build');const {receipt}=await exportSite({repo,config,output});
    const entry=receipt.assets.find(a=>a.input===file);assert.ok(entry);
    assert.deepEqual(await fs.readFile(path.join(output,'public',entry.output)),gif);
    const {serveSite}=await import('../lib/server.mjs');
    const served=await serveSite(path.join(output,'public'),'/pelda/',0);server=served.server;
    const response=await fetch(served.origin+'/pelda/'+entry.output);
    assert.match(response.headers.get('content-type'),/^image\/gif/);
    assert.deepEqual(Buffer.from(await response.arrayBuffer()),gif);
  } finally { if(server) await new Promise(r=>server.close(r));await fs.rm(tmp,{recursive:true,force:true}); }
});

test('standard Graphviz/Matplotlib DTD is stripped; entities and other DTDs stay blocked', () => {
  const body='<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L10 10"/></svg>';
  const declaration='<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"\n "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">';
  const clean=safeSvg(Buffer.from(declaration+body)).toString();
  assert.doesNotMatch(clean,/DOCTYPE/);assert.match(clean,/M0 0 L10 10/);
  assert.throws(()=>safeSvg(Buffer.from('<!DOCTYPE svg SYSTEM "file:///etc/passwd">'+body)),/declarations/);
  assert.throws(()=>safeSvg(Buffer.from(declaration+'<!ENTITY x "y">'+body)),/declarations/);
});

test('content license is opt-in and changes invalidate PDF keys', async () => {
  const config = await settings();
  config.collections[0].pdf = true;
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'study-license-'));
  const run = (name, value) => exportSite({repo:fixture, config:value, output:path.join(tmp,name), printEngine:'test-engine'});
  try {
    const plain = await run('plain',config);
    assert.equal(plain.payload.license, undefined);
    const licensed = await run('licensed',{...config, license:{id:'CC BY-NC-SA 4.0',attribution:'Minta'}});
    assert.equal(licensed.payload.license.url,'https://creativecommons.org/licenses/by-nc-sa/4.0/');
    assert.notEqual(plain.payload.collections[0].pdf.key,licensed.payload.collections[0].pdf.key);
    const changed = await run('changed',{...config, license:{id:'CC BY-SA 4.0',attribution:'Minta'}});
    assert.notEqual(changed.payload.collections[0].pdf.key,licensed.payload.collections[0].pdf.key);
    await assert.rejects(run('bad',{...config,license:{id:'toString',attribution:'Minta'}}),/license/);
  } finally { await fs.rm(tmp,{recursive:true,force:true}); }
});

test('public export: every page type and section; private files, links and citations left out', async () => {
  const tmp=await fs.mkdtemp(path.join(os.tmpdir(),'study-public-'));
  try {
    const repo=path.join(tmp,'repo');await fs.cp(fixture,repo,{recursive:true});
    const page='wiki/tema.md';
    await fs.writeFile(path.join(repo,page),'---\ntype: lesson-notes\ntitle: Órai jegyzet\nprivate: PRIVATE_METADATA\n---\n# Órai jegyzet\n\nMegmarad.[^b]\n\n<sub>🗓️ Óra: 2026-09-25 · 🔖 Tankönyv: 12. oldal</sub>\n\n[Fotó](../sources/fuzet/p0001.jpg) és [könyv](../references/konyv/document.md)\n\n# Nyitott kérdések\n\nEgy bizonytalan szó.\n\n[^b]: Füzet, 01.jpg.\n\n<!-- PRIVATE_COMMENT -->\n');
    const config=await settings();Object.assign(config,{mode:'public',site:'https://example.org',sourceNote:'A jegyzet Minta füzetbe írt jegyzetei alapján készült.',citationOnlyLinks:['sources/fuzet/p0001.jpg','references/konyv/document.md']});
    config.pages[1].sha256=sha256(await fs.readFile(path.join(repo,page)));
    config.assets=config.assets.map(a=>({...a,rights:'authored'}));
    config.collections[0].pdf=true;
    const run=(name,c=config,extra={})=>exportSite({repo,config:c,output:path.join(tmp,name),printEngine:'test',...extra});
    const {payload}=await run('good',config,{lastUpdated:{[page]:'2026-10-03T10:00:00+02:00'}});
    const visible=JSON.stringify([...payload.pages,...payload.collections.map(c=>c.chapters)]);
    assert.doesNotMatch(visible,/PRIVATE_|sources\/fuzet|references\/konyv/);
    for (const kept of [/Nyitott kérdések/,/Egy bizonytalan szó/,/Óra: 2026-09-25/,/Tankönyv: 12/,/Megmarad\./,/Fotó és könyv/]) assert.match(visible,kept);
    // The notebook footnote cites a private source: left out with its reference.
    assert.doesNotMatch(visible,/Füzet, 01\.jpg|nem nyilvános forrás|footnote/);
    assert.equal(payload.sourceNote,'A jegyzet Minta füzetbe írt jegyzetei alapján készült.');
    for (const [i,bad] of ['', ' ', 'x'.repeat(301), 7].entries()) await assert.rejects(run('note'+i,{...config,sourceNote:bad}),/source note/);
    const {payload:noNote}=await run('nonote',{...config,sourceNote:undefined});
    assert.equal(noNote.sourceNote,undefined);
    assert.notEqual(noNote.collections[0].pdf.key,payload.collections[0].pdf.key);
    assert.equal(payload.pages[1].lastUpdated,'2026-10-03T10:00:00+02:00');assert.equal(payload.pages[1].path,page);
    assert.equal(payload.pages[0].lastUpdated,undefined);
    await assert.rejects(run('rights',{...config,assets:[{...config.assets[0],rights:undefined}]}),/rights class/);
    await assert.rejects(run('omit',{...config,pages:[config.pages[0],{...config.pages[1],omitSections:['Nyitott kérdések']}]}),/omitSections is no longer supported/);
    await assert.rejects(run('edit',{...config,pages:[config.pages[0],{...config.pages[1],publicEdits:[{before:'a',after:'b',reason:'c'}]}]}),/publicEdits is no longer supported/);
    await assert.rejects(run('date',config,{lastUpdated:{[page]:'not a date'}}),/Invalid last-updated/);
    await fs.appendFile(path.join(repo,page),'\n[Bizonyíték](../docs/evidence/x.md)\n');
    config.pages[1].sha256=sha256(await fs.readFile(path.join(repo,page)));
    await assert.rejects(run('unknown'),error=>error.page===page && /Unapproved link/.test(error.message));
  } finally {await fs.rm(tmp,{recursive:true,force:true});}
});


test('a title following its opening banner is deduplicated, later section titles remain', async () => {
  const source = '---\ntitle: Lesson\n---\n![Banner](image.svg)\n\n<!-- provenance -->\n\n# Lesson\n\nIntroduction.\n\n# Lesson\n\nSection.';
  const r = await renderMarkdown(source, { resolveUrl });
  assert.equal((r.html.match(/<h2/g) || []).length, 1);
  assert.match(r.html, /class="heading-alias"/);
  assert.match(r.html, /Introduction/);
});

test('rendering is deterministic when assets resolve in a different order', async () => {
  const source = '# Kép\n\n![A](a.svg)\n\n![B](b.svg)\n\n![C](c.svg)\n';
  const delayed = order => async (url) => { await new Promise(r => setTimeout(r, order[url] || 0)); return '/m/' + url; };
  const first = await renderMarkdown(source, { resolveUrl: delayed({ 'a.svg': 30, 'b.svg': 0, 'c.svg': 10 }) });
  const second = await renderMarkdown(source, { resolveUrl: delayed({ 'a.svg': 0, 'b.svg': 30, 'c.svg': 20 }) });
  assert.equal(first.html, second.html);
  assert.match(first.html, /src="\/m\/a\.svg"[^>]*loading="eager"/);
  assert.deepEqual(first.audit.images, ['/m/a.svg', '/m/b.svg', '/m/c.svg']);
});
test('an animation exports its mp4 and its PNG poster as two media files', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'study-anim-'));
  try {
    const repo = path.join(tmp, 'repo');
    await fs.cp(fixture, repo, { recursive: true });
    await fs.mkdir(path.join(repo, 'wiki/assets/inga'), { recursive: true });
    const video = Buffer.from('\0\0\0\x18ftypisom-not-a-real-video');
    const poster = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==', 'base64');
    await fs.writeFile(path.join(repo, 'wiki/assets/inga/figure.mp4'), video);
    await fs.writeFile(path.join(repo, 'wiki/assets/inga/figure.png'), poster);
    await fs.writeFile(path.join(repo, 'wiki/anim.md'), '# Inga\n\n![Az inga mozgása](assets/inga/figure.mp4)\n');
    const config = await settings();
    config.pages.push({ path: 'wiki/anim.md', sha256: sha256(await fs.readFile(path.join(repo, 'wiki/anim.md'))) });
    config.assets.push({ path: 'wiki/assets/inga/figure.mp4', sha256: sha256(video) }, { path: 'wiki/assets/inga/figure.png', sha256: sha256(poster) });
    config.collections[0].pages.push('wiki/anim.md');
    const { payload, receipt } = await exportSite({ repo, config, output: path.join(tmp, 'build') });
    const html = payload.pages.find(p => p.html.includes('study-video')).html;
    assert.match(html, new RegExp(`<video [^>]*poster="/pelda/media/${sha256(poster)}\\.png" src="/pelda/media/${sha256(video)}\\.mp4"`));
    const inputs = receipt.assets.map(a => a.input);
    assert.deepEqual(inputs, [...inputs].sort());
    assert.ok(inputs.includes('wiki/assets/inga/figure.mp4') && inputs.includes('wiki/assets/inga/figure.png'));
    assert.deepEqual(await fs.readFile(path.join(tmp, 'build/public/media', `${sha256(video)}.mp4`)), video);
  } finally { await fs.rm(tmp, { recursive: true, force: true }); }
});
test('a podcast episode exports its mp3 in the public mode, and the Podcast page is a menu item after the home page', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'study-podcast-'));
  try {
    const repo = path.join(tmp, 'repo');
    await fs.cp(fixture, repo, { recursive: true });
    await fs.mkdir(path.join(repo, 'wiki/assets/proba/podcast'), { recursive: true });
    const audio = Buffer.from('ID3\x03\0\0\0\0\0\0not-a-real-mp3');
    await fs.writeFile(path.join(repo, 'wiki/assets/proba/podcast/elso.mp3'), audio);
    await fs.writeFile(path.join(repo, 'wiki/podcast.md'), '---\ntitle: Podcast\n---\n\n# Podcast\n\n## Az első téma\n\n![Képben vagy? – Az első téma](assets/proba/podcast/elso.mp3)\n');
    const config = await settings();
    config.mode = 'public'; config.site = 'https://example.github.io';
    config.pages.splice(1, 0, { path: 'wiki/podcast.md', sha256: sha256(await fs.readFile(path.join(repo, 'wiki/podcast.md'))), navigationLabel: '🎧 Podcast', navigation: 'info' });
    config.assets = config.assets.map(a => ({ ...a, rights: 'authored' }));
    config.assets.push({ path: 'wiki/assets/proba/podcast/elso.mp3', sha256: sha256(audio), rights: 'generated' });
    const { payload } = await exportSite({ repo, config, output: path.join(tmp, 'build') });
    const page = payload.pages.find(p => p.path === 'wiki/podcast.md');
    assert.equal(payload.pages.indexOf(page), 1);
    assert.equal(page.navigation, 'info');
    assert.equal(page.navigationLabel, '🎧 Podcast');
    assert.match(page.html, new RegExp(`<audio controls preload="none" src="/pelda/media/${sha256(audio)}\\.mp3"`));
    assert.deepEqual(await fs.readFile(path.join(tmp, 'build/public/media', `${sha256(audio)}.mp3`)), audio);
  } finally { await fs.rm(tmp, { recursive: true, force: true }); }
});
test('a public mp3 without a rights class is refused', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'study-podcast-'));
  try {
    const config = await settings();
    config.mode = 'public'; config.site = 'https://example.github.io';
    config.assets = [{ path: 'wiki/assets/proba/podcast/elso.mp3', sha256: 'a'.repeat(64) }];
    await assert.rejects(exportSite({ repo: fixture, config, output: path.join(tmp, 'build') }), /Asset rights class required/);
  } finally { await fs.rm(tmp, { recursive: true, force: true }); }
});
