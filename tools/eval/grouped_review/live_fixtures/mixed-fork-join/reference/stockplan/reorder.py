"""Pick the items that have fallen to their reorder threshold."""

from stockplan.contract import validate_item


def needs_reorder(items) -> list[str]:
    """Return the sorted skus whose qty is at or below reorder_at."""
    due = {item.sku for item in items if validate_item(item).qty <= item.reorder_at}
    return sorted(due)
