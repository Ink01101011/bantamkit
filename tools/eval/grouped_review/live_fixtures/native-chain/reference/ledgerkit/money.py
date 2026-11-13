"""Parse human-written money amounts into integer cents."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def parse_amount(text: str) -> int:
    """Return the amount in ``text`` as integer cents, rounding half away from zero."""
    cleaned = text.strip().replace(",", "").replace("$", "")
    if not cleaned:
        raise ValueError(f"empty amount: {text!r}")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"not an amount: {text!r}") from exc
    if not value.is_finite():
        raise ValueError(f"not a finite amount: {text!r}")
    return int((value * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
