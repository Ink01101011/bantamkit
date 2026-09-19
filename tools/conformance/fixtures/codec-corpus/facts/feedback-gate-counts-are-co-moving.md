---
name: feedback-gate-counts-are-co-moving
description: a pytest pass count is a function of repo content not of the test code
  - never quote a gate expectation without the commit it was measured at
type: feedback
created: '2026-08-21'
last_recalled: '2026-09-18'
links:
- feedback-verify-against-the-run-not-the-source
- feedback-real-probe-only
- project-bantamkit-program-backlog
- feedback-hand-the-returned-brief-not-a-path
---

Measured 2026-08-19 in bantamkit, by two parties disagreeing and **both being right**.

**The failure.** A brief told a unit *"expect 940 passed, 2 xfailed."* The unit measured
**932** in its worktree and filed the brief as wrong. I measured **940** in the main
checkout. Both numbers are correct **at their own commit**.

**The mechanism.** `git diff --name-only 5845698..3f52a86` returns seven files, **all
under `docs/`, none under `runtime-py/`** — the branch adds no test. Yet
`tests/test_field_programs.py` **parameterizes over the committed field programs in
`docs/eval-data/`**, and four of its test functions went 12 → 14 cases because the branch
added two `.py` files there. **4 × 2 = 8. 932 + 8 = 940.**

**The general shape.** A pytest pass count is not a property of the test code. It is a
**co-moving count**: a figure whose correct value is a function of the body of the
repository at the same commit. Any parameterized test that enumerates repo content makes
the suite total move when *content* moves, with no test touched and no `runtime-py/` diff.
Worse, it is **cross-artifact** — the derivation lives in the repo and the number gets
quoted in a document, a brief, or a commit message, where nothing recomputes it.

**How to apply:**
1. **Never quote a pass count bare.** Write `932 passed @ 5458059`, never `932 passed`. A
   count without its commit is an assertion about a tree the reader is not standing in.
2. **Never put a gate expectation in a brief as a fact.** Say "run the gates and report
   the count with its commit"; a hardcoded expectation makes a unit either wrong or
   distracted.
3. **When two measurements of "the same" count disagree, diff the collected nodes, not the
   test files.** `pytest -q --collect-only | grep '::' | sed 's/\[.*//' | sort | uniq -c`
   in each tree, then diff. The file-level `git diff` will show nothing and mislead you.
4. **A checker for this class must have a must-be-red case for a bare number with no
   derivation marker** — the defect appeared inside the very document that named the class.

See [[feedback-verify-against-the-run-not-the-source]], [[feedback-real-probe-only]].
