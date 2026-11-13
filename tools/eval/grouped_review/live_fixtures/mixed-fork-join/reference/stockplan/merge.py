"""Combine two warehouses' item lists into one."""

from stockplan.contract import Item, validate_item


def merge_counts(first, second) -> list[Item]:
    """Sum qty per sku, keep the larger reorder_at, return Items sorted by sku."""
    merged: dict[str, Item] = {}
    for item in [*first, *second]:
        validate_item(item)
        seen = merged.get(item.sku)
        if seen is None:
            merged[item.sku] = item
        else:
            merged[item.sku] = Item(
                item.sku, seen.qty + item.qty, max(seen.reorder_at, item.reorder_at)
            )
    return [merged[sku] for sku in sorted(merged)]
