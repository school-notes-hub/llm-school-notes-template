import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {renderMarkdown,inspectPage,resolveLocal} from './core.mjs';
const root=fs.mkdtempSync(path.join(os.tmpdir(),'school-page-test-'));
fs.mkdirSync(path.join(root,'wiki'));
const file=path.join(root,'wiki/page.md');
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII=','base64');
const content='# Test\n\n> [!TIP]\n> Explanation.\n\nInline $F=ma$.\n\n$$\nx^2+1\n$$\n\n```mermaid\ngraph TD\n A["Start"] --> B["End"]\n```\n\n![local](image.png)\n\n<details><summary>Question</summary>\n\n<dl><dd>\n\n<br />\n\nAnswer.[^x]\n\n<br /><br />\n\n</dd></dl>\n\n</details>\n\n[^x]: Source.\n';
fs.writeFileSync(file,content);fs.writeFileSync(path.join(root,'wiki/image.png'),png);
test.after(()=>fs.rmSync(root,{recursive:true,force:true}));
test('math, alerts, details and footnotes survive; executable HTML does not',()=>{
 const r=renderMarkdown(content+'\n<script>alert(1)</script><img src="x" onerror="alert(2)">');
 assert.equal(r.mathCount,2);assert.equal(r.mermaidCount,1);assert.deepEqual(r.errors,[]);
 for(const marker of ['markdown-alert-tip','<details>','<dd>','footnote','<svg'])assert.ok(r.html.includes(marker),marker);
 assert.ok(!r.html.includes('<script'));assert.ok(!r.html.includes('onerror'));
});
test('links, malformed escapes, invalid math and evidence hashes are checked',()=>{
 assert.equal(resolveLocal(root,file,'#%xx').error,'invalid-url');
 assert.ok(renderMarkdown('$$\nx^2+1\n').errors.some(e=>e.kind==='unclosed-display-math'));
 assert.equal(resolveLocal(root,file,'../../outside').error,'path-outside-repository');
 const r=renderMarkdown('$\\thisCommandDoesNotExist$');assert.ok(r.errors.some(e=>e.kind==='math'));
 fs.writeFileSync(file,content+'\n[missing](no.md)\n[bad anchor](page.md#missing)\n');
 const check=inspectPage(root,file);assert.ok(check.errors.some(e=>e.kind==='missing-link'));assert.ok(check.errors.some(e=>e.kind==='missing-anchor'));
 fs.writeFileSync(file,content+'\n<!-- image-description\nasset: image.png\nsha256: '+ '0'.repeat(64)+'\n-->\n');
 assert.ok(inspectPage(root,file).errors.some(e=>e.kind==='image-description-hash'));
 fs.writeFileSync(file,content);
});
test('TeX macros do not leak across pages',()=>{
 renderMarkdown('$\\newcommand{\\foo}{x}\\foo$');
 assert.ok(renderMarkdown('$\\foo$').errors.some(e=>e.kind==='math'));
});

test('linked symlinks outside checkout are rejected before reading bytes',()=>{
 fs.symlinkSync('/etc/hosts',path.join(root,'wiki/escape.md'));
 fs.writeFileSync(file,content+'\n[unsafe](escape.md)\n');
 assert.ok(inspectPage(root,file).errors.some(e=>e.kind==='symlink-outside-repository'));
 fs.writeFileSync(file,content);
});
test('browser: disclosure states, cold/warm cache, changed asset and broken Mermaid', {skip:!process.env.PAGE_CHECK_BROWSER},()=>{
 const cli=path.resolve('tools/page_check.mjs');
 const args=[cli,'--repo',root,'--pages','wiki/page.md','--browser',process.env.PAGE_CHECK_BROWSER];
 const run=()=>{try{return {status:0,out:execFileSync(process.execPath,args,{encoding:'utf8'})};}catch(e){return {status:e.status,out:String(e.stdout)}}};
 fs.mkdirSync(path.join(root,'.visual-runs'),{recursive:true});
 fs.symlinkSync(path.join(root,'wiki'),path.join(root,'.visual-runs/page-check'));
 assert.equal(run().status,2);
 fs.unlinkSync(path.join(root,'.visual-runs/page-check'));
 let r=run();assert.equal(r.status,0,r.out);
 let report=JSON.parse(fs.readFileSync(path.join(root,'.visual-runs/page-check/report.json')));
 assert.equal(report.pages[0].views.length,4);assert.equal(report.pages[0].semantic_review,'not-performed');
 assert.equal(report.pages[0].views[0].details,1);
 r=run();assert.equal(r.status,0,r.out);assert.equal(JSON.parse(r.out).reused,1);
 fs.writeFileSync(path.join(root,'wiki/image.png'),Buffer.concat([png,Buffer.from('changed')]));
 r=run();assert.equal(r.status,0,r.out);assert.equal(JSON.parse(r.out).reused,0);
 fs.writeFileSync(file,content.replace('graph TD','invalid diagram syntax'));
 r=run();assert.equal(r.status,1,r.out);
 report=JSON.parse(fs.readFileSync(path.join(root,'.visual-runs/page-check/report.json')));
 assert.ok(report.errors.some(e=>['mermaid','browser'].includes(e.kind)));
});
test('escaped interval brackets stay in the alt text and are never math',()=>{
 const r=renderMarkdown('![A = \\]-2; 5\\] és \\[0; 5\\[](a.svg)\n');
 assert.ok(r.html.includes('alt="A = ]-2; 5] és [0; 5["'),r.html);
 assert.equal(r.mathCount,0);assert.ok(!r.html.includes('math-display'));
});
test('a lesson date is a quiet meta item with its tooltip, reachable by tap (sn 0.3.8, 0.3.9)',()=>{
 const r=renderMarkdown('* [x](a.md) <span class="study-when study-when-unsure" title="Dátum nélküli óra: szept. 23. – okt. 4.">~szept. vége</span>\n');
 assert.ok(r.html.includes('<span class="study-when study-when-unsure" title="Dátum nélküli óra: szept. 23. – okt. 4." tabindex="0"><span class="study-tilde" aria-hidden="true">~</span>szept. vége</span>'),r.html);
 const css=fs.readFileSync(new URL('./style.css',import.meta.url),'utf8');
 assert.match(css,/\.study-when::before \{[^}]*mask:/);
 assert.match(css,/\.study-when\[title\]:focus::after \{ content:attr\(title\)/);
 assert.match(css,/@media print[^\n]*\.study-tilde, \.markdown-body \.study-when\[title\]:focus::after \{ display:none; \}/);
});
