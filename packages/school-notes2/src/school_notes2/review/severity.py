"""Finding severity, including receipts written before severity was required."""


def is_error(finding):
    return finding.get("severity", "hiba") == "hiba"
