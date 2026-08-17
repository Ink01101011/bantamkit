"""Entry validation. The only module that decides an entry is malformed."""

from ledger.errors import ValidationError

REQUIRED_FIELDS = ("amount", "ccy")


def validate_entry(entry):
    for field in REQUIRED_FIELDS:
        if field not in entry:
            raise ValidationError(f"missing field {field!r}: {entry!r}")
    if entry["amount"] == 0:
        raise ValidationError(f"amount must be non-zero: {entry!r}")
    return entry
