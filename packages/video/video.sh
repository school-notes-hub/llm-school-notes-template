#!/bin/sh
# A Manim-videó gépi lánca (terv-menet.md 2. pont): burok a video.py körül, ugyanennek a fának a school_notes2
# uv-környezetében (ahogy az sn fut). A Manim a manim.sh-n át, saját környezetben renderel.
#   video.sh <tanuló> <tantárgy> <lap>-<n> [--atadas [--valtozott] | --vegleges | --meres | --takarit]
# Kilépési kód: 0 zöld, 1 piros, 2 megállt, 3 render-összeomlás. Részletek: <munkamappa>/video.log.
# Az író csak 480p-n (kapcsoló nélkül) futtatja, előtérben, 600000 ms-os timeouttal.
# Élesben a kiadott fából fut: ~/.local/share/school-notes/release/current/packages/video/video.sh
D="$(cd "$(dirname "$0")" && pwd)"
R="$(dirname "$D")/school-notes2"
[ -f "$R/pyproject.toml" ] || { echo "MEGÁLLT: nincs school-notes2 a fában: $R"; exit 2; }
command -v uv >/dev/null 2>&1 || { echo "MEGÁLLT: nincs uv"; exit 2; }
exec uv run --quiet --frozen --project "$R" python "$D/video.py" "$@"
