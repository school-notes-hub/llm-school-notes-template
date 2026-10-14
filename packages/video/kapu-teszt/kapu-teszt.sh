#!/bin/sh
# A kapu elfogadási próbája egy paranccsal: a TesztJelenet-en zöld, a HibasJelenet-en pontosan az
# elvart-kapu.json leletei; mellette a tábla, a lapok, a kivétel és a determinizmus próbái.
# --render: előbb a tesztjelenetek újrarenderelése (videotar-teszt/render.sh, kb. 15 s); render nélkül is
# lefut, ha a renderek megvannak (a kapu K1-e szól, ha a render régebbi a bemeneténél).
D="$(cd "$(dirname "$0")" && pwd)"
T="$D/../videotar-teszt"
if [ "$1" = "--render" ] || [ ! -f "$T/hibasjelenet/render_naplo.json" ] || [ ! -f "$T/tesztjelenet/render_naplo.json" ]; then
  "$T/render.sh" > "$D/render.log" 2>&1 || { tail -15 "$D/render.log"; exit 3; }
fi
cd "$D" && uv run --quiet --frozen --project "$(dirname "$(dirname "$D")")/school-notes2" \
  python -m pytest -q -p no:cacheprovider -p no:warnings test_kapu.py
