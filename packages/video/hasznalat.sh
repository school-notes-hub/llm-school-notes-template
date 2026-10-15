#!/bin/sh
# Ugyanennek a kiadott fának a Python-környezetében; semmilyen tanulóspecifikus út nincs itt.
D="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$D${PYTHONPATH:+:$PYTHONPATH}"
exec uv run --quiet --frozen --project "$D/../school-notes2" python -m hasznalat.lanc "$@"
