# Architecture

The three entry points are the handlers listed in `src/ledger/registry.py`.

- `settle.py` drives a batch. It wraps `posting.post_entry` in
  `retry.with_retry`, and raises its own error when a batch is too large.
- `posting.py` writes one entry. It validates first, via
  `validate.validate_entry`, and defines no exception of its own.
- `report.py` renders a summary. It reads the registry and imports no handler.
- `validate.py` is the only module that decides an entry is malformed.
- `errors.py` defines every exception class in the service. No other module
  declares one.

Every tunable is a key in `src/ledger/config.py`; that module is the only one
that touches `os.environ`. Modules ask `load_settings()` for values, so an
attribute read on a `Settings` object is how you tell that a module consumes a
config key.
