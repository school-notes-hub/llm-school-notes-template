import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import remarkRehype from 'remark-rehype';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize';
import rehypeStringify from 'rehype-stringify';
import rehypeMathjax from 'rehype-mathjax/svg';
import { visit, SKIP } from 'unist-util-visit';
import { toText } from 'hast-util-to-text';
import GithubSlugger from 'github-slugger';
import { parse as parseYaml } from 'yaml';

export function splitMarkdown(source) {
  const match = source.match(/^\uFEFF?---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/);
  const metadata = match ? parseYaml(match[1], { maxAliasCount: 0 }) : {};
  const body = match ? source.slice(match[0].length) : source;
  const ast = unified().use(remarkParse).parse(body);
  const firstHeading = ast.children.find(n => n.type === 'heading');
  const headingText = firstHeading?.children?.map(n => n.value || '').join('');
  return { metadata: metadata || {}, body, title: String(metadata?.title || headingText || 'Jegyzet') };
}

const schema = structuredClone(defaultSchema);
schema.tagNames.push('sub', 'sup', 'dl', 'dd', 'dt');
schema.attributes.code = [...(schema.attributes.code || []), ['className', /^language-/, 'math-inline', 'math-display']];
schema.attributes.div = [...(schema.attributes.div || []), ['className', 'math', 'math-display']];
schema.attributes.span = [...(schema.attributes.span || []), ['className', 'math', 'math-inline']];
schema.attributes.details = ['open'];
schema.attributes.p = [...(schema.attributes.p || []), ['className', 'study-pending']];
// The input never supplies executable HTML, CSS, embeds or arbitrary IDs/classes.
// Footnote IDs are prefixed by rehype-sanitize, including their references.

const el = (tagName, properties = {}, children = []) => ({ type: 'element', tagName, properties, children });
const isElement = (n, tag) => n.type === 'element' && (!tag || n.tagName === tag);
// An empty anchor with a plain lower-case id and nothing else (the wiki's section jump targets).
// Lower-case includes accented letters: a Hungarian heading slug keeps them ("a-földművelés").
const isJumpTarget = n => isElement(n, 'a') && !n.properties.href && !n.children.length
  && /^(?:user-content-)?[\p{Ll}\p{Nd}][\p{Ll}\p{Nd}-]{0,200}$/u.test(String(n.properties.id || ''));

// The public view leaves out what a reader cannot open: a footnote with no public web link
// cites the notebook, teacher material or a textbook, all private. A chapter title's grade
// prefix ("9. évfolyam: ") is dropped too: one repository holds one school year.
const WEB_URL = /^https?:\/\//i;
const GRADE_PREFIX = /^(\P{L}*?)\d{1,2}\. évfolyam: /u;
export const withoutGrade = text => text.replace(GRADE_PREFIX, '$1').trim() ? text.replace(GRADE_PREFIX, '$1') : text;

function publicMarkdown(tree) {
  const urls = new Map();
  visit(tree, 'definition', node => { urls.set(node.identifier, node.url); });
  // A web link written inline, as a reference ([text][id]) or as raw HTML.
  const hasWebLink = n => (n.type === 'link' && WEB_URL.test(n.url))
    || (n.type === 'linkReference' && WEB_URL.test(urls.get(n.identifier) || ''))
    || (n.type === 'html' && /href\s*=\s*["']?https?:\/\//i.test(n.value))
    || (n.children || []).some(hasWebLink);
  const dropped = new Set();
  visit(tree, 'footnoteDefinition', (node, index, parent) => {
    if (hasWebLink(node)) return;
    dropped.add(node.identifier);
    parent.children.splice(index, 1);
    return index;
  });
  visit(tree, 'footnoteReference', (node, index, parent) => {
    if (!dropped.has(node.identifier)) return;
    parent.children.splice(index, 1);
    return index;
  });
  visit(tree, 'heading', node => {
    const first = node.children[0];
    if (first?.type === 'text') first.value = withoutGrade(first.value);
  });
}

const blank = n => (n.type === 'text' && !n.value.trim()) || isElement(n, 'br')
  || (isElement(n, 'p') && n.properties.className?.includes('study-spacer'));
const isPrivateMark = n => isElement(n, 'span') && n.properties.dataPrivateLink !== undefined;
const isHeading = n => isElement(n) && /^h[1-6]$/.test(n.tagName);
const isFootnotes = n => isElement(n, 'section') && n.properties.dataFootnotes !== undefined;

function emptyHeadings(tree) {
  // A heading with nothing but spacing before the next heading of the same or higher rank.
  const found = new Set();
  visit(tree, (node) => {
    if (isFootnotes(node)) return SKIP;
    const kids = node.children || [];
    kids.forEach((h, i) => {
      if (!isHeading(h)) return;
      const level = Number(h.tagName[1]);
      for (let j = i + 1; j < kids.length; j++) {
        if (isHeading(kids[j]) && Number(kids[j].tagName[1]) <= level) break;
        if (!blank(kids[j])) return;
      }
      found.add(h);
    });
  });
  return found;
}

// Private links in the public view: a list item that starts with one (a photo list of a
// lesson page) is left out, then an emptied list and a section heading it emptied; a link in
// running text keeps its words as plain text, so the sentence stays whole.
function tidyPrivateLinks(tree) {
  const before = emptyHeadings(tree);
  const leadsWithPrivate = li => {
    let kids = li.children.filter(c => !blank(c));
    if (isElement(kids[0], 'p')) kids = kids[0].children.filter(c => !blank(c));
    return kids.length > 0 && isPrivateMark(kids[0]);
  };
  // The footnote list is the renderer's own; its items are kept or dropped by fixFootnotes.
  visit(tree, 'element', (node, index, parent) => {
    if (isFootnotes(node)) return SKIP;
    if (!isElement(node, 'li') || !leadsWithPrivate(node)) return;
    parent.children.splice(index, 1);
    return index;
  });
  visit(tree, 'element', (node, index, parent) => {
    if (isFootnotes(node)) return SKIP;
    if (!['ul', 'ol'].includes(node.tagName) || node.children.some(c => isElement(c, 'li'))) return;
    parent.children.splice(index, 1);
    return index;
  });
  // Repeat: removing emptied sub-headings can empty their parent heading's section.
  for (;;) {
    const emptied = [...emptyHeadings(tree)].filter(h => !before.has(h));
    if (!emptied.length) break;
    for (const h of emptied) {
      visit(tree, (node) => {
        const i = (node.children || []).indexOf(h);
        if (i >= 0) node.children.splice(i, 1);
      });
    }
  }
  visit(tree, 'element', (node, index, parent) => {
    if (!isPrivateMark(node)) return;
    parent.children.splice(index, 1, ...node.children);
    return index;
  });
  fixFootnotes(tree);
}

// After items or headings were dropped: a footnote no reference points to any more goes, a
// back-reference to a dropped reference goes, and the references are numbered again.
function fixFootnotes(tree) {
  const refs = [];
  visit(tree, 'element', node => { if (isElement(node, 'a') && node.properties.dataFootnoteRef !== undefined) refs.push(node); });
  const target = a => String(a.properties.href || '').slice(1);
  const refIds = new Set(refs.map(r => String(r.properties.id)));
  const used = new Set(refs.map(target));
  visit(tree, 'element', (section, index, parent) => {
    if (!isFootnotes(section)) return;
    const ol = section.children.find(c => isElement(c, 'ol'));
    if (ol) {
      visit(ol, 'element', (node, i, p) => {
        if (!isElement(node, 'a') || node.properties.dataFootnoteBackref === undefined || refIds.has(target(node))) return;
        p.children.splice(i, 1);
        return i;
      });
      ol.children = ol.children.filter(li => !isElement(li, 'li') || used.has(String(li.properties.id)));
    }
    if (!ol || !ol.children.some(c => isElement(c, 'li'))) { parent.children.splice(index, 1); return index; }
    return SKIP;
  });
  const numbers = new Map();
  for (const r of refs) {
    if (!numbers.has(target(r))) numbers.set(target(r), numbers.size + 1);
    r.children = [{ type: 'text', value: String(numbers.get(target(r))) }];
  }
}

function generatedNotices(tree) {
  // Only the tool's Markdown markers designate export-excluded notices.
  visit(tree, node => {
    if (!node.children) return;
    const stack = [];
    for (const child of node.children) {
      const open = child.type === 'html' && child.value.trim().match(/^<!-- school-notes:generated ([a-z0-9-]+) -->$/);
      if (open) stack.push(open[1]);
      else if (child.type === 'html' && child.value.trim() === '<!-- /school-notes:generated -->') stack.pop();
      else if (child.type === 'paragraph' && stack.some(name => /^pending(?:$|-section-|-figure-)/.test(name))) {
        child.data = { ...child.data, hProperties: { ...child.data?.hProperties, className: ['study-pending'] } };
      }
    }
  });
}

export async function renderMarkdown(source, { resolveUrl, mermaid, pageId = '', footnoteLabel = 'Források', publicView = false } = {}) {
  const split = splitMarkdown(source);
  const { metadata, body } = split;
  const title = publicView ? withoutGrade(split.title) : split.title;
  const headings = [];
  const sanitizedIds = new Map();
  const audit = { title, formulas: [], mermaid: [], labels: [], links: [], images: [] };
  const processor = unified().use(remarkParse).use(remarkGfm).use(remarkMath)
    .use(() => tree => { generatedNotices(tree); if (publicView) publicMarkdown(tree); })
    // The footnote list gets a visible heading (no sr-only class), so it never reads as part of
    // the section above it.
    .use(remarkRehype, { allowDangerousHtml: true, footnoteLabel, footnoteLabelProperties: {} })
    .use(rehypeRaw)
    .use(() => tree => {
      // Markdown inside an HTML summary is raw text; recover its inline formulas.
      visit(tree, 'element', node => {
        if (node.tagName !== 'summary') return;
        visit(node, 'text', (text,index,parent) => {
          const matches=[...text.value.matchAll(/(?<!\\)\$([^$\n]+)\$/g)];
          if(!matches.length) return;
          const children=[];let offset=0;
          for(const match of matches){
            children.push({type:'text',value:text.value.slice(offset,match.index)});
            children.push(el('code',{className:['language-math','math-inline']},[{type:'text',value:match[1]}]));
            offset=match.index+match[0].length;
          }
          children.push({type:'text',value:text.value.slice(offset)});
          parent.children.splice(index,1,...children);
          return index+children.length;
        });
      });
    })
    .use(() => tree => {
      visit(tree, 'element', node => {
        if (node.properties.id && !isJumpTarget(node)) sanitizedIds.set(node.properties.id, 'user-content-' + node.properties.id);
      });
    })
    .use(rehypeSanitize, schema)
    .use(() => tree => {
      // An empty `<a id="pdf-13-oldal"></a>` is a jump target that other pages link to
      // (`page#pdf-13-oldal`); it keeps its plain id so those links resolve.
      visit(tree, 'element', node => {
        const id = String(node.properties.id || '');
        if (isJumpTarget(node) && id.startsWith('user-content-')) node.properties.id = id.slice(13);
      });
    })
    .use(() => async tree => {
      const slugger = new GithubSlugger();
      let seenBody = false;
      // Remove only a leading heading repeating the page title. Keep its fragment.
      for (let i = 0; i < tree.children.length; i++) {
        const n = tree.children[i];
        if (!isElement(n)) continue;
        // A leading banner does not make the following repeated page title body content.
        if (!seenBody && isElement(n, 'p') && n.children.some(c => isElement(c, 'img')) && !toText(n).trim()) continue;
        if (/^h[1-6]$/.test(n.tagName) && !seenBody && toText(n) === title) {
          tree.children[i] = el('span', { id: slugger.slug(toText(n)), className: ['heading-alias'] });
        } else { seenBody = true; }
      }
      const jobs = [];
      let imageCount = 0;
      visit(tree, 'element', (node, index, parent) => {
        const text = toText(node);
        for (const prop of ['ariaDescribedBy', 'ariaLabelledBy']) {
          if (Array.isArray(node.properties[prop])) node.properties[prop] = node.properties[prop].map(id => sanitizedIds.get(id) || id);
        }
        if (/^h[1-6]$/.test(node.tagName) && node.properties.id !== 'user-content-footnote-label') {
          const depth = Math.min(6, Number(node.tagName[1]) + 1);
          node.tagName = `h${depth}`;
          node.properties.id = slugger.slug(text);
          headings.push({ depth, slug: node.properties.id, text });
        }
        if (node.tagName === 'blockquote') {
          const p = node.children.find(n => isElement(n, 'p'));
          const first = p?.children[0];
          const match = first?.type === 'text' && first.value.match(/^\[!(TIP|NOTE|WARNING|IMPORTANT|CAUTION)\](?:\s|$)/);
          if (match) {
            first.value = first.value.slice(match[0].length);
            if (!toText(p).trim()) node.children.splice(node.children.indexOf(p), 1);
            node.tagName = 'aside';
            node.properties = { className: ['study-callout', `study-${match[1].toLowerCase()}`], 'aria-label': ({ TIP: 'Magyarázat', NOTE: 'Megjegyzés', WARNING: 'Figyelmeztetés', IMPORTANT: 'Fontos', CAUTION: 'Figyelem' })[match[1]] };
          }
        }
        if (node.tagName === 'sub' && /^(?:💡|➕|⚠️|📗|🗓️|🔖|🤖)/u.test(text.trim())) {
          node.tagName = 'small'; node.properties.className = ['study-label']; audit.labels.push(text);
        }
        if (node.tagName === 'p' && node.children.every(n => (n.type === 'text' && !n.value.trim()) || isElement(n, 'br'))) {
          node.properties.className = ['study-spacer'];
        }
        if (node.tagName === 'details') node.properties['data-pagefind-ignore'] = '';
        if (node.tagName === 'a' && node.properties.href) {
          jobs.push((async () => {
            let href = String(node.properties.href);
            if (href.startsWith('#') && sanitizedIds.has(href.slice(1))) href = '#' + sanitizedIds.get(href.slice(1));
            const resolved = await resolveUrl(href, false);
            if (resolved.citationOnly) { node.tagName = 'span'; node.properties = { dataPrivateLink: '' }; return; }
            node.properties.href = typeof resolved === 'string' ? resolved : resolved.url;
            if (resolved.private) { node.children.push({ type: 'text', value: ' (privát forrás)' }); }
            audit.links.push(node.properties.href);
          })());
        }
        if (node.tagName === 'img') {
          // Decided in document order, before any await: the output must not depend on which
          // asset resolves first, or unchanged pages would differ between builds.
          const order = imageCount++;
          node.properties.loading = order ? 'lazy' : 'eager';
          const source = String(node.properties.src);
          if (/\.mp4$/i.test(source)) {
            // An animation: a playable video on screen, its same-named PNG poster as the
            // static counterpart in print and PDF.
            jobs.push((async () => {
              const video = await resolveUrl(source, true);
              const poster = await resolveUrl(source.replace(/\.mp4$/i, '.png'), true);
              const alt = String(node.properties.alt || 'Animáció');
              audit.images[order] = poster;
              const player = el('video', { controls: true, preload: 'metadata', playsInline: true, poster, src: video, ariaLabel: alt, className: ['study-video-player'] }, [{ type: 'text', value: alt }]);
              const still = el('img', { src: poster, alt, loading: 'eager', decoding: 'async', className: ['study-figure', 'study-video-poster'] });
              Object.assign(node, el('span', { className: ['study-video'] }, [player, still]));
            })());
          } else jobs.push((async () => {
            node.properties.src = await resolveUrl(source, true);
            node.properties.decoding = 'async';
            audit.images[order] = node.properties.src;
            node.properties.className = [node.properties.src.includes('/banner-') ? 'study-banner' : 'study-figure'];
          })());
        }
        if (node.tagName === 'pre') {
          const code = node.children.find(n => isElement(n, 'code') && n.properties.className?.includes('language-mermaid'));
          if (code) jobs.push((async () => {
            const graph = code.children.map(n => n.value || '').join(''); audit.mermaid.push(graph);
            const image = await mermaid(graph);
            parent.children[index] = el('p', {}, [el('img', { src: image, alt: graph.match(/accTitle:\s*(.+)/)?.[1] || 'Kapcsolati ábra', className: ['study-figure'], loading: 'lazy' })]);
          })());
        }
      });
      await Promise.all(jobs);
      tidyPrivateLinks(tree);
      const kept = new Set();
      visit(tree, 'element', node => { if (isHeading(node)) kept.add(node.properties.id); });
      headings.splice(0, headings.length, ...headings.filter(h => kept.has(h.slug)));
    })
    .use(() => tree => {
      audit.formulas=[];
      visit(tree, 'element', node => {
        if(node.tagName==='code' && node.properties.className?.some(c=>c==='language-math'||c==='math-inline'||c==='math-display')) audit.formulas.push(toText(node));
      });
    })
    .use(rehypeMathjax, { svg: { fontCache: 'none' }, tex: { packages: ['base', 'ams', 'newcommand', 'configmacros', 'boldsymbol', 'textmacros'] } })
    .use(() => tree => {
      let formulaIndex = 0;
      visit(tree, 'element', node => {
        if (node.tagName === 'mjx-container') {
          node.properties.role = 'math';
          node.properties['aria-label'] = audit.formulas[formulaIndex++];
        }
        if (node.properties?.['data-mjx-error']) throw new Error(`Math rendering failed: ${node.properties['data-mjx-error']}`);
        if (node.properties?.dataMmlNode === 'merror' || node.properties?.['data-mml-node'] === 'merror') throw new Error('Math rendering failed');
        if (node.properties?.className?.includes('mjx-merror')) throw new Error('Math rendering failed');
      });
    })
    .use(rehypeStringify);
  const result = await processor.process(body);
  return { title, html: String(result), headings, audit, metadata };
}

export async function printSection(html, prefix) {
  // Prefix all IDs/references before combining independently rendered pages.
  const answers = [];
  const processor = unified().use(rehypeRaw).use(() => tree => {
    visit(tree, 'element', (node, index, parent) => {
      if (node.tagName === 'p' && node.properties.className?.includes('study-pending')) {
        parent.children.splice(index, 1); return index;
      }
    });
    visit(tree, 'element', (node, index, parent) => {
      if (node.properties.id) node.properties.id = prefix + node.properties.id;
      if (String(node.properties.href || '').startsWith('#')) node.properties.href = '#' + prefix + node.properties.href.slice(1);
      for (const prop of ['ariaDescribedBy', 'ariaLabelledBy']) if (node.properties[prop]) node.properties[prop] = node.properties[prop].map(id => prefix + id);
    });
    visit(tree, 'element', (node, index, parent) => {
      if (node.tagName === 'img') node.properties.loading = 'eager';
      // Print and PDF show an animation's poster only.
      if (node.tagName === 'video') { parent.children.splice(index, 1); return index; }
      if (node.tagName === 'p') {
        let hasImage = false; visit(node, 'element', child => { if (child.tagName === 'img') hasImage = true; });
        if (hasImage) node.properties.className = ['print-figure'];
      }
      if (node.tagName === 'details') {
        const summary = node.children.find(n => isElement(n, 'summary'));
        const question = structuredClone(summary?.children || [{type:'text',value:'Válasz'}]);
        visit({type:'root',children:question}, 'element', n => { delete n.properties.id; });
        answers.push({ question, children: node.children.filter(n => n !== summary) });
        // Preserve the question at its original place; solutions move to the end.
        node.tagName = 'p'; node.properties = { className: ['print-question'] }; node.children = summary?.children || [];
      }
    });
    // Keep a diagram and its immediate small/italic caption on the same sheet.
    const caption = n => isElement(n, 'p') && toText(n).length < 350 && n.children.some(c => isElement(c, 'em') || isElement(c, 'small')) && n.children.every(c => c.type === 'text' ? !c.value.trim() : ['em','small','sup','br'].includes(c.tagName));
    visit(tree, node => {
      if (!node.children || isElement(node,'figure')) return;
      for (let i=0;i<node.children.length;i++) {
        const child=node.children[i];
        if (!isElement(child,'p') || !child.properties.className?.includes('print-figure')) continue;
        let start=i,end=i+1;
        let j=i-1; while(j>=0 && node.children[j].type==='text' && !node.children[j].value.trim()) j--;
        if(j>=0 && caption(node.children[j])) start=j;
        j=i+1; while(j<node.children.length && node.children[j].type==='text' && !node.children[j].value.trim()) j++;
        if(j<node.children.length && caption(node.children[j])) end=j+1;
        child.properties.className=[];
        node.children.splice(start,end-start,el('figure',{className:['print-figure']},node.children.slice(start,end)));
        i=start;
      }
    });
  }).use(rehypeStringify);
  const result = await processor.run({ type: 'root', children: [{ type: 'raw', value: html }] });
  const answerTree = { type: 'root', children: answers.flatMap(a => [el('h3', {}, a.question), ...a.children]) };
  return { html: processor.stringify(result), answers: processor.stringify(answerTree) };
}
