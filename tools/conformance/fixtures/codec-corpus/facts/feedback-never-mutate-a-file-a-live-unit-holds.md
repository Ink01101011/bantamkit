---
name: feedback-never-mutate-a-file-a-live-unit-holds
description: re-derive a unit's mutation on a copy from git, never in the working
  tree while that unit is still running - the orchestrator nearly clobbered an in-flight
  edit
type: feedback
created: '2026-08-22'
last_recalled: '2026-09-19'
links: []
---

Measured 2026-08-19 in bantamkit, and it nearly cost a unit's work.

**What happened.** A unit committed `075cd30` and I started re-deriving its mutation
immediately — `cp` the working-tree file to a backup, `sed` the mutation in, run the check,
`cp` back. The unit was **still running**, and while I held that backup it amended its own
commit with a newly measured figure. My restore happened to preserve that edit only because
my backup was taken *after* its write. **Ten seconds the other way and I would have silently
reverted a measurement it had just made**, and neither of us would have noticed — the commit
would simply have lacked a number its report claimed.

**Why the obvious guard does not apply.** "The unit committed, so it is done" is false: an
agent commits and then keeps working, and `git commit --amend` means the SHA you verified can
stop existing. `075cd30` is unreachable from any branch now; the real commit is `cc9882f`.

**How to apply.**

1. **Re-derive from git, not from the working tree.**
   `git show <sha>:path > /tmp/copy.py`, mutate the copy, run it. For a standalone script this
   works directly. For anything inside the installed package it does not — the venv's editable
   install resolves `bantamkit` to the main checkout, so a copied tree is never imported (a
   unit was fooled by exactly that tonight (2026-09-11) and reported identical before/after numbers).
   There, wait.
2. **Treat "the unit committed" as no signal at all.** The finished signal is its report
   arriving. Until then the working tree is its desk, not yours.
3. **Verify against the SHA in the unit's report**, not the SHA you saw in `git log` while it
   was running. Re-run the gates at the reported SHA even if you ran them ten minutes ago.

See [[feedback-verify-against-the-run-not-the-source]],
[[project-shift-2026-08-19-night]].
