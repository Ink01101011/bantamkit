---
name: prove-the-case-red-before-claiming-it-guards
description: why a conformance case that passes proves nothing, the five vacuity shapes
  found across two reviews, and the rule that a comment claiming a guard must cite
  the mutation that reddened it
type: feedback
created: '2026-09-05'
last_recalled: '2026-09-06'
links:
- differential-is-blind-to-symmetric-regression
- feedback-verify-against-the-run-not-the-source
- feedback-confirm-the-gate-covers-the-thing
- skill-audit-built-three-designs-refuted
---

2026-09-05, two reviews on one branch each found cases that were green while the thing they named was broken, and each had a comment asserting it was not vacuous. The comments were mine and were wrong.

FIVE SHAPES, all confirmed by running them:
1. NOTHING REFERENCES THE STRING. Two operator error sentences hand-duplicated 2x2 across runtimes. Corrupting BOTH in the Node build left 250 conformance cases and 446 unit tests green. A surface written twice with no case comparing it is unported by the repo's own gate.
2. THE LITERAL CANNOT TELL THE OUTCOMES APART. A case asserted `{archived: ['alpha']}`. Refusal leaves that; so does the mutant that renames the live fact OVER the archived copy and loses data. The assertion had to be on the file's CONTENT.
3. THE MUTANT DISABLES THE OTHER HALF TOO. A four-step archive/archived/restore/archived round trip stayed green with `archive` a no-op, because step 3's `restore` then also refuses and the directory ends in the same state.
4. THE CORPUS CANNOT EXPRESS THE PROPERTY. `catalogue_bytes` is defined as UTF-8 BYTES, but every description in the fixture was pure ASCII, so `len(s)` and `len(s.encode())` were the same number for all 16 skills. Mutating bytes to characters left conformance at "66 cases, 0 differed" and was caught by ONE assertion misfiled inside a JSON-formatting test. `ensure_ascii=False` — the flag that makes the two runtimes' JSON agree — was caught by NOTHING, on either gate, while the suite's own docstring claimed it was under test. A property the corpus cannot express is untested however many cases run.
5. THE SAME DEFECT THROUGH ANOTHER DOOR. A fix landed for "dedupe merges skills across versions"; the review then found version RESOLUTION built its candidate set from skills that had already survived loading, so an empty or unreadable newer directory was invisible and an older one won silently. Same wrong answer, different mechanism, and both runtimes agreed so the differential was structurally blind. After fixing one shape of a defect, ask what else reaches the same wrong state.

THE RULE: a comment claiming a case is distinguishing must name the mutation that reddens it and the count. Run it on a COPY, put the number in the commit message, and if you cannot make it red the case does not guard what you say it does. "Red but barely" — one assertion, misfiled — counts as not pinned.

SECOND CLASS, from the same reviews: docstrings that justify code with scenarios the code cannot reach, inherited by copying the INVERSE method's reasoning without re-deriving direction. `restore`'s pre-move parse is load-bearing; `archive`'s is not. `restore`'s rollback exists for a directory at the SOURCE; for `archive` that path is the DESTINATION and an earlier guard already stats it. The code can be right while every reason given for it is wrong.

See [[differential-is-blind-to-symmetric-regression]], [[feedback-verify-against-the-run-not-the-source]], [[feedback-confirm-the-gate-covers-the-thing]], [[skill-audit-built-three-designs-refuted]].
