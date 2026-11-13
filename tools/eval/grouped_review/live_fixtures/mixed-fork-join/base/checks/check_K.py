"""Fast check for task K: the contract imports and has the agreed shape."""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stockplan.contract import Item, validate_item

item = Item("bolt", 5, 2)
assert (item.sku, item.qty, item.reorder_at) == ("bolt", 5, 2), "Item fields are sku, qty, reorder_at"
params = list(inspect.signature(validate_item).parameters)
assert params == ["item"], f"validate_item parameters are {params}, expected ['item']"
assert validate_item(item) is item, "validate_item must return the item it accepted"
print("check K: ok")
