---
name: differential-is-blind-to-symmetric-regression
description: why a two-runtime conformance case stays green through a real regression,
  three measured instances, and what a gate must pin instead
type: feedback
created: '2026-09-04'
last_recalled: '2026-09-11'
links:
- feedback-verify-against-the-run-not-the-source
- project-mutation-defeated-by-round-numbers
- npm-publish-0-26-0-blocked-on-login
---

A conformance case that only compares Python's answer to Node's answer CANNOT see a regression that lands in both. Measured in job43b, 2026-09-04, and again on 2026-09-05.

**Why:** CLAUDE.md requires a fix to land in BOTH runtimes in the same job. That is right — but it means the honest way to prove a case has teeth (revert the fix, watch it go red) is a JOINT revert, and a joint revert leaves the two sides AGREEING. Unit I6 reverted M2/M5 in both runtimes: both then agreed the workbook was unreadable, every side-to-side case stayed green, and the differential noticed nothing. A side-to-side case proves **parity**; only a checked-in **literal** or a per-side **invariant** proves correctness.

**Second shape:** three `charset-*.eml` fixtures sent their bytes `8bit`, so a raw invalid-UTF-8 sequence sat in the file. `_text_kind` decodes the head through an incremental UTF-8 decoder BEFORE looking for a MIME header, so the container sniffed `unknown` and both runtimes refused the whole file. Those cases had been green for rounds — pinning a REFUSAL, never reaching a codec. `quoted-printable` fixed it and docread went 1048 → 1060 cases.

**Third shape, 2026-09-05, and the cleanest demonstration yet — the harness itself makes the regression symmetric.** `assets_digest` differed between the PUBLISHED artifacts (wheel `sha256:fa8372f6…` over 98 files, npm `sha256:d47dcf4b…` over 87) because `pip install` byte-compiles the pack's `.py` fixtures and the walk swept `__pycache__` up. A new conformance session pointed BOTH runtimes at one polluted pack — so both counted the `.pyc` files, both agreed, and the cross-runtime case passed at `sha256:e740af3f…` over 90 on both sides while both were wrong. Only `a __pycache__ does not move assets_digest — the reference` / `— the port`, comparing each side against ITS OWN clean-pack answer, went red. The real defect was asymmetric only because just one ecosystem's installer creates the directory; a shared fixture cannot reproduce that asymmetry.

**How to apply:** when a fix lands in both runtimes, add a per-side invariant or a checked-in literal alongside the differential, and say which one you watched fail. When a case passes, ask what would make it fail — if the answer is "one side drifts", it does not cover a symmetric bug; if the answer is "the file becomes unreadable", check the file is readable TODAY (2026-09-06). And when the asymmetry in the wild comes from the ENVIRONMENT rather than from the code, a shared fixture will not reproduce it at all.
