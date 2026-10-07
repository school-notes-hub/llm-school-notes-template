import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import GithubSlugger from 'github-slugger';
const require = createRequire(import.meta.url);
const MarkdownIt = require('markdown-it');
const footnote = require('markdown-it-footnote');
const taskLists = require('markdown-it-task-lists');
const sanitize = require('sanitize-html');
const {mathjax} = require('mathjax-full/js/mathjax.js');
const {TeX} = require('mathjax-full/js/input/tex.js');
const {SVG} = require('mathjax-full/js/output/svg.js');
const {liteAdaptor} = require('mathjax-full/js/adaptors/liteAdaptor.js');
const {RegisterHTMLHandler} = require('mathjax-full/js/handlers/html.js');
const {AllPackages} = require('mathjax-full/js/input/tex/AllPackages.js');
const adaptor = liteAdaptor(); RegisterHTMLHandler(adaptor);
export const digest = data => crypto.createHash('sha256').update(data).digest('hex');
export const escape = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
export const stripFrontmatter = s => s.replace(/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/,'');
export const inside = (root,p) => p===root || p.startsWith(root+path.sep);
const safeHtml = html => sanitize(html, {
  allowedTags: [...sanitize.defaults.allowedTags, 'details','summary','sub','sup','img','br','input'],
  allowedAttributes: {'*':['id','class'], a:['href','title'], img:['src','alt','title','width','height'], span:['title'],
    details:['open'], input:['type','checked','disabled'], th:['colspan','rowspan'],td:['colspan','rowspan']},
  allowedSchemes: ['http','https','mailto'], allowProtocolRelative:false,
});
function mathPlugin(md) {
  md.inline.ruler.before('escape','math_inline',(state,silent)=>{
    if(state.src[state.pos]!=='$' || state.src[state.pos+1]==='$') return false;
    let end=state.pos+1;
    while((end=state.src.indexOf('$',end))>=0 && state.src[end-1]==='\\') end++;
    if(end<0) return false;
    const content=state.src.slice(state.pos+1,end);
    if(!content || /^\s|\s$/.test(content)) return false;
    if(!silent) {const t=state.push('math_inline','',0);t.content=content;}
    state.pos=end+1; return true;
  });
  md.block.ruler.before('fence','math_block',(state,start,end,silent)=>{
    const first=state.src.slice(state.bMarks[start]+state.tShift[start],state.eMarks[start]).trim();
    if(!first.startsWith('$$')) return false;
    let content=first.slice(2), next=start+1;
    if(content.endsWith('$$')) content=content.slice(0,-2);
    else {
      let closed=false;
      for(;next<end;next++) {
        const line=state.src.slice(state.bMarks[next]+state.tShift[next],state.eMarks[next]);
        if(line.trimEnd().endsWith('$$')) {content+='\n'+line.trimEnd().slice(0,-2);next++;closed=true;break;}
        content+='\n'+line;
      }
      if(!closed){if(silent)return true;const t=state.push('math_unclosed','',0);t.content=content;t.block=true;state.line=end;return true;}
    }
    if(silent) return true;
    const t=state.push('math_block','',0);t.block=true;t.content=content;t.map=[start,next];state.line=next;return true;
  },{alt:['paragraph','reference','blockquote','list']});
}
function walk(tokens,fn){for(const token of tokens){fn(token);if(token.children)walk(token.children,fn);}}
export function renderMarkdown(source) {
  const math = mathjax.document('', {InputJax: new TeX({packages: AllPackages.filter(p=>!['noerrors','noundefined','html','require','autoload'].includes(p))}), OutputJax: new SVG({fontCache:'none'})});
  const errors=[], assets=[], links=[], slugger=new GithubSlugger(); let mathCount=0, mermaidCount=0;
  const md=new MarkdownIt({html:true,linkify:false,typographer:false}).use(footnote).use(taskLists).use(mathPlugin);
  // markdown-it joins escaped characters (`text_special`) only at the top level, and an image's alt
  // text drops the nested ones: `![\]-1; 3\]](a.svg)` would lose its interval brackets.
  md.core.ruler.after('text_join','nested_text_join',state=>walk(state.tokens,t=>{if(t.type==='text_special')t.type='text';}));
  // Sanitize the complete output before injecting our trusted MathJax markup.
  const formulas=[];
  const formula=(content,display)=>{
    mathCount++;
    try {
      const svg=adaptor.outerHTML(math.convert(content,{display}));
      if(svg.includes('data-mjx-error')) errors.push({kind:'math',formula:content});
      const token=`MATHPLACEHOLDER${crypto.randomUUID().replaceAll('-','')}END`;
      formulas.push([token,svg]); return token;
    } catch {errors.push({kind:'math',formula:content});return '<code>Math rendering failed</code>';}
  };
  md.renderer.rules.math_unclosed=(ts,i)=>{errors.push({kind:'unclosed-display-math'});return '<pre>'+escape('$$'+ts[i].content)+'</pre>';};
  md.renderer.rules.math_inline=(ts,i)=>formula(ts[i].content,false);
  md.renderer.rules.math_block=(ts,i)=>'<div class="math-display">'+formula(ts[i].content,true)+'</div>\n';
  const originalFence=md.renderer.rules.fence;
  md.renderer.rules.fence=(ts,i,opts,env,self)=>{
    const lang=ts[i].info.trim();
    if(lang==='mermaid'){mermaidCount++;return '<pre class="mermaid">'+escape(ts[i].content)+'</pre>\n';}
    if(lang==='math') return '<div class="math-display">'+formula(ts[i].content,true)+'</div>\n';
    return originalFence(ts,i,opts,env,self);
  };
  const env={};const tokens=md.parse(stripFrontmatter(source),env);
  for(let i=0;i<tokens.length;i++) if(tokens[i].type==='heading_open') {
    const inline=tokens[i+1];const text=(inline.children||[]).filter(t=>['text','code_inline','math_inline'].includes(t.type)).map(t=>t.content).join('');
    tokens[i].attrSet('id',slugger.slug(text));
  }
  walk(tokens,t=>{
    if(t.type==='image')assets.push(t.attrGet('src'));
    if(t.type==='link_open')links.push(t.attrGet('href'));
  });
  let html=safeHtml(md.renderer.render(tokens,md.options,env));
  // A lesson date item (as on the study site): focusable when it has a tooltip and is not inside a link,
  // its `~` a span of its own and "körülbelül" for a screen reader.
  html=html.replace(/(<a\b[^>]*>)?<span class="study-when( study-when-unsure)?" title="([^"]*)">(~?)/g,(_,a,u,t,tilde)=>
    `${a||''}<span class="study-when${u||''}" title="${t}"${a?'':' tabindex="0"'}>${tilde?'<span class="study-tilde" aria-hidden="true">~</span><span class="study-sr">körülbelül </span>':''}`);
  for(const [token,svg] of formulas)html=html.replace(token,()=>svg);
  html=html.replace(/<blockquote>\s*<p>\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\](?:\n|<br\s*\/?>\n?)/g,(_,kind)=>
    `<blockquote class="markdown-alert markdown-alert-${kind.toLowerCase()}"><p class="markdown-alert-title">${kind[0]+kind.slice(1).toLowerCase()}</p><p>`);
  return {html,errors,assets,links,mathCount,mermaidCount};
}
export function resolveLocal(root,page,uri) {
  if(!uri || /^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(uri)) return null;
  const [file,fragment] = uri.split('#');
  let decoded,anchor;try{decoded=decodeURIComponent(file.split('?')[0]);anchor=fragment ? decodeURIComponent(fragment) : '';}catch{return {error:'invalid-url',uri};}
  const target=decoded ? path.resolve(path.dirname(page),decoded) : page;
  if(!inside(root,target))return {error:'path-outside-repository',uri};
  return {target,fragment:anchor};
}
export function inspectPage(root,file) {
  root=fs.realpathSync(root);file=path.resolve(file);
  if(!inside(root,file)||!inside(root,fs.realpathSync(file)))throw Error('Page outside repository');
  const source=fs.readFileSync(file,'utf8');const rendered=renderMarkdown(source);
  const errors=[...rendered.errors],warnings=[],deps=new Map([[file,digest(source)]]);
  const imageFiles=new Map();
  // Include raw HTML links/images as well as Markdown tokens and hidden evidence paths.
  const htmlAssets=[...rendered.html.matchAll(/<img\b[^>]*\bsrc="([^"]+)"/g)].map(x=>x[1].replaceAll('&amp;','&'));
  const htmlLinks=[...rendered.html.matchAll(/<a\b[^>]*\bhref="([^"]+)"/g)].map(x=>x[1].replaceAll('&amp;','&'));
  for(const uri of new Set([...rendered.links,...rendered.assets,...htmlAssets,...htmlLinks])) {
    const image=rendered.assets.includes(uri)||htmlAssets.includes(uri);
    const resolved=resolveLocal(root,file,uri);
    if(!resolved){if(image)errors.push({kind:'external-image-not-checked',uri});continue;}
    if(resolved.error){errors.push({kind:resolved.error,uri});continue;}
    const {target,fragment}=resolved;
    if(!fs.existsSync(target)){deps.set(target,'missing');errors.push({kind:'missing-link',uri});continue;}
    if(!inside(root,fs.realpathSync(target))){errors.push({kind:'symlink-outside-repository',uri});continue;}
    if(fs.statSync(target).isDirectory())continue;
    const bytes=fs.readFileSync(target);deps.set(target,digest(bytes));
    if(image){
      if(!inside(root,fs.realpathSync(target)))errors.push({kind:'image-symlink-outside-repository',uri});
      else imageFiles.set(uri,target);
    }
    if(fragment && path.extname(target)==='.md'){
      const targetHtml=target===file?rendered.html:renderMarkdown(bytes.toString()).html;
      const ids=new Set([...targetHtml.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]));
      if(!ids.has(fragment))errors.push({kind:'missing-anchor',uri});
    }
  }
  for(const block of source.matchAll(/<!--\s*image-description([\s\S]*?)-->/g)){
    const asset=block[1].match(/^asset:\s*(.+)$/m)?.[1]?.trim();const expected=block[1].match(/^sha256:\s*([a-f\d]{64})\s*$/m)?.[1];
    if(!asset || !expected) {warnings.push({kind:'incomplete-image-description'});continue;}
    if(/^(?:https?:|drive:)/.test(asset)){warnings.push({kind:'external-image-evidence-not-checked'});continue;}
    const target=asset.startsWith('wiki/')?path.resolve(root,asset):path.resolve(path.dirname(file),asset);
    if(!inside(root,target)||!fs.existsSync(target)||!inside(root,fs.realpathSync(target))){errors.push({kind:'missing-evidence-image',asset});deps.set(target,'missing');continue;}
    const actual=digest(fs.readFileSync(target));deps.set(target,actual);
    if(actual!==expected)errors.push({kind:'image-description-hash',asset});
  }
  // No network requests or semantic claims: this only records current local dependencies.
  return {...rendered,errors,warnings,source,dependencies:[...deps].map(([p,sha256])=>({path:path.relative(root,p),sha256})),imageFiles};
}
