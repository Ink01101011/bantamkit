"""Batch settlement. Drives posting through the retry wrapper."""

from ledger.config import load_settings
from ledger.errors import SettlementError
from ledger.posting import post_entry
from ledger.retry import with_retry


def settle_batch(entries):
    settings = load_settings()
    if len(entries) > settings.settle_batch_size:
        raise SettlementError(f"batch of {len(entries)} exceeds settle_batch_size")
    posted = []
    for entry in entries:
        posted.append(with_retry(post_entry, entry))
    return posted
