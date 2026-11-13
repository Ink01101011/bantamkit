"""Fast check for task C: the module imports and merge_counts has the agreed shape."""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stockplan.contract import Item
from stockplan.merge import merge_counts

params = list(inspect.signature(merge_counts).parameters)
assert params == ["first", "second"], f"merge_counts parameters are {params}"
merged = merge_counts([Item("nut", 1, 1)], [])
assert isinstance(merged, list), "merge_counts must return a list"
assert all(isinstance(item, Item) for item in merged), "merge_counts must return Items"
print("check C: ok")
