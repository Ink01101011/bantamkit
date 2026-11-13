"""Summarise an invoice: subtotal, tax and total in cents."""

from decimal import ROUND_HALF_UP, Decimal

from ledgerkit.lines import line_total


def invoice_summary(lines, tax_rate_pct) -> dict:
    """Total ``(quantity, unit_price, discount_pct)`` lines and add tax on the subtotal."""
    subtotal = 0
    for quantity, unit_price, discount_pct in lines:
        subtotal += line_total(quantity, unit_price, discount_pct)
    rate = Decimal(str(tax_rate_pct))
    tax = int((subtotal * rate / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return {"subtotal": subtotal, "tax": tax, "total": subtotal + tax}
