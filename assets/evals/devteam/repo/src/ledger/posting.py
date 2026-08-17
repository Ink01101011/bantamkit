"""Post one entry to the ledger. Validates before writing; raises nothing itself."""

from ledger.config import load_settings
from ledger.validate import validate_entry


def post_entry(entry):
    settings = load_settings()
    validate_entry(entry)
    if entry["ccy"] != settings.posting_currency:
        return {"status": "converted", "ccy": settings.posting_currency}
    return {"status": "posted", "ccy": entry["ccy"]}
