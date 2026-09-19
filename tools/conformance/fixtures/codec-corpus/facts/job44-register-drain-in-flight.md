---
name: job44-register-drain-in-flight
description: job44 outcome - what draining the roadmap register actually found, why
  a two-runtime differential could not see any of it, and what is waiting on the user's
  publish decision
type: project
created: '2026-09-06'
last_recalled: '2026-09-19'
links:
- merge-authorized-standing-tag-withheld
- differential-is-blind-to-symmetric-regression
- tests-that-pick-the-input-that-cannot-fail
- feedback-confirm-the-gate-covers-the-thing
---

**CLOSED 2026-09-06 at `09c8716`, branch `fix/job44-register-drain`, 2 commits, 52 files, +7872/-348. Version 0.29.2 in both files. NOT published, NOT tagged, NOT merged — the user reserved the publish decision.**

21 units. Four gates at `09c8716`: pytest 2430, ruff clean, npm 608/606/0/2, conformance 6724 cases / 149 ruled-different / 0 failures on Node v25.2.1.

**The finding that outlives the job: a two-runtime differential cannot see a symmetric defect, and this was measured four independent ways in one night.**

- U16's review found three HIGH defects in the job's own work; all three were symmetric, so all 6,662 side-to-side cases stayed green through them. It found them by building inputs and measuring, not by comparing sides.
- F3 then applied each fix's mutation to BOTH runtimes and ran the baseline suite: invisible, 1,107 cases / 0 failures, four times over.
- U18 appended the same string to both sides of ten CJK codecs: 12 rulings green, 10 match counts green, 30 anchor literals red.
- U3 removed the `lexists` guard from both sides: both mutants AGREED on a sentence false about a move nobody attempted.

**A ruling proves only that the two sides still DIFFER. A bare differential proves only that they still AGREE. Neither anchors a value. Every parity case needs a typed literal beside it.**

**The register was written from code reading, and measurement corrected it almost everywhere it was touched:** mhtml was NOT already bounded; (z)'s "lands on top of the link" was wrong; (s) named an unreachable mechanism while a real divergence existed from a different cause (Apple's libz vs Node's bundled zlib, 803/6306 on macOS, 0 against stock madler); (o)'s ten CJK counts do not reproduce and are internally impossible, and its WAVE DASH is eight characters not one; (v) was closed against the wrong door — the budget bounded the rendering while the parse stayed open, 143,935 B on disk still costing 2,290.8 MB RSS.

**Register hygiene failed twice and neither was caught by a gate:** the orchestrator itself edited a record in place while clearing a gate, and `amendguard`'s `what_this_is` claims to cover "the register" while `amend_only` does not list it. Registered as (bb), deliberately unresolved — adding the file reds 5 hunks of which 3 are legitimate closures, and `test_served_tool_count_records.py:120` reads the same list as an EXEMPT set.

Still open with reasons: #5, #6, #10 (features, wrong vehicle for a patch), #12 (date-gated to 2026-09-08), #9's new read-ledger matcher defect (registered by U11, measured inert steering), (q) (by ruling), (r) (fixed; unconfirmable without Windows), (s) (re-worded, unpinnable), (x) (a decision), (aa), (bb).

See [[merge-authorized-standing-tag-withheld]], [[tests-that-pick-the-input-that-cannot-fail]], [[differential-is-blind-to-symmetric-regression]].
