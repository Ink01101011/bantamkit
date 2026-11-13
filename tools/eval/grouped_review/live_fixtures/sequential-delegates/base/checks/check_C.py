"""Fast check for task C: the module imports and top_components has the agreed shape."""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from logscan.report import top_components

signature = inspect.signature(top_components)
params = list(signature.parameters)
assert params == ["records", "level", "limit"], f"top_components parameters are {params}"
assert signature.parameters["limit"].default == 3, "limit must default to 3"
assert top_components([], "ERROR") == [], "no records must give an empty list"
print("check C: ok")
