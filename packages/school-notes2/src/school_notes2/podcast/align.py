"""Where Whisper has a name, and whether it wrote the name (the name check's alignment, apart
from the paid calls in `names.py`): the text's and Whisper's words, their timing (`timeline`),
the Whisper check by spelling (`whisper_heard`) and each occurrence's own Whisper words
(`place`). Deterministic, no I/O. The rules are described in `names.py`."""

import difflib
import re
import unicodedata

def norm_ph(text: str) -> str:
    text = unicodedata.normalize("NFC", (text or "").lower())
    text = re.sub(r"[^a-záéíóöőúüű ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact(text: str) -> str:
    """The comparison form: no spaces, `ly` as `j` (the same sound)."""
    return norm_ph(text).replace(" ", "").replace("ly", "j")


def words_of(text: str) -> list[tuple[str, str]]:
    return [(w, norm_ph(w).replace(" ", "")) for w in text.split() if norm_ph(w)]


TIMING_WORD, TIMING_SEGMENT, TIMING_GAP, TIMING_NONE = "word", "segment", "gap", "none"
SIMILAR = 0.6          # the least similarity of a Whisper window to the name among other unmatched words


def timeline(transcript: dict) -> tuple[list[tuple[str, float, float, str]], str]:
    """Whisper's words as (normalised, start, end, as written) and how they are timed: `word`
    (word times), `segment` (the answer has segment times only – some OpenRouter providers give
    no word times: every word of a segment gets the segment's span) or `none`."""
    words = [(norm_ph(w.get("word", "")).replace(" ", ""), w["start"], w["end"], str(w.get("word", "")).strip())
             for w in transcript.get("words") or [] if "start" in w and "end" in w]
    if words:
        return words, TIMING_WORD
    words = [(norm_ph(w).replace(" ", ""), seg["start"], seg["end"], w)
             for seg in transcript.get("segments") or [] if "start" in seg and "end" in seg
             for w in str(seg.get("text") or "").split()]
    return (words, TIMING_SEGMENT) if words else ([], TIMING_NONE)


def _equal(tw: list, ww: list) -> dict[int, int]:
    """Text word index → Whisper word index for the words the two agree on."""
    matcher = difflib.SequenceMatcher(None, [n for _, n in tw], [w[0] for w in ww], autojunk=False)
    t2w = {}
    for tag, a0, a1, b0, _ in matcher.get_opcodes():
        if tag == "equal":
            for k in range(a1 - a0):
                t2w[a0 + k] = b0 + k
    return t2w


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))


VOWELS = frozenset("aeiouöü")          # after `_fold`; `y` (Kölcsey) counts with the consonants
# The case endings Whisper may write after a name (accents folded): -t/-ot/-at/-et/-öt, -nak/-nek,
# -val/-vel, -ról, -tól, -hoz, -ban, -ba, -ból, -ra, -on, -n, -ig, -ért, -ként, -nál, -ul, -vá,
# -kor, -é. Nothing else: `Ionok` is not `Ión`. After a consonant -val/-vel/-vá/-vé assimilate
# (`_assimilated`).
ENDINGS = frozenset({"t", "ot", "at", "et", "nak", "nek", "val", "vel", "rol", "tol", "hoz", "hez", "ban",
                     "ben", "ba", "be", "bol", "ra", "re", "on", "en", "n", "ig", "ert", "kent", "nal", "nel",
                     "ul", "va", "ve", "kor", "e", "ek"})
ASSIMILATED = ("al", "el", "a", "e")    # -val, -vel, -vá, -vé after the doubled consonant (folded)
DIGRAPHS = ("sz", "cs", "zs", "gy", "ny", "ty", "dz")
VARIANT_FROM = 5                       # letters; a shorter name gets no one-letter spelling variant


def _assimilated(stem: str) -> tuple[int, str] | None:
    """(where the stem's written form changes, the assimilated stem) of a consonant-final stem:
    its last consonant doubled – a digraph by its first letter (`zeusz` → `zeussz`), `th` read as
    t (`kossuth` → `kossutht`); None after a vowel or a lone `y` (Kölcsey: -vel stays)."""
    if not stem or stem[-1] in VOWELS:
        return None
    if stem.endswith("th"):
        return len(stem), stem + "t"
    if stem[-2:] in DIGRAPHS:
        return len(stem) - 2, stem[:-2] + stem[-2] + stem[-2:]
    if stem[-1] == "y":
        return None
    return len(stem), stem + stem[-1]


def _inflected(got: str, stem: str, last: int) -> bool:
    """`got` is `stem` with a case ending, all of it inside the last word (it starts at `last`)."""
    if got.startswith(stem) and len(stem) > last and got[len(stem):] in ENDINGS:
        return True
    found = _assimilated(stem)
    return bool(found) and found[0] > last and any(got == found[1] + ending for ending in ASSIMILATED)


def _one_consonant(a: str, b: str) -> bool:
    """`b` is `a` with one consonant inserted, or the other way round (Zeus/Zeusz, Kosuth/Kossuth);
    never a vowel (`Zesz` is not `Zeusz`) and never a changed letter."""
    if abs(len(a) - len(b)) != 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    return any(b[i] not in VOWELS and b[:i] + b[i + 1:] == a for i in range(len(b)))


def _written_as(words: list[str], wanted: str) -> bool:
    """Whisper's words (`_fold`ed, compact) are `wanted` (folded, compact): equal, or – from
    `VARIANT_FROM` letters on – with one consonant more or less; then at most a case ending
    (`_inflected`: `ENDINGS`, or -val/-vel/-vá/-vé assimilated to the name's own last consonant)
    inside the last word: `Kossuth Lajos és Petőfi` is not `Kossuth`, `Rémület` is not `Ré`,
    `Kossuthka` is not `Kossuth`."""
    got = "".join(words)
    if not wanted or not got:
        return False
    last = len(got) - len(words[-1])
    stems = [wanted] if got.startswith(wanted) else []
    if len(wanted) >= VARIANT_FROM:
        stems += [got[:n] for n in (len(wanted) - 1, len(wanted) + 1)
                  if 0 < n <= len(got) and _one_consonant(got[:n], wanted)]
    return got == wanted or any(got == stem or _inflected(got, stem, last) for stem in stems) \
        or _inflected(got, wanted, last)


def whisper_heard(written: list[str], entry: dict) -> bool:
    """Did Whisper write this name where it stands? Whisper writes a name mostly as it is spelled
    (`Kossuth`, `Széchenyi`, `Zeus`), sometimes as it sounds (`Kölcsei`): its words there, accents
    aside (Whisper's accents are no evidence of vowel length – the blind check's are), are the form
    or a target (`_written_as`). A different sound (`Szícsinyi`, `Kusut`) is not the name.
    The measured method (2026-10-07: 0/12 false accepts) asked Whisper for a target literally;
    this spelling-aware condition is sn 0.4.1's and was not measured (the measurement's clips are
    not kept): the pronunciation itself stays the blind check's, three exact targets."""
    words = [w for w in (_fold(compact(x)) for x in written) if w]
    return bool(words) and any(_written_as(words, _fold(compact(w))) for w in [entry["form"], *entry["targets"]])


def _similarity(written: list[str], entry: dict) -> float:
    got = compact(" ".join(written))
    wanted = [compact(entry["form"]), *(compact(t) for t in entry["targets"])]
    return max(difflib.SequenceMatcher(None, _fold(got), _fold(w), autojunk=False).ratio() for w in wanted)


def place(tw: list, ww: list, t2w: dict, found: list[tuple[dict, int, int]]) -> list[dict]:
    """Where Whisper has each occurrence (in text order): `window` (first, end) of its own Whisper
    words, or None and `gap` (first, end) – the Whisper words between the agreeing neighbours.

    1. Every word of the name agrees with Whisper: those words.
    2. Between the agreeing neighbours the text has only the name: everything Whisper wrote
       there (`Szícsinyi István` for `Széchenyi István`).
    3. Other unmatched text words too: the shortest earliest window of at most the name's length
       + 2 words that Whisper wrote as the name (`whisper_heard`), else the most similar one if at
       least `SIMILAR` (ties: the earliest, then the shortest).

    A later occurrence is looked for only after the earlier one's window: two names never get
    the same Whisper words (and so the same moment)."""
    out, last = [], 0
    for entry, i0, i1 in found:
        prev = max((i for i in t2w if i < i0), default=None)
        nxt = min((i for i in t2w if i >= i1), default=None)
        lo = max(t2w[prev] + 1 if prev is not None else 0, last)
        hi = t2w[nxt] if nxt is not None else len(ww)
        window = None
        if all(i in t2w for i in range(i0, i1)):
            window = (t2w[i0], t2w[i1 - 1] + 1)
        elif lo < hi:
            first, end = prev + 1 if prev is not None else 0, nxt if nxt is not None else len(tw)
            others = [i for i in range(first, end) if not i0 <= i < i1]
            if not others:
                window = (lo, hi)
            else:
                size = (i1 - i0) + 2
                spans = [(s, e) for s in range(lo, hi) for e in range(s + 1, min(hi, s + size) + 1)]
                written = {(s, e): [w[3] for w in ww[s:e]] for s, e in spans}
                exact = [span for span in spans if whisper_heard(written[span], entry)]
                if exact:
                    window = min(exact, key=lambda span: (span[0], span[1]))
                elif spans:
                    best = min(spans, key=lambda span: (-_similarity(written[span], entry), span[0], span[1]))
                    if _similarity(written[best], entry) >= SIMILAR:
                        window = best
        if window is not None:
            last = window[1]
        out.append({"window": window, "gap": (lo, hi),
                    "between": (prev + 1 if prev is not None else 0, nxt if nxt is not None else len(tw))})
    return out
