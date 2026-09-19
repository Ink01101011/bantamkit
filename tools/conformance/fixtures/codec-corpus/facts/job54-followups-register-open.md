---
name: job54-followups-register-open
description: job54 CLOSED 2026-09-19 - 0.34.3 fully out and measured byte-identical
  on npm and PyPI, what the ~/.bantamkit gitignore fix actually turned out to be,
  the open register F1-F5 plus G1-G2 for the next job, and three release-probe traps
  worth reusing
type: project
created: '2026-09-18'
last_recalled: null
links:
- bantamkit-open-followups-after-job53
- job53-known-issues-open
- merge-authorized-standing-tag-withheld
- otp-prompts-cannot-be-answered-in-the-bang-channel
- feedback-verify-against-the-run-not-the-source
---

**CLOSED 2026-09-19.** `shiftwork_clock_in` on `.shiftwork/checkpoint-job54.json` answers `result: success`. 0.34.3 is out on all four channels: main `2b5c2ad`, npm, PyPI, annotated tag `v0.34.3` on the merge commit, GitHub release not a draft. Eight units: J54-1..4, J54-3b (inserted mid-job to clear a review blocker), J54-5 (two passes), J54-6, J54-7.

**MEASURED, re-derived by the orchestrator, not quoted from a unit:** the npm tgz, the PyPI wheel and the PyPI sdist are each **byte-identical** to J54-6's local builds (`cmp` silent; neither PyPI file yanked). The headline behaviour was proven in the **published** package, not the repo: `npx -y bantamkit-mcp@0.34.3 --install cursor` into a fresh throwaway HOME writes `~/.bantamkit/.gitignore` with the exact 88-byte literal (sha256 `7f833b9d…`), and into a HOME where `.bantamkit` pre-existed it writes none while still landing the install tree.

**What the register items turned out to be, beyond what was filed:**
- **N2 was worse than "stale".** M47's anchor matched both `skill_audit`'s and `token_ledger`'s `return _noted(result.as_json())`, and `replace(...,1)` takes the first — so that mutation had been mutating the WRONG TOOL, in a spec file that is about `skill_audit`. M51 matched 0 because `bantamkit_read` is retired from the roster (handler still at `mcpserver.py:~1706` marked DORMANT, absent from all 12 `_from_manifest(`).
- **#5 had a second creator nobody had named,** symmetric in both runtimes: `MemoryStore._ensure_dirs`/`ensureDirs` took the ignore decision about `root.parent`, which is the `.bantamkit` for exactly one shape of root. Not hypothetical — `~/.bantamkit` holds an empty `facts/`+`archive/` from an old `--store ~/.bantamkit` run. Also measured: a FAILED `npm install --prefix` still leaves the prefix on disk, so the decision is applied after the installer returns either way.
- **The fix shipped against a doc stating the old rule.** J54-5 blocked the job on it; J54-3b corrected `docs/memory.md` and `docs/install.md`. A behaviour change is not done when `docs/porting.md` alone is amended.

**OPEN REGISTER for the next job:**
- **F1** — the conformance total is a function of the LIVE gitignored project memory store: the `codec` suite builds its corpus from it, 3 cases per fact, so 59/60/61 facts give 8166/8169/8172 with no code change. Cases are added, not dropped, and the shrink direction is guarded. **Never quote `PASS: N cases` as a gate expectation; `0 failures` is the gate.** Fix: freeze the codec corpus the way `tokenledger`'s already is.
- **F2** — the `tools/` half of the new lint gate has **no pinned rule set**. The only ruff config is `runtime-py/pyproject.toml`, so `tools/` runs on ruff's defaults: **413 rules against runtime-py's 153**. That is why PIE810/PLW1510/EXE001/RUF100/FURB167 fire there at all, and it means `pip install -U ruff` can redden `CLAUDE.md`'s gate with no repo change. Fix: a root `ruff.toml`.
- **F3** `d0049d4` spans Layer 1 and Layer 5 in one commit. **F4** `b1eff0a`'s message claims no other tool file carries a shebang; three do, all `+x`. **F5** `test_the_tool_is_served_eleventh_…` asserts `order[9]`.
- **G1** `docs/conformance.md:435,439` and `docs/record-vs-pointer.md:314-315` still name the old narrow lint gate in their provenance stamps. **G2** `runtime-py/dist/` still holds 0.31.0/0.32.0/0.32.1 artifacts from before the `dist-*/` convention.
- **For the user, not a defect:** the notes were baselined at `6666d8b` while tag `v0.34.2` is `ca67a37`. Tag-to-tag, three more non-shipping paths moved, so the notes claim LESS than shipped. Decide whether "release notes cover tag to tag" becomes a convention.

**THREE PROBE TRAPS worth reusing:** (1) re-deriving the "10 ruff findings" by copying `runtime-py/pyproject.toml` next to an extracted `tools/` tree gives **51**, because the real gate has no config there; (2) probing the ignore behaviour through a clean-room install's `dist/cli.js` **directly** shows nothing — `--install` from an existing install records it and never runs `npm install --prefix`, so only the npx path fires that creator; (3) **npmjs.com's website served the old version's page for over 18 minutes** after publish while `npm view` was correct throughout — the PyPI `max-age=600` trap with a longer TTL. Re-probe before reporting a mismatch.

**Still the user's alone:** `npm publish` (the account is `two-factor auth: auth-and-writes`, so every publish needs an OTP and must run in a real TTY) and the PyPI upload. **Still waiting on the user:** ruleset 23413860 keeps its `update` rule, so every merge needs `gh pr merge N --merge --admin`; the prepared body is `.shiftwork/notes-job53/ruleset-put.json`.

Related: [[bantamkit-open-followups-after-job53]], [[job53-known-issues-open]], [[merge-authorized-standing-tag-withheld]], [[otp-prompts-cannot-be-answered-in-the-bang-channel]], [[feedback-verify-against-the-run-not-the-source]].
