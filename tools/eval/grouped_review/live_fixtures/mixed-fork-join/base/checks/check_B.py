"""Fast check for task B: the module imports and needs_reorder has the agreed shape."""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stockplan.contract import Item
from stockplan.reorder import needs_reorder

params = list(inspect.signature(needs_reorder).parameters)
assert params == ["items"], f"needs_reorder parameters are {params}, expected ['items']"
assert needs_reorder([Item("nut", 1, 9)]) == ["nut"], "an item far below its threshold reorders"
print("check B: ok")
