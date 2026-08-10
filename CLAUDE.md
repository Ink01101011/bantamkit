# bantamkit

Layer discipline is strict: a change lives in exactly one layer
(docs/architecture.md). Run the suite from the repo venv:
`.venv/bin/python -m pytest runtime-py/tests -q` and keep
`.venv/bin/ruff check runtime-py` clean.

## Shift-work orchestration policy

Any multi-unit orchestration — ≥2 planned units, or any
spec→plan→implement / bugfix / code-trace job that fans out agents — MUST
run its agent spawns through the shiftwork MCP tools:

1. Plan once into a schema-valid checkpoint (convention:
   `.shiftwork/checkpoint.json`; template:
   `tools/shiftwork/example-codefix-checkpoint.json`).
2. Per unit: `shiftwork_clock_in` → spawn the subagent with the returned
   brief verbatim → `shiftwork_clock_out` with status, handoff patch,
   history entry, and accounting (tokens, duration, and the model actually
   used — the model choice is yours per role, never random, always logged).
3. On `result: escalate`, stop and ask the user. On `result: success`, the
   job is done.

Exempt: one-off ad-hoc spawns (a single search or review with no plan
behind it) — no unit to clock.
