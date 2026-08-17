import pytest

from ledger.errors import SettlementError
from ledger.settle import settle_batch


def test_settle_batch_rejects_oversized_batch():
    with pytest.raises(SettlementError):
        settle_batch([{"amount": 1, "ccy": "EUR"}] * 201)
