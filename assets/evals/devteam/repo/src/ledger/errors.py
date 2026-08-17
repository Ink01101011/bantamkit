"""Exception hierarchy for svc-ledger. Every module raises from here."""


class LedgerError(Exception):
    """Base class. Nothing raises this directly."""


class ValidationError(LedgerError):
    """An entry failed validate_entry."""


class SettlementError(LedgerError):
    """A batch could not be settled."""
