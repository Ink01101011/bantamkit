# svc-ledger

Double-entry ledger service. Three handlers, one settings module, no globals.

- Module map and the call order between modules: `docs/architecture.md`
- Operating procedure, escalation, and where the tunables live: `docs/runbook.md`
- Release history, newest first, with commit ids: `HISTORY.md`
- Patch files for selected commits: `patches/`
- Open incidents, including captured tracebacks: `issues/`

Handlers are resolved at import time from `src/ledger/registry.py`. Nothing else
in the service knows the handler names.
