"""Fast check for task B: the module imports and count_by_window has the agreed shape."""

import inspect
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from logscan.window import count_by_window

params = list(inspect.signature(count_by_window).parameters)
assert params == ["records", "minutes"], f"count_by_window parameters are {params}"
record = {"ts": datetime(2026, 1, 2, 3, 4, tzinfo=UTC), "level": "INFO",
          "component": "api", "message": "x"}
counts = count_by_window([record], 15)
assert isinstance(counts, dict), "count_by_window must return a dict"
assert sum(counts.values()) == 1, "one record must be counted once"
print("check B: ok")
