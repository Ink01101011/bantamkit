"""Price one invoice line."""

from decimal import ROUND_HALF_UP, Decimal

from ledgerkit.money import parse_amount


def line_total(quantity: int, unit_price: str, discount_pct: int = 0) -> int:
    """Return quantity x unit price in cents, less a whole-percent discount."""
    if quantity <= 0:
        raise ValueError(f"quantity must be positive, got {quantity}")
    if discount_pct < 0 or discount_pct > 100:
        raise ValueError(f"discount must be within 0..100, got {discount_pct}")
    gross = quantity * parse_amount(unit_price)
    discount = (Decimal(gross) * discount_pct / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return gross - int(discount)
