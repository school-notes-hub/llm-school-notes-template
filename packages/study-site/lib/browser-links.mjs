// Keep every referring page and the target page when reporting a local link failure.
export function linkProblems(link, sources, pages, address, detail) {
  const pathname = new URL(link).pathname;
  const target = pages.find(p => new URL(p.url, address).pathname === pathname)?.path;
  return [...sources].sort().map(path => ({ path, ...(target ? { target } : {}), link, ...detail }));
}
