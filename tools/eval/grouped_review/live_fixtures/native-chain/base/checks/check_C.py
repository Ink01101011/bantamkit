"""Fast check for task C: the module imports and invoice_summary has the agreed shape."""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledgerkit.invoice import invoice_summary

params = list(inspect.signature(invoice_summary).parameters)
expected = ["lines", "tax_rate_pct"]
assert params == expected, f"invoice_summary parameters are {params}, expected {expected}"
summary = invoice_summary([(1, "1", 0)], 0)
assert isinstance(summary, dict), "invoice_summary must return a dict"
assert set(summary) == {"subtotal", "tax", "total"}, f"unexpected keys {sorted(summary)}"
print("check C: ok")
