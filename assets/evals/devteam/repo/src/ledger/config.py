"""The only module in svc-ledger that reads os.environ.

Every tunable is a key in CONFIG_KEYS with its default beside it. docs/runbook.md
deliberately does not repeat these values: one place, one default.
"""

import os

CONFIG_KEYS = {
    "retry_max_attempts": 5,
    "retry_backoff_ms": 250,
    "settle_batch_size": 200,
    "posting_currency": "EUR",
    "report_top_n": 10,
}


class Settings:
    """Attribute access over CONFIG_KEYS, environment first."""

    def __init__(self, values):
        self.values = values

    def __getattr__(self, name):
        if name not in self.values:
            raise AttributeError(f"unknown config key: {name}")
        return self.values[name]


def load_settings():
    values = {}
    for key, default in CONFIG_KEYS.items():
        raw = os.environ.get("LEDGER_" + key.upper())
        values[key] = type(default)(raw) if raw is not None else default
    return Settings(values)
