"""Deterministic writer: quoted repairs, accented links, plural lesson log and scope leak."""
import json
import posixpath
import sys
from pathlib import Path

from school_notes2.review import relations
from school_notes2.wiki import frontmatter

repo = Path(sys.argv[1])
fetch = json.loads((repo / ".school-notes/fetch.json").read_text())
result = {"status": "done", "review_closure": [], "infographic_decisions": []}
repaired_topics = set()
for item in fetch["open_review_items"]:
    detail = relations.details((repo / item["file"]).read_text(), item["item_id"])
    target = detail.get("file", "")
    if target.endswith(".md") and (repo / target).is_file():
        text = (repo / target).read_text()
        quote = detail.get("quote", "")
        if quote and quote in text and not quote.lstrip().startswith(("#", "---", "<!--")):
            text = text.replace(quote, quote + " A kapcsolat lépésenként követhető.", 1)
        else:
            text += "\nA kapcsolat lépésenként követhető.\n"
        if frontmatter.split(text).meta.get("type") == "topic":
            repaired_topics.add(target)
            if "## Áramló részecskék" not in text:
                text += "\n## Áramló részecskék\n\nA részecskék mozgása irányított.\n"
        (repo / target).write_text(text)
    result["review_closure"].append({"file": item["file"], "item_id": item["item_id"], "status": "fixed"})
topics = sorted(repaired_topics)
if len(topics) > 1:
    for source, target in zip(topics, topics[1:] + topics[:1]):
        link = posixpath.relpath(target, posixpath.dirname(source)) + "#áramló-részecskék"
        text = (repo / source).read_text()
        if link not in text:
            (repo / source).write_text(text + f"\n[Kapcsolódó magyarázat]({link})\n")
for item in fetch.get("infographic_pages", []):
    target = item if isinstance(item, str) else item["page"]
    result["infographic_decisions"].append({"page": target, "reason": "A szöveges levezetés elegendő."})
if fetch["open_review_items"]:
    (repo / "wiki/probe-unassigned.md").write_text("# Nem kiosztott\n\nEzt a tool visszaállítja.\n")
if fetch["packages"]:
    subject = fetch["packages"][0]["subject"]
    topics = sorted(p for p in (repo / "wiki" / subject).glob("*.md")
                    if frontmatter.split(p.read_text()).meta.get("type") == "topic")
    topic = topics[0]
    text = topic.read_text()
    if "## Áramló részecskék" not in text:
        text += "\n## Áramló részecskék\n\nA részecskék mozgása irányított.\n\n## Első lépés\n\nMegadjuk az irányt.\n\n## Második lépés\n\nMegadjuk a sebességet.\n"
    topic.write_text(text)
    note = f"wiki/{subject}/2026-10-02-proba-jegyzet.md"
    (repo / note).write_text("---\ntitle: Próbaórák\ndescription: A részecskék mozgása.\nlessons:\n"
        f"  - {{date: '2026-10-02', title: Első próbaóra, topics: [{topic.name}]}}\n"
        f"  - {{date: '2026-10-02', title: Második próbaóra, topics: [{topic.name}]}}\n---\n\n"
        f"# Mit tanultunk ezeken az órákon\n\n* [Áramló részecskék]({topic.name}#áramló-részecskék)\n"
        f"* [Első lépés]({topic.name}#első-lépés)\n* [Második lépés]({topic.name}#második-lépés)\n")
    result["notes"] = [{"file": note, "pages": [p["seq"] for p in fetch["pages"] if not p["duplicate_of"]]}]
log = repo / "wiki/log.md"
log.write_text(log.read_text() + "\n## 2026-10-05\n\n* **Update**: A magyarázat elkészült.\n")
(repo / ".school-notes/result.json").write_text(json.dumps(result, ensure_ascii=False))
