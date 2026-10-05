"""Yield to a live installer, recover its abandoned handoff without blocking cron."""

import json
import os
from datetime import datetime

from ..log import TZ
from ..notify import incidents
from . import last_error


def waiting(ctx):
    # A failed mail delivery must still be retried after the flag has been removed.
    if any(i["scope"] == "operation:install" for i in incidents.active(ctx)):
        incidents.record(ctx, "program", "install")
    path = ctx.cfg.state_dir / "operations/install-pending"
    try:
        marker = json.loads(path.read_text())
        pid = marker["pid"]
        since = datetime.fromisoformat(marker["since"])
        age = (datetime.now(TZ) - since).total_seconds()
        live = isinstance(pid, int) and pid > 0 and _alive(pid)
    except FileNotFoundError:
        return False
    except (ValueError, TypeError, KeyError, OverflowError):
        live, age = False, 0
    if live and age <= 7200:
        ctx.log.event("round.skip", "install_pending", message="telepítés várakozik, a kör kilép", pid=pid)
        return True
    error = RuntimeError("beragadt telepítési jelző: a folyamat nem él vagy a jelző két óránál régebbi")
    ctx.log.error("round.install_pending", error)
    # Persist the incident before removing its evidence; replay sends no second mail.
    last_error.record(ctx, "install", "program", error)
    path.unlink(missing_ok=True)
    return False


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
