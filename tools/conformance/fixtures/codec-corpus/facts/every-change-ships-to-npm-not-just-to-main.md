---
name: every-change-ships-to-npm-not-just-to-main
description: the user requires every bantamkit fix or feat to be published to npm
  as part of the same job, merging to main is not done
type: feedback
created: '2026-09-05'
last_recalled: '2026-09-19'
links:
- npm-publish-0-26-0-blocked-on-login
- merge-authorized-standing-tag-withheld
- feedback-ship-it-working-and-measured
- otp-prompts-cannot-be-answered-in-the-bang-channel
---

**Standing instruction given 2026-09-05, right after the first npm publish landed.** Their words: *"จดไว้ด้วยต่อไป ทำอะไร fix/feat หรืออะไรก็ตามต้อง publish ด้วย"*.

**A bantamkit job is not finished when it merges to main. It is finished when the change is live on npm.** This extends [[feedback-ship-it-working-and-measured]] one step further out: "working and measured" now has to mean working in the artifact a stranger installs, not only in the working tree.

**What this adds to every fix/feat job, on top of review-then-merge:**

1. Bump the version in BOTH places — `runtime-ts/package.json` and `runtime-py/src/bantamkit/__init__.py`. The parity rule does not exempt the version, and npm refuses a republish of an existing number, so a job that forgets the bump cannot ship at all.
2. Run the full gate at the release commit — node suite, pytest, ruff, `node tools/conformance/run.mjs --all`.
3. Clean-room verify the tarball before publishing: `npm pack`, install it into an empty project, drive the server over stdio. This is the only test of what a stranger receives.
4. Publish, then verify FROM the public registry — compare the published shasum against the tarball that was tested, and run `npx --yes bantamkit-mcp@<version>` with an empty cache.

**The one step that is not mine to run.** npm 2FA is on for account `kktestdev`, and the `!` channel has no TTY, so the OTP prompt never appears — see [[otp-prompts-cannot-be-answered-in-the-bang-channel]]. Do everything up to `npm publish`, then hand the user the command for a real terminal. Do not treat that hand-off as the end of the job: wait, then verify the registry.

**Still unauthorized regardless:** git tag, GitHub release, PyPI. Publishing to npm was granted; those were not.
