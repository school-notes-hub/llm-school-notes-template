#!/bin/sh
# A tesztjelenetek egy paranccsal: szintetikus bemenet (TTS és Whisper nélkül), 480p30 render,
# utána a pytest (benne a render-naplók séma- és geometriapróbája). Kimenet: <mappa>/render_naplo.json.
D="$(cd "$(dirname "$0")" && pwd)"
PY="$HOME/.local/share/school-notes/manim-env/bin/python"
for p in tesztjelenet:TesztJelenet hibasjelenet:HibasJelenet; do
  m=${p%%:*}; c=${p##*:}
  "$PY" "$D/szintetikus.py" "$D/$m" || exit 2
  t0=$(date +%s)
  ( cd "$D/$m" && "$D/../manim.sh" -ql --fps 30 --save_sections "$@" jelenetek.py "$c" > render.log 2>&1 ) \
    || { echo "$c: render-hiba (részletek: $m/render.log)"; tail -15 "$D/$m/render.log"; exit 3; }
  echo "$c: render $(( $(date +%s) - t0 )) s"
done
cd "$D" && "$PY" -m pytest -q -p no:warnings
