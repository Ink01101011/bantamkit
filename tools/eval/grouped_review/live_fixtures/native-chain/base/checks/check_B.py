"""Fast check for task B: the module imports and line_total has the agreed shape."""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledgerkit.lines import line_total

signature = inspect.signature(line_total)
params = list(signature.parameters)
expected = ["quantity", "unit_price", "discount_pct"]
assert params == expected, f"line_total parameters are {params}, expected {expected}"
assert signature.parameters["discount_pct"].default == 0, "discount_pct must default to 0"
assert isinstance(line_total(1, "1"), int), "line_total must return an int"
print("check B: ok")
