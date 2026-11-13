"""Fast check for task A: the module imports and parse_line has the agreed shape."""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from logscan.parse import parse_line

params = list(inspect.signature(parse_line).parameters)
assert params == ["line"], f"parse_line parameters are {params}, expected ['line']"
record = parse_line("2026-01-02T03:04:05Z INFO api: started")
assert isinstance(record, dict), "parse_line must return a dict for a well-formed line"
assert set(record) == {"ts", "level", "component", "message"}, f"unexpected keys {sorted(record)}"
print("check A: ok")
