// Merge a declarative, action-free tour group into the page's reading order.
// IDs retain their positions; all later consumers read the resolved script.
import { newState, openPage, measure } from './usage-record.mjs';

export async function orderTargets(page, actors, requested) {
  const starts = new Set(requested.map(role => actors[role].sorozat).filter(Boolean));
  for (const start of starts) {
    const remaining = requested.filter(role => actors[role].sorozat === start);
    let previous = start;
    while (remaining.length) {
      for (const role of remaining) actors[role].utana = previous;
      const boxes = await page.evaluate(measure, {actors, requested: remaining});
      const next = remaining.filter(role => boxes[role].dom_order !== null)
        .sort((a, b) => boxes[a].dom_order - boxes[b].dom_order)[0];
      if (!next) throw Error('DOM order: no later target for ' + remaining.join(', '));
      remaining.splice(remaining.indexOf(next), 1);
      previous = next;
    }
  }
}

export async function orderTour(browser, origin, script, actors) {
  for (const scene of script.jelenetek) {
    const groups = [];
    for (let i = 0; i < scene.lepesek.length;) {
      if (!scene.lepesek[i].dom_sorrend) { i++; continue; }
      const start = i;
      while (scene.lepesek[i]?.dom_sorrend) i++;
      groups.push([start, i]);
    }
    if (!groups.length) continue;
    const state = await newState(browser, scene.nezet, origin);
    try {
      for (const [start, end] of groups) {
        const group = scene.lepesek.slice(start, end);
        if (group.some(s => s.url !== group[0].url || s.allapot?.length || s.kurzor ||
            s.kiemel?.length !== 1 || s.gorget?.szereplo !== s.kiemel[0].szereplo))
          throw Error('DOM order requires one page and one passive target per step');
        await openPage(state, group[0].url, origin);
        const requested = group.map(s => s.kiemel[0].szereplo);
        await orderTargets(state.page, actors, requested);
        const boxes = await state.page.evaluate(measure, {actors, requested});
        if (requested.some(role => boxes[role].dom_order === null))
          throw Error('DOM order: missing target: ' + requested.filter(role => boxes[role].dom_order === null).join(', '));
        const ids = group.map(s => s.id);
        group.sort((a, b) => boxes[a.kiemel[0].szereplo].dom_order - boxes[b.kiemel[0].szereplo].dom_order);
        group.forEach((step, i) => { step.id = ids[i]; });
        scene.lepesek.splice(start, group.length, ...group);
      }
    } finally { await state.page.close(); }
  }
}
