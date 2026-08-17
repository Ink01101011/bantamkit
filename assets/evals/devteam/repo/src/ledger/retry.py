"""Retry wrapper. Reads its attempt count from settings, never from a constant."""

import time

from ledger.config import load_settings


def with_retry(fn, *args):
    settings = load_settings()
    last = None
    for _attempt in range(settings.retry_max_attempts):
        try:
            return fn(*args)
        except Exception as exc:
            last = exc
            time.sleep(settings.retry_backoff_ms / 1000)
    raise last
