"""The home page's generated guide and legend, and their idempotent placement."""

import re
from pathlib import Path

from ..state import safefs
from . import markers

GUIDE_ANCHOR = "hogyan-hasznald"
GUIDE = [
    "* 📚 **Tantárgyoldal**: a tantárgy fejezetei a tanítás sorrendjében, bennük a kidolgozott "
    "leckék. Felül a 🧭 **Hol tartunk** doboz: ✓ a korábban kezdett, ◉ a mostani fejezet; alul az "
    "🗓️ **Órák**: melyik órán mit vettünk.",
    "* 📄 **Kidolgozott lecke** (témalap): a teljes tananyag: ⚡ Röviden, magyarázat, ábrák, "
    "🧠 Kérdezd ki magad. Tanuláshoz, házihoz, dolgozatra készüléshez.",
    "* ⚡ **Összefoglaló**: a fejezet rövid változata, a fejezet végén; ismétléshez és dolgozat "
    "előtt. Minden pontja a kidolgozott leckére visz.",
    "* 🗓️ **Órák**: a tantárgyoldal alján, a legújabb óra felül. A dátum kicsi; a `~` azt jelenti, "
    "hogy nem biztos – koppints rá, vagy vidd rá az egeret, és látod az időszakot.",
]
GUIDE_PODCAST = ("* 🎧 **Podcast**: rövid beszélgetés egy-egy kidolgozott leckéről; a lecke ⚡ Röviden "
                 "doboza alatt és a 🎧 Podcast oldalon hallgathatod.")
LEGEND = [
    "A jelöletlen szöveg az órán tanult anyag. Ami ehhez hozzá van téve, azt kis címke jelöli "
    "közvetlenül a hozzá tartozó tartalom alatt; az egeret rávive látod a jelentését "
    "(link nélküli címkén koppintásra is). A 🤖 gépi szerzőséget mutat, nem hitelesítést.",
    "",
    "* 💡 **Magyarázat** (<sub>💡 🤖 gépi magyarázat</sub>): kifejti, amit az órai anyag csak röviden "
    "ír le: miért van így, hogyan jutunk az eredményhez.",
    "* ➕ **Kiegészítés** (<sub>➕ 🤖 gépi kiegészítés</sub>): kitölt egy, a megértéshez fontos hiányt.",
    "* ⚠️ **Javítás** (<sub>⚠️ 🤖 gépi javítás</sub>): a helyes változat ott, ahol az órai jegyzetben "
    "hiba volt; ilyenkor javítsd a füzetedet is.",
    "* 📗 **A tankönyv alapján**: a tankönyvből vett rész, amely az órai jegyzetben nem szerepelt.",
    "* 🗓️ **Óra**: melyik órán tanultátok az adott részt; ha nincs pontos dátum, `~` jelzi, az "
    "időszakot az egér rávitelekor látod (link nélküli dátumon koppintásra is).",
    "* 🔖 **Tankönyv**: a kapcsolódó lecke és oldal, vagy az, hogy a tankönyv ezt nem tárgyalja.",
    "* ⚡ **Röviden**: a kidolgozott lecke elején a legfontosabb tudnivalók; ezt nézd át dolgozat "
    "előtt. A fejezet ⚡ **Összefoglaló** oldala ezekből áll össze.",
    "* 🧠 **Kérdezd ki magad**: kérdések a kidolgozott lecke végén; a választ lenyitva "
    "ellenőrizheted magad.",
]


def guide_block(repo: Path) -> str:
    """🧭 Hogyan használd: the page kinds and the parts of a subject page, the same text for every
    learner (the 🎧 line while there is a Podcast page)."""
    from . import podcast
    lines = GUIDE + ([GUIDE_PODCAST] if safefs.is_file(repo, podcast.PAGE) else [])
    # no closing `<br />`: a raw HTML line would swallow the legend block's heading after it
    return f'# <a id="{GUIDE_ANCHOR}"></a>🧭 Hogyan használd\n\n' + "\n".join(lines) + "\n"


def legend_block() -> str:
    return "# 🔎 Jelmagyarázat\n\n" + "\n".join(LEGEND) + "\n"


HAND_LEGEND = re.compile(r"^# 🔎 Jelmagyarázat[ \t]*\n", re.M)
SECTION_END = re.compile(r"^(?:#{1,6} |<!-- school-notes:generated |<br\s*/?>)", re.M)


def place_home_blocks(text: str) -> str:
    """The guide and legend blocks' place on the home page, once: the hand-written
    `# 🔎 Jelmagyarázat` section (to the next heading, block or spacer) becomes the two blocks;
    without one they go right after the subjects block; a guide missing beside an existing
    legend goes in front of it; a missing legend goes right after the existing guide."""
    names = markers.names(text)
    if "guide" in names and "legend" in names:
        return text
    if "legend" in names:
        start = next(s for s, _, n in markers.spans(text) if n == "legend")
        return text[:start] + markers.wrap("guide", "") + text[start:]
    if "guide" in names:
        end = next(e for _, e, n in markers.spans(text) if n == "guide")
        return text[:end] + "\n" + markers.wrap("legend", "") + text[end:]
    old = HAND_LEGEND.search(text)
    if old and not any(s <= old.start() < e for s, e, _ in markers.spans(text)):
        end = SECTION_END.search(text, old.end())
        stop = end.start() if end else len(text)
        return text[:old.start()] + markers.wrap("guide", "") + markers.wrap("legend", "") + "\n" + text[stop:]
    after = next((e for _, e, n in markers.spans(text) if n == "subjects"), None)
    if after is None:
        return text
    return (text[:after].rstrip("\n") + "\n\n<br />\n\n" + markers.wrap("guide", "")
            + markers.wrap("legend", "") + "\n" + text[after:].lstrip("\n"))
