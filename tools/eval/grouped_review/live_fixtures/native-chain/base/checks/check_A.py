"""Fast check for task A: the module imports and parse_amount has the agreed shape."""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledgerkit.money import parse_amount

params = list(inspect.signature(parse_amount).parameters)
assert params == ["text"], f"parse_amount parameters are {params}, expected ['text']"
assert isinstance(parse_amount("1"), int), "parse_amount must return an int"
print("check A: ok")
