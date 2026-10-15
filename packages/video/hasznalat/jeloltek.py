"""Teljes jelöltlista a nyilvános HTML-ből és a böngésző ábralistájából."""

from html.parser import HTMLParser
from urllib.parse import urlsplit

from .kitolt import clean, speakable


class Node:
    def __init__(self, tag="root", attrs=(), parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []

    @property
    def text(self):
        return "".join(c.text if isinstance(c, Node) else c for c in self.children)

    def all(self, tag=None, cls=None):
        found = []
        for c in self.children:
            if not isinstance(c, Node):
                continue
            if (tag is None or c.tag == tag) and (
                cls is None or cls in c.attrs.get("class", "").split()
            ):
                found.append(c)
            found.extend(c.all(tag, cls))
        return found


class HTML(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = self.current = Node()
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.current)
        self.current.children.append(n)
        if tag not in {"img", "br", "hr", "input", "meta", "link", "source", "wbr"}:
            self.current = n

    def handle_endtag(self, tag):
        n = self.current
        while n.parent:
            if n.tag == tag:
                self.current = n.parent
                return
            n = n.parent

    def handle_data(self, data):
        self.current.children.append(data)


def position(url, links):
    return links.index(url) if url in links else len(links)


def subject_context(pages, subject):
    dom = HTML(subject["html"]).root
    chapter = next(
        (
            a.attrs.get("href", "").split("#fejezet-")[-1]
            for n in dom.all(cls="study-path-now")
            for a in n.all("a")
        ),
        None,
    )
    order = [
        a.attrs.get("href")
        for li in dom.all("li")
        if li.text.strip().startswith("📄")
        for a in li.all("a")
    ]
    lessons = [
        p
        for p in pages
        if p.get("kind") == "topic" and p["route"].startswith(subject["route"] + "/")
    ]
    lessons.sort(key=lambda p: (position(p["url"], order), p["route"]))
    summary = next(
        (
            p
            for p in pages
            if p.get("kind") == "chapter-summary"
            and p.get("chapterId") == chapter
            and p["route"].startswith(subject["route"] + "/")
        ),
        None,
    )
    return dom, chapter, order, lessons, summary


def missing_content(lesson):
    dom = HTML(lesson["html"]).root
    missing = [
        cls
        for cls in (
            "study-brief",
            "study-podcast",
            "study-figure",
            "study-open-questions",
        )
        if not dom.all(cls=cls)
    ]
    if not lesson.get("usageClassroomParagraphs"):
        missing.append("E2: címke nélküli törzsbekezdés órai lábjegyzettel")
    labels = dom.all(cls="study-label")
    missing += [
        text
        for text in ("📗", "⚠️", "➕", "💡")
        if not any(n.text.strip().startswith(text) for n in labels)
    ]
    if not any("🗓️" in n.text and "Tankönyv" in n.text for n in labels):
        missing.append("Óra-sor tankönyvvel")
    if not dom.all("details") or "Kérdezd ki magad" not in dom.text:
        missing.append("Kérdezd ki magad")
    if not any("data-footnotes" in n.attrs for n in dom.all("section")):
        missing.append("Források")
    return missing


def missing_structure(subject, dom, chapter, lesson, summary):
    missing = []
    if not chapter or lesson.get("chapterId") != chapter:
        missing.append("mostani fejezet")
    if not dom.all(cls="study-path-done"):
        missing.append("korábbi fejezet")
    if not summary or not any(
        urlsplit(a.attrs.get("href", "")).path == urlsplit(lesson["url"]).path
        for a in HTML(summary["html"]).root.all("a")
        if "Részletesen" in a.text or "Részletesen" in a.parent.text
    ):
        missing.append("összefoglaló Részletesen linkkel")
    return missing


def subject_candidates(pages, home, subject, index, figures):
    dom, chapter, order, lessons, summary = subject_context(pages, subject)
    found, rejected = [], []
    optional = int(bool(dom.all(cls="study-when-unsure")))
    for lesson in lessons:
        missing = missing_structure(
            subject, dom, chapter, lesson, summary
        ) + missing_content(lesson)
        if not figures.get(lesson["route"], []):
            missing.append("nincs nem fejléc img.study-figure ábra")
        titles = [
            subject["title"],
            lesson["title"],
            lesson.get("chapterTitle", ""),
            (summary or {}).get("title", ""),
        ]
        missing += [
            "kimondható cím: " + title
            for title in titles
            if not speakable(clean(title))
        ]
        if missing:
            rejected.append({"lap": lesson["route"], "hiany": missing})
        else:
            found.append(
                {
                    "tantargy": subject,
                    "lecke": lesson,
                    "osszefoglalo": summary,
                    "kezdolap": home,
                    "opcionalis": optional,
                    "sorrend": [
                        -optional,
                        index,
                        position(lesson["url"], order),
                        lesson["route"],
                    ],
                }
            )
    return found, rejected


def candidates(payload, figures=None):
    pages = payload["pages"]
    if figures is None:
        figures = {p["route"]: p.get("usageFigures", []) for p in pages}
    home = next(p for p in pages if p.get("navigation") == "home")
    links = [a.attrs.get("href") for a in HTML(home["html"]).root.all("a")]
    subjects = [p for p in pages if p.get("navigation") == "subject"]
    subjects.sort(key=lambda p: (position(p["url"], links), pages.index(p)))
    found, rejected = [], []
    for index, subject in enumerate(subjects):
        accepted, excluded = subject_candidates(pages, home, subject, index, figures)
        found.extend(accepted)
        rejected.extend(excluded)
    found.sort(key=lambda candidate: candidate["sorrend"])
    # The home page links its project information; a podcast index is also an
    # info page in the sidebar, so navigation kind alone is not sufficient.
    projects = [p for p in pages if p.get("navigation") == "info" and p["url"] in links]
    if len(projects) != 1:
        raise ValueError("a kezdőlapnak pontosan egy projekt-információs lapra kell hivatkoznia")
    project = projects[0]
    for candidate in found:
        candidate["projekt"] = project
    return found, rejected


def listing(candidates_, rejected):
    lines = [
        f"{c['tantargy']['route']} | {c['lecke'].get('chapterTitle', '')} | {c['lecke']['route']} | "
        f"{c['osszefoglalo']['route']} | kötelező: ✓ | opcionális: {c['opcionalis']}"
        for c in candidates_
    ]
    if not lines:
        lines.append("MEGÁLLT: nincs olyan lecke, amelyen minden kötelező rész megvan")
    lines.extend(f"Kizárva: {r['lap']}: {', '.join(r['hiany'])}" for r in rejected)
    return "\n".join(lines) + "\n"
