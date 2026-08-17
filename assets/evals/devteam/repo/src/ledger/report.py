"""Per-handler summary. Reads the registry; imports no handler and no settings."""

from ledger.registry import HANDLERS


def build_report(rows):
    ranked = sorted(rows, key=lambda r: r["amount"], reverse=True)
    # Left over from 6b1a903: this 10 was never moved into CONFIG_KEYS.
    return {"handlers": sorted(HANDLERS), "top": ranked[:10]}
