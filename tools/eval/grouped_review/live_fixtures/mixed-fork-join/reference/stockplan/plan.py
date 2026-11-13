"""Turn two warehouses' stock into one restock order."""

from stockplan.merge import merge_counts
from stockplan.reorder import needs_reorder


def restock_plan(first, second, multiple: int = 2) -> dict[str, int]:
    """Return {sku: units to order} so each due sku reaches reorder_at * multiple."""
    merged = merge_counts(first, second)
    due = set(needs_reorder(merged))
    plan: dict[str, int] = {}
    for item in merged:
        order = item.reorder_at * multiple - item.qty
        if item.sku in due and order > 0:
            plan[item.sku] = order
    return plan
