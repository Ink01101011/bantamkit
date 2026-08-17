import pytest

from ledger.errors import ValidationError
from ledger.posting import post_entry


def test_post_entry_rejects_zero_amount():
    with pytest.raises(ValidationError):
        post_entry({"amount": 0, "ccy": "EUR"})


def test_post_entry_converts_foreign_currency():
    assert post_entry({"amount": 10, "ccy": "USD"})["status"] == "converted"
