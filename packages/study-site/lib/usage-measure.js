// Executed in the inspected page. Helpers stay in this block, outside page globals.
{
  const headings = () => [
    ...document.querySelectorAll(
      ".study-content h1,.study-content h2,.study-content h3",
    ),
  ];
  const text = (node) => node.innerText || "";
  const matchingHeadings = (label) =>
    headings().filter((node) => text(node).includes(label));

  function section(label) {
    const found = matchingHeadings(label);
    if (found.length !== 1) return found;
    const nodes = [found[0]];
    for (
      let node = found[0].nextElementSibling;
      node;
      node = node.nextElementSibling
    ) {
      if (/^H[1-6]$/.test(node.tagName) && node.tagName <= found[0].tagName)
        break;
      nodes.push(node);
    }
    return nodes;
  }

  function figure(node) {
    const r = node.getBoundingClientRect();
    return (
      node.matches(figureSelector) &&
      node.complete &&
      node.naturalWidth > 0 &&
      r.width > 0 &&
      r.height > 0
    );
  }

  function resolve(name, actors, stack = []) {
    if (stack.includes(name)) throw Error(`cyclic role: ${name}`);
    const actor = actors[name];
    if (!actor) throw Error(`unknown role: ${name}`);
    if (actor.fajta === "unio")
      return actor.tagok.flatMap((n) => resolve(n, actors, [...stack, name]));
    let nodes =
      actor.fajta === "leszarmazott"
        ? resolve(actor.szulo, actors, [...stack, name]).flatMap(n => [...n.querySelectorAll(actor.selector)])
        : actor.fajta === "szakasz"
        ? section(actor.text)
        : [...document.querySelectorAll(actor.selector)];
    if (actor.fajta === "szakasz" && actor.selector) {
      nodes = nodes.flatMap((n) =>
        n.matches(actor.selector)
          ? [n]
          : [...n.querySelectorAll(actor.selector)],
      );
    }
    if (actor.fajta === "szoveg")
      nodes = nodes.filter((n) =>
        actor.kezdet
          ? text(n).trim().startsWith(actor.text)
          : text(n).includes(actor.text),
      );
    if (actor.szoveg)
      nodes = nodes.filter((n) => text(n).includes(actor.szoveg));
    if (actor.cimke_nelkul) nodes = nodes.filter(unlabelled);
    if (actor.ora_forras) nodes = nodes.filter(n =>
      (actor.forras_szovegek || []).includes(text(n).replace(/\s+/g, ' ').trim()));
    if (actor.elso !== undefined) nodes = nodes.slice(0, actor.elso);
    if (actor.n !== undefined) nodes = nodes.slice(actor.n, actor.n + 1);
    return nodes;
  }

  function unlabelled(node) {
    return node.matches('.study-content > p') && text(node).trim() &&
      !node.querySelector('.study-label, img, video, audio') &&
      !node.nextElementSibling?.matches('.study-label, p:has(> .study-label:only-child)') &&
      !node.matches('.study-kind, .study-desc') &&
      !text(node).trim().startsWith('🔖');
  }

  function context(nodes) {
    return nodes.flatMap((node) => {
      if (node.matches('.study-label') && !text(node).includes('🗓️')) {
        const block = node.closest('p, li, blockquote, .study-callout');
        // Inline footer (<br><small>) and a separate block footer both occur.
        if (block && text(block).trim() !== text(node).trim()) return [block];
        const footer = block || node;
        return [footer.previousElementSibling, footer].filter(Boolean);
      }
      return [node.closest('.study-kind, .study-tools, .study-label, li') || node];
    });
  }

  function tooltip(node) {
    const style = getComputedStyle(node, "::after");
    return (
      !["none", "normal", '""'].includes(style.content) &&
      style.display !== "none" &&
      style.visibility !== "hidden"
    );
  }

  function bubbleRect(node) {
    const s = getComputedStyle(node, "::after");
    if (!tooltip(node) || s.position !== "absolute") return [];
    const rect = node.getBoundingClientRect();
    const x = rect.x + (parseFloat(s.left) || 0),
      y = rect.y + (parseFloat(s.top) || 0);
    const width =
      parseFloat(s.width) +
      (s.boxSizing === "border-box"
        ? 0
        : parseFloat(s.paddingLeft) +
          parseFloat(s.paddingRight) +
          parseFloat(s.borderLeftWidth) +
          parseFloat(s.borderRightWidth));
    const height =
      parseFloat(s.height) +
      (s.boxSizing === "border-box"
        ? 0
        : parseFloat(s.paddingTop) +
          parseFloat(s.paddingBottom) +
          parseFloat(s.borderTopWidth) +
          parseFloat(s.borderBottomWidth));
    return Number.isFinite(width + height)
      ? [{ x, y, width, height, right: x + width, bottom: y + height }]
      : [];
  }

  function rectangles(nodes) {
    return nodes
      .flatMap((node) => {
        const elements =
          getComputedStyle(node).display === "contents"
            ? [...node.children]
            : [node];
        return [
          ...elements.map((n) => n.getBoundingClientRect()),
          ...bubbleRect(node),
        ];
      })
      .filter((r) => r.width > 0 && r.height > 0);
  }

  function bounds(rects) {
    if (!rects.length) return null;
    const x = Math.min(...rects.map((r) => r.x)),
      y = Math.min(...rects.map((r) => r.y));
    const right = Math.max(...rects.map((r) => r.right)),
      bottom = Math.max(...rects.map((r) => r.bottom));
    return [x, y, right - x, bottom - y].map(
      (v) => Math.round(v * 1000) / 1000,
    );
  }

  function fivePoints(r) {
    const dx = Math.min(8, r.width / 4),
      dy = Math.min(8, r.height / 4);
    return [
      [r.x + dx, r.y + dy],
      [r.right - dx, r.y + dy],
      [r.x + dx, r.bottom - dy],
      [r.right - dx, r.bottom - dy],
      [(r.x + r.right) / 2, (r.y + r.bottom) / 2],
    ];
  }

  function uncovered(nodes, rects) {
    let common = nodes[0];
    while (common && !nodes.every((n) => common.contains(n)))
      common = common.parentElement;
    return rects.flatMap(fivePoints).map(([x, y]) => {
      const hit = document.elementFromPoint(x, y);
      return (
        !!hit &&
        (hit === common || nodes.some((n) => n === hit || n.contains(hit)))
      );
    });
  }

  function visibleRects(rects) {
    const top = globalThis.__usageLayout().top;
    return rects.map((r) => {
      const x = Math.max(0, r.x), y = Math.max(top, r.y);
      const right = Math.min(innerWidth, r.right);
      const bottom = Math.min(innerHeight, r.bottom);
      return { x, y, right, bottom, width: right - x, height: bottom - y };
    }).filter((r) => r.width > 0 && r.height > 0);
  }

  function structures(nodes, actor) {
    if (!nodes.length) return [];
    const firstQuestion = section("Kérdezd ki magad").flatMap((n) =>
      n.matches("details") ? [n] : [...n.querySelectorAll("details")],
    )[0];
    const firstLesson = document.querySelector(
      '.study-content li:has(> a[id^="ora-"])',
    );
    const checks = {
      leiras: nodes.every((n) => n.matches(".study-desc") && text(n).trim()),
      "ora-sor": nodes[0] === firstLesson,
      "datum-link": nodes.every(
        (n) => n.matches('a[href*="#ora-"]') && n.closest('.study-label')?.textContent.includes('🗓️'),
      ),
      cimke: nodes.every((n) => n.matches(".study-label") && text(n).trim()),
      "cimke-nelkuli": actor.ora_forras && nodes.every(n => unlabelled(n) &&
        (actor.forras_szovegek || []).includes(text(n).replace(/\s+/g, ' ').trim())),
      abra: nodes.every(figure),
      utmutato: nodes.every(
        (n) =>
          section("Hogyan használd").some(
            (parent) => parent === n || parent.contains(n),
          ) && n.matches("ul"),
      ),
      kerdes: nodes[0] === firstQuestion && !!nodes[0].querySelector("summary"),
    };
    return Object.keys(checks).filter((key) => checks[key]);
  }

  function measureRole(name, actors) {
    document
      .querySelectorAll(`[data-usage-${name}]`)
      .forEach((n) => n.removeAttribute(`data-usage-${name}`));
    const actor = actors[name],
      nodes = resolve(name, actors),
      fragments = nodes.map(n => textFragment(n, actor)),
      rects = actor.reszlet ? fragments.flatMap(f => f?.rects || []) : rectangles(nodes);
    const count =
      actor.fajta === "szakasz" && !actor.selector
        ? matchingHeadings(actor.text).length
        : actor.fajta === "unio"
          ? Number(actor.tagok.every((n) => resolve(n, actors).length > 0))
          : nodes.length;
    const hrefs = nodes.flatMap((n) =>
      n.matches("a[href]")
        ? [n.getAttribute("href")]
        : [...n.querySelectorAll("a[href]")].map((a) => a.getAttribute("href")),
    );
    nodes.forEach((n) => n.setAttribute(`data-usage-${name}`, ""));
    return {
      count,
      reason:
        name === "abra" && !nodes.length
          ? "Nincs nem fejléc img.study-figure ábra a leckén."
          : "",
      box: bounds(rects),
      context: bounds(rectangles(context(nodes))),
      label_context: nodes.length > 0 && nodes.every((n) =>
        n.matches('.study-label') && !text(n).includes('🗓️')),
      visible: rects.length > 0,
      uncovered: uncovered(nodes, rects),
      visible_uncovered: uncovered(nodes, visibleRects(rects)),
      hrefs,
      text: (actor.reszlet ? fragments.map(f => f?.text || '') : nodes.map(text)).join(" ").replace(/\s+/g, " ").trim(),
      tooltip: nodes.some(tooltip),
      structures: structures(nodes, actor),
    };
  }

  // Measure a text range without changing the page's markup or line wrapping.
  function textFragment(node, actor) {
    if (!actor.reszlet) return null;
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT), leaves = [];
    while (walker.nextNode()) leaves.push(walker.currentNode);
    const full = leaves.map(n => n.textContent).join(''), start = full.indexOf(actor.reszlet);
    if (start < 0) return null;
    const end = actor.vegeig ? full.length : start + actor.reszlet.length;
    const range = document.createRange();
    let offset = 0;
    for (const leaf of leaves) {
      const next = offset + leaf.textContent.length;
      if (offset <= start && start < next) range.setStart(leaf, start - offset);
      if (offset < end && end <= next) range.setEnd(leaf, end - offset);
      offset = next;
    }
    return {text: full.slice(start, end), rects: [...range.getClientRects()]};
  }

  globalThis.__usageFigures = () =>
    [
      ...document.querySelectorAll(figureSelector),
    ].map((n) => ({
      src: n.getAttribute("src"),
      box: bounds([n.getBoundingClientRect()]),
      available: innerHeight - globalThis.__usageLayout().top,
      fits: figure(n) && n.getBoundingClientRect().height <= innerHeight - globalThis.__usageLayout().top,
    }));

  globalThis.__usageMeasure = ({ actors, requested }) =>
    Object.fromEntries(
      requested.map((name) => [name, measureRole(name, actors)]),
    );
  // Actual rendered word rectangles, excluding hidden/occluded text. These
  // describe the captured page; neither the camera nor the gate guesses fonts.
  globalThis.__usageText = () => {
    const result = [], walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode, parent = node.parentElement;
      if (!parent || parent.closest('script, style, svg') ||
          getComputedStyle(parent).visibility !== 'visible') continue;
      for (const match of node.textContent.matchAll(/\S+/gu)) {
        const range = document.createRange();
        range.setStart(node, match.index);
        range.setEnd(node, match.index + match[0].length);
        for (const r of range.getClientRects()) {
          const x = Math.max(0, r.left), y = Math.max(0, r.top);
          const right = Math.min(innerWidth, r.right), bottom = Math.min(innerHeight, r.bottom);
          if (right <= x || bottom <= y) continue;
          const hit = document.elementFromPoint((x + right) / 2, (y + bottom) / 2);
          if (hit && (hit === parent || parent.contains(hit)))
            result.push({ text: match[0], box: bounds([r]) });
        }
      }
    }
    return result;
  };
  globalThis.__usageFocus = () => [...document.querySelectorAll(':focus-visible')]
    .filter((n) => {
      const s = getComputedStyle(n), r = n.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && s.visibility === 'visible' &&
        ((s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== 'none');
    }).map((n) => ({ text: text(n), box: bounds(rectangles([n])) }));
  globalThis.__usageLayout = () => {
    const fixed = [
      ...document.querySelectorAll("header, mobile-starlight-toc nav"),
    ];
    const top =
      Math.max(0, ...fixed.map((n) => n.getBoundingClientRect().bottom)) + 16;
    return {
      content: bounds(
        rectangles([...document.querySelectorAll(".study-content")]),
      ),
      top,
    };
  };
}
