"""The item contract every stockplan module shares."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    """One stock-keeping unit in one place: how many are on hand and when to reorder."""

    sku: str
    qty: int
    reorder_at: int


def validate_item(item: Item) -> Item:
    """Return ``item`` unchanged, or raise ValueError when it breaks the contract."""
    if not item.sku or item.sku != item.sku.strip():
        raise ValueError(f"sku must be non-empty with no outer whitespace: {item.sku!r}")
    if item.qty < 0:
        raise ValueError(f"qty must not be negative: {item.qty}")
    if item.reorder_at < 0:
        raise ValueError(f"reorder_at must not be negative: {item.reorder_at}")
    return item
