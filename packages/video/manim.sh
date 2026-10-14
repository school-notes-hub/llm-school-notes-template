#!/bin/sh
# A videólánc Manimja: a conda-forge-környezet és a saját TinyTeX (a képletekhez), sudo nélkül.
# A videotar (elemtár) ebből a mappából kerül a PYTHONPATH-ra: a jelenetkód `from videotar import …`-tal használja.
# Telepítés: school-notes-ops/docs/helyi/video/telepites.md
S="$HOME/.local/share/school-notes"
D="$(cd "$(dirname "$0")" && pwd)"
PYTHONPATH="$D${PYTHONPATH:+:$PYTHONPATH}" PATH="$(ls -d "$S"/tinytex/.TinyTeX/bin/*/ | head -1):$PATH" exec "$S/manim-env/bin/manim" "$@"
