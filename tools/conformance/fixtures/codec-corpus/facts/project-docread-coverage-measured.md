---
name: project-docread-coverage-measured
description: what bantamkit's file reader can actually hand back after job29 - refusal
  rate 99.85 to 11.81 percent, and non-UTF-8 is NOT the remaining lever, it is worth
  two files
type: project
created: '2026-08-22'
last_recalled: '2026-09-18'
links: []
---

Measured 2026-08-21 by job29 units I and J, then **re-derived independently** by
the register unit, which contradicted ten of the relayed figures. Numbers here
are the re-derived ones.

**The baseline was far worse than anyone stated.** Before this job `extract()`
could hand back **76 of 49,556 files — 0.15%** — all of them `html`. Refusal
rate was **99.85%**, not the ~89% my brief claimed. After: **88.19%**, 43,629
text files yielding **5,577,850** rows, zero omissions raised on the real corpus.

**Kind census of the real corpus** — the denominator for any "all mime" claim:
text 43,629 / unknown 3,923 / empty 964 / png 848 / html 76 / gzip 61 / gif 48 /
zip 6. **Zero xlsx, docx, pdf, mhtml, doc or rtf exist in that corpus at all.**
The module was built around seven extractors; six of them have no file to read
on this machine, and the container nobody wrote a reader for was 88% of it.

**THE "NON-UTF-8 IS THE LARGEST REMAINING LEVER" CLAIM IS REFUTED.** I asserted
it twice, including to the user. Measured across the deduplicated union: of
**4,809** `unknown` files, **4,799 carry a NUL in the head**, **0 carry a UTF-16
BOM**, 8 are binary under every codec, and **exactly 2 are recoverable** (one
`.csv`, one `.txt`, both cp1252). An encoding-detection unit would be worth
**two files**. Do not open it.

**A denominator I published was a double count.** "116,529 text files across
three roots" summed `~/Documents/Claude/Projects` with `~/Documents`, and the
first is a SUBTREE of the second. Deduplicated: **72,902**. The size-cap claims
survive with the corrected denominator (16 MiB covers 72,900 of 72,902; 0 of
72,902 hit the strict-decode tail), the denominators do not.

**The size-cap benchmark figures are themselves fixture artifacts** — peak memory
moved 68.6 → 109.8 MiB at the SAME cap with nothing changed but the fixture's
line width. Only the **4.00× ratio** between a 16 MiB and a 64 MiB cap is a
property of the cap. This is [[project-mutation-defeated-by-round-numbers]] in a
figure I would have published as a measurement.

See [[project-real-corpus-denominator]], [[feedback-orchestrator-numbers-from-recall]].
