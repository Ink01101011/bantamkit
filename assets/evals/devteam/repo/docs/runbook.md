# Runbook

Attempt counts, backoff intervals and batch sizes are **not written on this
page** and never will be. Every one of them is a key with its default in
`src/ledger/config.py` — read that file for the current value. Do not answer an
operational question about a number from this page; it will be stale.

Escalation: three consecutive settlement failures page the on-call. Foreign
currency entries are converted, not rejected. A malformed entry is a caller bug
and is never retried past the wrapper's own attempt budget.
