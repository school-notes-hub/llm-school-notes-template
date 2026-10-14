// The page kinds and how a page says what it is (plan terv-oldalszerkezet 5, owner 2026-10-15:
// the plan's texts). One table for the type band under the title, the Previous/Next links and
// the page foot; the home page's guide (the tool's `guide` block) explains the same kinds.
export const KINDS = {
  subject: { icon: '📚', name: 'Tantárgyoldal', text: 'a 📄 kidolgozott leckék fejezetenként, tanítási sorrendben; lent: melyik órán mit vettünk.' },
  topic: { icon: '📄', name: 'Kidolgozott lecke', text: 'a teljes tananyag: Röviden, magyarázat, ábrák, kérdések.' },
  'chapter-summary': { icon: '⚡', name: 'Összefoglaló', text: 'a fejezet rövid változata ismétléshez; a részletek a témalapokon.' },
  review: { icon: '🔁', name: 'Ismétlés', text: 'dolgozatra készülő összefoglaló.' },
  'lesson-notes': { icon: '🗓️', name: 'Órai jegyzet', text: 'rövid lap: mit vettünk ezen az órán; a tananyag a témalapokon.' },
};

// Previous/Next stay inside one subject and one family: the worked lessons and the summaries of
// a subject (in the release list's order: chapter by chapter, the summary after its topics), its
// reviews, its lesson logs. The home, subject, Podcast and info pages have none.
const FAMILY = { topic: 'lesson', 'chapter-summary': 'lesson', review: 'review', 'lesson-notes': 'notes' };

export function subjectOf(pages, page) {
  return pages.find(p => p.navigation === 'subject' && page.route.startsWith(p.route + '/'));
}

export function neighbours(pages, page) {
  const family = FAMILY[page.kind];
  const subject = subjectOf(pages, page);
  if (!family || !subject) return {};
  const row = pages.filter(p => FAMILY[p.kind] === family && subjectOf(pages, p) === subject);
  const i = row.indexOf(page);
  return { previous: row[i - 1], next: row[i + 1] };
}
