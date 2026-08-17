# 142 — settlement aborts on a zero-amount entry

Reported by ops on 2026-08-02 against `main` (`9f2c1ab`). One entry in a batch
of 40 carried `amount: 0`; the whole batch aborted after the wrapper exhausted
its attempts. Captured traceback, verbatim from the worker log:

```
Traceback (most recent call last):
  File "src/ledger/settle.py", line 15, in settle_batch
    posted.append(with_retry(post_entry, entry))
  File "src/ledger/retry.py", line 17, in with_retry
    raise last
  File "src/ledger/posting.py", line 9, in post_entry
    validate_entry(entry)
  File "src/ledger/validate.py", line 13, in validate_entry
    raise ValidationError(f"amount must be non-zero: {entry!r}")
ledger.errors.ValidationError: amount must be non-zero: {'amount': 0, 'ccy': 'EUR'}
```

Ops question: which change put this check in, and should a caller bug really
burn the whole attempt budget? Runbook says a malformed entry is never retried
past the wrapper's budget, so behaviour matches the runbook; the argument is
about whether the budget should apply at all.
