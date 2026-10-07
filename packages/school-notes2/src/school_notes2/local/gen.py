"""`sn gen` (plan 3.2, 3.3/5): one paid image generation through the host ledger (≤ 3 attempts
per image, the monthly and school-year budgets apply), `--settle` and `--grant`.

Every call first settles the ledger's unknown-outcome (interrupted) attempts older than
24 hours; `--settle` does only that. `--grant` opens one new frame of attempts for an image
whose 3 attempts are used up – only on the owner's explicit word; at most one grant per
image and day (the request id is the date)."""

import json
from pathlib import Path

from ..images import generate
from .common import today


def run(local, figure_id: str | None, note: Path | None = None, *, settle: bool = False,
        grant: bool = False) -> int:
    settings = local.image_settings()
    settled = generate.settle_unknown(settings, log=local.steps)
    for item in settled:
        print(f"rendezve: {item['job']} ({item['state']}, {item['cost_usd']} USD)")
    if settle:
        local.record("gen", "settled", settled=len(settled))
        return 0
    if grant:
        found = generate.grant(settings, figure_id, f"helyi-{today()}")
        if found is None:
            print(f"{figure_id}: nincs a képledgerben; nincs mit engedélyezni")
            return 1
        value, new = found
        print(json.dumps({"grant": value, "new": new}, ensure_ascii=False, indent=1))
        local.record("gen", "granted" if new else "already-granted", target=figure_id)
        return 0
    text = note.read_text(encoding="utf-8").strip() if note else None
    result = generate.generate(settings, figure_id, text, log=local.steps)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    local.record("gen", result["state"], target=figure_id, cost_usd=result.get("cost_usd"),
                 attempt=result.get("number"))
    return 0 if result["state"] in ("generated", "accepted") else 1
