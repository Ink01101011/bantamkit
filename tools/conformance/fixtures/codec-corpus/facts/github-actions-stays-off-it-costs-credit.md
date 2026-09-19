---
name: github-actions-stays-off-it-costs-credit
description: GitHub Actions must stay off on bantamkit because it costs the user credit
  - what the local gates are, and what the one authorised window on 2026-09-05 cost
  and found
type: feedback
created: '2026-09-04'
last_recalled: '2026-09-11'
links:
- feedback-real-probe-only
- npm-publish-0-26-0-blocked-on-login
- tests-that-pick-the-input-that-cannot-fail
- differential-is-blind-to-symmetric-regression
---

The user ruled 2026-09-04: GitHub Actions must stay OFF on bantamkit — "ปิดการรัน CI github ไปเลยมันติด credit". It consumes their credit, which is the same budget the whole token-reduction effort is about. Re-ruled 2026-09-05 after one authorised window: "ปิด CI กลับไปก่อน แล้วอัปเดต memory ด้วยให้รันอ่าน local แทน".

**State: OFF.** `gh workflow disable ci.yml`; `state: disabled_manually`, workflow id 329302971. `.github/workflows/ci.yml` is unchanged on disk — the switch is server-side, so re-enabling is `gh workflow enable ci.yml` and needs no commit.

**How to apply: never re-enable without being asked, and when asked, SAY THIS FIRST.** On 2026-09-05 the user said "ทำให้ CI รันได้อีกที" and I enabled it without mentioning that it had been switched off deliberately for cost — the reason was in this very memory and I did not recall it. They learned the cost only when they asked, hours later, "CI หมายถึงรัน github ไหม". Asking is authorisation; it is not a reason to skip telling them what it costs.

**THE LOCAL GATES ARE THE SUBSTITUTE.** Run all four before any push and report the counts; that is what replaces CI, not a promise that CI would pass:

    node tools/conformance/run.mjs --all
    .venv/bin/python -m pytest runtime-py -q
    .venv/bin/ruff check runtime-py
    npm test --prefix runtime-ts

**Local gates run one platform and one dependency set, and that is their known blind spot.** Two cheap ways to widen it WITHOUT Actions, both used successfully on 2026-09-05:
- `mise` has node 18/20/22/25 installed. `~/.local/share/mise/installs/node/<v>/bin/node` runs the whole Node suite and the conformance harness, and it reproduced a Windows CI failure (`sync-assets`, a timing race) on node 18 with no runner at all.
- A scratch venv resolving dependencies FRESH (`python -m venv … && pip install -e "runtime-py[dev,mcp]"`) reproduces CI's versions. The repo venv is pinned at `mcp` 2.0.0 while a fresh install takes 2.1.1, and that one difference accounted for a CI failure that no laptop could see.

**WHAT THE 2026-09-05 WINDOW COST AND FOUND, so the trade is on record.** 15 runs, 112 jobs, 338.7 ubuntu minutes and 293.6 windows minutes — windows bills at 2x, so ~926 billable minutes. It found 24 failing cases invisible locally, a conformance suite that had NEVER completed on Windows (it crashed in `charsets.mjs`), CPython and Node version drift that changed real behaviour, and three of my own mistakes that local runs could not detect.

The information was worth having; **15 runs was not.** Most were one fix pushed immediately. Batch every change into one push before spending a run, and report the minutes each time.
