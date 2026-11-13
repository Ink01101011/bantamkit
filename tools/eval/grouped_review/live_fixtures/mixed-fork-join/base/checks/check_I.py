"""Fast check for task I: the module imports and restock_plan has the agreed shape."""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stockplan.plan import restock_plan

signature = inspect.signature(restock_plan)
params = list(signature.parameters)
assert params == ["first", "second", "multiple"], f"restock_plan parameters are {params}"
assert signature.parameters["multiple"].default == 2, "multiple must default to 2"
assert restock_plan([], []) == {}, "no items must give an empty plan"
print("check I: ok")
