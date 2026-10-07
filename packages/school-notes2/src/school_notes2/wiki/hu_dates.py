"""Lesson dates in the learner's words (rules 1.22.6, PROFILE *Wording*): short Hungarian dates
within the school year (`okt. 4.`, `szept. eleje`), the year only for a day outside it
(`2025. okt. 4.`), never an ISO date in visible text. A date is a quiet meta item, as on a
GitHub release line: the study site draws a small outline clock before small grey text
(`.study-when`). An uncertain date gets only a `~` before it (`.study-when-unsure`); its range
and explanation are the hover tooltip (`title`), never visible text, and paper leaves the
uncertain item out."""

import html
import re

ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
MONTHS = ("jan.", "febr.", "márc.", "ápr.", "máj.", "jún.", "júl.", "aug.", "szept.", "okt.", "nov.", "dec.")
NEVER = "9999-12-31"
WHEN = "study-when"


def school_year(days: list[str]) -> int:
    """The year of the 1 September that starts the school year of the latest day (deterministic:
    from the lessons, never from today)."""
    days = [d for d in days if d and d != NEVER]
    if not days:
        return 0
    latest = max(days)
    return int(latest[:4]) if int(latest[5:7]) >= 9 else int(latest[:4]) - 1


def _inside(day: str, year: int) -> bool:
    return not year or f"{year}-09-01" <= day <= f"{year + 1}-08-31"


def short(day: str, year: int = 0) -> str:
    """`okt. 4.`; `2025. okt. 4.` outside the school year."""
    y, m, d = int(day[:4]), int(day[5:7]), int(day[8:10])
    return ("" if _inside(day, year) else f"{y}. ") + f"{MONTHS[m - 1]} {d}."


def full(day: str) -> str:
    """`2026. 10. 04.` where a full date is needed."""
    return f"{day[:4]}. {day[5:7]}. {day[8:10]}."


def part(day: str, year: int = 0) -> str:
    d = int(day[8:10])
    word = "eleje" if d <= 10 else "közepe" if d <= 20 else "vége"
    y = "" if _inside(day, year) else f"{day[:4]}. "
    return f"{y}{MONTHS[int(day[5:7]) - 1]} {word}"


def between(first: str, last: str) -> str:
    """Two formatted points as one span, in Hungarian style: within one month the month once and
    an unspaced en dash (`szept. 10–19.`, the inner point dropped; `szept. eleje–közepe`),
    otherwise a spaced en dash (`szept. 23. – okt. 4.`)."""
    if first == last:
        return first
    a, b = first.rsplit(" ", 1), last.rsplit(" ", 1)
    if len(a) == 2 and len(b) == 2 and a[0] == b[0]:
        left = a[1][:-1] if a[1].endswith(".") and b[1].endswith(".") else a[1]
        return f"{a[0]} {left}–{b[1]}"
    return f"{first} – {last}"


def approximate(lo: str, hi: str, year: int = 0) -> str:
    """The visible part of an uncertain day: the part of the month when both bounds fall in it,
    the month alone when they fall in one month, else the part of the month of the lower bound
    (the day it is ordered by); its range belongs to the tooltip."""
    if not lo and (not hi or hi == NEVER):
        return "?"
    if not lo or not hi or hi == NEVER:
        return part(lo or hi, year)
    if part(lo, year) == part(hi, year):
        return part(lo, year)
    if lo[:7] == hi[:7]:
        return part(lo, year).rsplit(" ", 1)[0]
    return part(lo, year)


def range_text(lo: str, hi: str, year: int = 0) -> str:
    """The range of an undated lesson for its tooltip."""
    if lo and hi and hi != NEVER:
        return between(short(lo, year), short(hi, year))
    if lo:
        return f"legkorábban {short(lo, year)}"
    if hi and hi != NEVER:
        return f"legkésőbb {short(hi, year)}"
    return "ismeretlen"


def in_text(text: str, year: int = 0) -> str:
    """Free text (a `date_note`) with its ISO dates in the short form."""
    return ISO.sub(lambda m: short(m[0], year), text)


def meta(text: str, title: str = "", unsure: bool = False) -> str:
    """The quiet date item: `<span class="study-when" title="…">okt. 4.</span>`; an uncertain one
    `~` + text with the class `study-when-unsure`."""
    classes = WHEN + (f" {WHEN}-unsure" if unsure else "")
    tip = f' title="{html.escape(title, quote=True)}"' if title else ""
    return f'<span class="{classes}"{tip}>{"~" if unsure and text != "?" else ""}{text}</span>'
