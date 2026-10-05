"""One shared monthly threshold notice and a short completion budget line."""

from decimal import Decimal

from ..images import budget
from ..notify import Notice, pending


def usage(ctx):
    settings = ctx.image_settings()
    return budget.spent_in_month(settings.ledger(), settings.today()), settings.monthly_usd, settings.today()


def threshold(ctx):
    if not hasattr(ctx.image_settings(), "today"):
        return
    spent, cap, day = usage(ctx)
    if cap is not None and spent > cap * Decimal("0.8"):
        # All learners share the spending cap and the mail receipt identity.
        pending.send(ctx, Notice("images", f"image-threshold:{day:%Y-%m}", "", "images", "Képkeret",
            f"A havi képköltés átlépte a keret 80%-át: {spent:.2f}/{cap:g} USD.", ""))


def summary(ctx, task):
    if not hasattr(ctx, "image_settings") or not hasattr(ctx.image_settings(), "today"):
        return
    spent, cap, _ = usage(ctx)
    if cap is not None and spent > cap * Decimal("0.8"):
        task.update(image_budget_note=f"képkeret: {spent:.2f}/{cap:g} USD")
