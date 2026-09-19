---
name: tests-that-pick-the-input-that-cannot-fail
description: why a green test suite missed a parity bug in every case - the example
  chosen was the one where both sides agree, and three shapes of it measured in one
  review
type: feedback
created: '2026-09-05'
last_recalled: '2026-09-19'
links:
- differential-is-blind-to-symmetric-regression
- feedback-verify-against-the-run-not-the-source
- feedback-confirm-the-gate-covers-the-thing
---

Measured 2026-09-05 on the `--install` branch. Review returned ten findings; three were parity defects that BOTH runtimes' unit suites and the conformance suite passed straight through. The bug in each case was not the assertion — it was the example.

**1. The one input where two languages agree.** The refusal names the type of a config that is not an object: Python `holds str`, and the port answered `holds string`, `holds number`, `holds boolean`. Both unit tests used `[1, 2, 3]` — `list` is the ONE name in the whole vocabulary CPython and JavaScript spell identically. A parametrised case over every scalar `json.loads` can return would have caught it on the first run. Ask: of the inputs this function accepts, which one CANNOT distinguish a correct implementation from a wrong one? If that is the one in the test, the test is decorative.

**2. The combination nobody wrote a case for.** `--install` was dispatched before `--mcp-report` on one runtime and after it on the other, so `--mcp-report --install cursor` wrote a file on one and not the other. Every early-return flag had a case; no case had ever combined TWO of them. Coverage counted flags, and the defect lived in their ordering.

**3. `x is not None` where the question was membership.** A config holding `"bantamkit": null` HAS an entry, and `.get()` cannot tell that from having none — so one side rewrote the file without `--force` while the other refused, and the advertised guarantee was false exactly there. Null is the value a test author skips because it looks like absence.

**And the shape that keeps recurring:** a differential comparing the two runtimes cannot see an answer they get wrong TOGETHER. The new gates for this branch are written as LITERALS — `{python: false, node: false}` — because had both written the file, side-to-side would still have said "identical". Third instance this session; see [[differential-is-blind-to-symmetric-regression]].

**How to apply:** after writing a case, name the input that would make it fail and check it is the one you used. For a port, prefer a parametrised sweep over the value space to one hand-picked example — the hand-picked one tends to be the safe one. And when two flags each have a case, ask what happens when both are passed.
