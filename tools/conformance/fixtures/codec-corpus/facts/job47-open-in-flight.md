---
name: job47-open-in-flight
description: job47 is OPEN as of 2026-09-11 - the memory_dream self-merge and the
  modelRefusal fail-open, where its checkpoint and prep probe live, and the decision
  already settled so a fresh context does not reopen it
type: project
created: '2026-09-11'
last_recalled: '2026-09-19'
links:
- project-bantamkit-pending-user-decisions
- feedback-prep-probe-before-planning
- every-change-ships-to-npm-not-just-to-main
- feedback-verify-against-the-run-not-the-source
---

job47 started 2026-09-11 and is IN FLIGHT. Resume from .shiftwork/checkpoint-job47.json (9 units; shiftwork_status for the cursor) and .shiftwork/notes-job47/prep-probe.md (186 lines of measured findings - read it, do not re-derive). Branch fix/job47-dream-self-merge-and-modelrefusal off 13244f4.

SCOPE: roadmap-toolbox row 13 (memory_dream self-merges when one directory is bound as both layers; it archived 20 of 20 of the user's real profile facts on 2026-09-10) and (hh) item 2 (a non-list job.roles.<role>). Still open afterwards and deliberately out of scope: (gg) the bare-pip remedy, (hh) item 1 token_ledger's OSError asymmetry, build_identity's undeclared cross_runtime/runtime fields, (ab) docmanifest.py missing from CORE_MODULES, roadmap row 6's threshold.

THE DECISION IS SETTLED - do not reopen it. Row 13 leaves the fixing unit a choice: drop the duplicate layer, or refuse with a named error. It is DROP THE DUPLICATE LAYER, routing into the no-profile-layer outcome that already ships on both sides. Not preference: the shipped sentence is already literally true for this case, the status set is a CLOSED list pinned in five places (component.py:129, component.ts:180, docs/memory.md:388 and :569, docs/eventlog.md:294), and memory_dream has no refusal vocabulary at all - a named error would be its first-ever exception, invented twice.

TWO THINGS THE REGISTER GETS WRONG, found by the prep probe:
1. (hh) item 2 is worse than "the port fails open". Node does not merely return null - it COMPLETES the clock-out: status set, cursor advanced, accounting line written. And the reference does not fail closed either: str/dict refuse with a names list mangled into single characters, while int/null/bool raise an uncaught TypeError: can only join an iterable instead of the structured _error J46-10 ruled. Both sides need fixing.
2. dreamOutcome / memory_dream / Memory.layered have ZERO differential coverage. grep -rn "dreamOutcome|dream_outcome|memory_dream|no-profile-layer" tools/conformance/ returns nothing; the dream suite drives only low-level dream(project, profile, dry_run) at ref/dream_ref.py:151. Extending the driver is the LARGER half of the fix - a guard in Memory.layered is unreachable by the runner as it stands.

Gate baseline re-derived at 13244f4 (job46's closeout says 7517 cases; it is 7493 here - counts co-move with repo content, so re-derive, never quote): pytest 2829 passed / ruff clean / npm 906 of 908 / --all 7493 cases, 156 ruled-different, 0 failures. Release target 0.32.0, free on npm and PyPI; 0.31.0 live on both.

Also uncommitted on this branch and unrelated: docs/superpowers/specs/2026-09-11-scope-lock-design.md, a draft past review round 1, pending round 2.
