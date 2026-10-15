// Browser actions and their recorded timing, independent of capture orchestration.
export function locator(page, role) {
  return page.locator(`[data-usage-${role}]`).first();
}

async function pointOf(loc) {
  const summary = loc.locator("summary");
  const target = (await summary.count()) ? summary.first() : loc;
  const box = await target.boundingBox();
  return box ? [box.x + box.width / 2, box.y + box.height / 2] : null;
}

async function clickAction(page, action) {
  const loc = locator(page, action.szereplo);
  if (!(await loc.count())) return false;
  if (action.muvelet !== "koppint") {
    const open = await loc.evaluate((n) =>
      n.popoverTargetElement
        ? n.popoverTargetElement.matches(":popover-open")
        : n.tagName === "DETAILS"
          ? n.open
          : (n.querySelector("details")?.open ??
            n.getAttribute("aria-expanded") === "true"),
    );
    if (open === (action.muvelet === "nyit")) return false;
  }
  const summary = loc.locator("summary");
  const target = (await summary.count()) ? summary.first() : loc;
  const destination = await target.evaluate((n) => n.closest("a[href]")?.href);
  const activate = () =>
    action.muvelet === "koppint"
      ? target.tap({ timeout: 3000 })
      : target.click();
  if (destination)
    await Promise.all([
      page.waitForURL(destination, { waitUntil: "networkidle" }),
      activate(),
    ]);
  else await activate();
  return true;
}

export async function recordAction(ctx, action) {
  const { page, shot, motion } = ctx;
  const loc = locator(page, action.szereplo);
  if (action.muvelet === "esc") {
    await page.keyboard.press("Escape");
    await page.evaluate(() => document.activeElement?.blur());
    motion.push({ image: await shot("-esc"), seconds: 0.6 });
    return;
  }
  if (!(await loc.count())) return;
  const cursor = await pointOf(loc);
  if (action.muvelet === "gepel") {
    await typeText(ctx, loc, action.text, cursor);
    return;
  }
  const before = await shot(`-allapot-${motion.length}-elotte`);
  if (await clickAction(page, action)) {
    motion.push({ image: before, seconds: 0.6, cursor, approach: true });
    motion.push({
      image: await shot(`-allapot-${motion.length}-utana`),
      seconds: 0.3,
      cursor,
      ring: true,
    });
  }
}

export async function scroll(ctx, step, boxes) {
  const item = boxes[step.gorget?.szereplo];
  const box = item?.context || item?.box;
  if (!box) return;
  const { page, shot, motion } = ctx;
  const start = await page.evaluate(() => scrollY);
  const { top, content } = await page.evaluate(() => globalThis.__usageLayout());
  let target =
    step.gorget.igazit === "kozep"
      ? (page.viewportSize().height - box[3] + top) / 2
      : top;
  if (step.kamera !== 'teljes' && step.nezet !== 'telefon' && content) {
    const height = (content[2] + 32) * 9 / 16;
    const tall = step.kiemel?.some((c) => c.magas) && box[3] > page.viewportSize().height - top;
    const footer = item.label_context || step.dom_sorrend ||
      item.structures?.some(kind => ['cimke', 'datum-link'].includes(kind));
    target = tall ? top + 24 : footer // 16 CSS px context plus border padding.
      ? top + height - box[3] - 40
      : top + Math.min(80, height * 0.2);
  }
  const delta = step.gorget.igazit === "teteje" ? -start : box[1] - target;
  const count =
    Math.abs(delta) < 2
      ? 0
      : Math.ceil(Math.min(1.6, Math.max(0.6, Math.abs(delta) / 1000)) * 30);
  for (let i = 1; i <= count; i++) {
    const u = i / count;
    await page.evaluate(
      async (y) => {
        scrollTo(0, y);
        await new Promise((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)),
        );
      },
      start + delta * u * u * (3 - 2 * u),
    );
    motion.push({
      image: await shot(`-gorget-${String(i).padStart(2, "0")}`),
      seconds: 1 / 30,
    });
  }
}

export async function anchoredAction(ctx, step) {
  let before = { image: null, cursor: null };
  for (const action of (step.allapot || []).filter(
    (a) => a.horgony || a.muvelet === "koppint",
  )) {
    before = {
      image: await ctx.shot("-elotte"),
      cursor: await pointOf(locator(ctx.page, action.szereplo)),
    };
    await clickAction(ctx.page, action);
  }
  return before;
}

async function typeText({ page, shot, motion }, loc, text, cursor) {
  motion.push({
    image: await shot("-gepel-elotte"),
    seconds: 0.6,
    cursor,
    approach: true,
  });
  await loc.fill("");
  for (const letter of text) {
    await loc.pressSequentially(letter);
    motion.push({
      image: await shot(`-gepel-${motion.length}`),
      seconds: 0.1,
      cursor,
    });
  }
  await page.waitForTimeout(500); // Pagefind debounce.
  motion.push({ image: await shot("-gepel-kesz"), seconds: 0.5, cursor });
  await loc.blur(); // Recorded typing keeps focus; the following highlight does not.
}
