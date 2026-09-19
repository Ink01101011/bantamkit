---
name: job43b-review-round4-started
description: job43b review round 4 CLOSED and MERGED 2026-09-04 as d40846c - the seven
  units, the gate numbers, and the three orchestrator numbers a unit had to correct
type: project
created: '2026-09-04'
last_recalled: '2026-09-14'
links:
- feedback-orchestrator-numbers-from-recall
- merge-authorized-standing-tag-withheld
- differential-is-blind-to-symmetric-regression
- feedback-unreviewed-surface-is-the-last-rounds-fixes
---

CLOSED and MERGED 2026-09-04. `shiftwork_clock_in` answers `result: success`.

PR **#82** MERGED (squash, branch kept) as **`d40846c`** on main — 30 files, +2,241 / -256 against `952586e`. The user authorized the merge in one word after being asked once by number. Tag still NOT authorized and none was created.

Scope reviewed: `47d1c12..main` = 2,711 insertions / 163 deletions / 33 files — the true never-reviewed surface, NOT PR #81's 10,035 nor `39c5a74..main`'s 10,691.

Units and layers: I1 I2 I3 review (25 raw findings) → I3b conformance (repair the gate before measuring through it) → I4 runtime-py 3 commits → I4h hooks 3 → I5 runtime-ts 5 → I6 conformance+docs 14 → I7 gates+PR.

Gates at `8c989eb` (branch tip), run three times independently — I6, orchestrator, I7 — identical every time:
- `--all` PASS **6280 cases, 1535 byte-identical, 3271 exact-string, 1474 structural, 127 ruled-different, 0 failures** (baseline at 952586e: 6193 / 125 / 0)
- npm **446 / 446 / 0** (baseline 423)
- pytest **2168 passed, 2 skipped, 1 deselected, 3 xfailed** (baseline 2146)
- ruff clean
Per-suite all 0 differed: charsets 88, cli 73, codec 504, docread 1062, mcpreport 25, memorycli 212, recall-strings 96, shiftwork 596, statusline 52, store 186, validate 3015, wire 371.

`charsets` went 93 → 88 and that is CORRECT: H1 removed seven byte tables seven stateful codecs could never have had; two key-set cases were added back.

Eight follow-ups registered in docs/roadmap-toolbox.md row 8 as **(q)–(x)**: (q) hook ledger race, (r) charsets.ts platform-dependence — a red PREDICTED not observed, CI is the arbiter, (s) damaged-member sentence, (t) bzip2 date-format styles, (u) two private CPython methods bound at import, (v) column ceiling bounds a row not a document, (w) duplicate cell reference drops a cell silently, (x) uncapped eviction-protected class, a decision not a defect. (o) amended with the 12-of-900 wave-dash U+301C vs U+FF5E measurement.

THREE ORCHESTRATOR NUMBERS A UNIT HAD TO CORRECT — see [[feedback-orchestrator-numbers-from-recall]]:
1. The repo has **23 tags, not 22**. `git for-each-ref refs/tags | wc -l` = 23, newest v0.25.0 dated 2026-08-24 which predates job43's merge — so "no tag was created" HOLDS, but I quoted 22 into every brief without re-measuring.
2. FIXLIST's "22 deduped, three pairs" is really **23 rows and two pairs**; 22 is the post-H2 allocation count.
3. docs/conformance.md's measurement is provenanced at `1cf8df2`, not the tip.

The deepest finding of the round is [[differential-is-blind-to-symmetric-regression]].

Post-merge done: `git pull --ff-only`, `npm run build --prefix runtime-ts` (tsc clean). The user must reconnect via `/mcp` for the live server to pick up the new dist.
