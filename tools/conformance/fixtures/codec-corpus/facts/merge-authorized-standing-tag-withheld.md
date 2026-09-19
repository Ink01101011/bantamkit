---
name: merge-authorized-standing-tag-withheld
description: whether to ask before merging tagging or publishing a bantamkit release
  - merge standing, tag and github release deny-ruled, and npm publish is NOT standing
  when the user reserves it per-job; whether to ask before merging a bantamkit PR,
  and why a merge can still get blocked after a compaction
type: feedback
created: '2026-08-21'
last_recalled: '2026-09-19'
links:
- every-change-ships-to-npm-not-just-to-main
- npm-publish-0-26-0-blocked-on-login
- feedback-authorization-does-not-survive-compaction
- bantamkit-program-resume-pointer
---

Merge is standing (granted three times). Tag and GitHub release are per-version and deny-ruled at BOTH scopes; `git -C <path> tag` is a known hole in the deny rule and is not to be used.

**AMENDED 2026-09-06: npm publish is not unconditionally standing.** Opening job44 the user said, in their own words: *"เสร็จแล้วแจ้งฉันแล้วรอฉันอนุมัต publish"* — build and bump the version, then STOP and wait for their approval before publishing. So the standing grant recorded in [[every-change-ships-to-npm-not-just-to-main]] ("a job ends when the change is live on npm") is overridden whenever the user reserves the decision for a specific job. Read the opening message of the job before assuming publish is authorized; a grant given in an earlier job is not a grant for this one.

The reverse also holds and is the more common case: when they say nothing, publish is standing and the job is not done at `main`.

MERGE IS AUTHORIZED STANDING. The user granted it twice in their own words: "review แล้ว merge MR ได้เลยไม่ต้องรอฉัน แค่รายงานฉันเสมอ" and "รอบหน้า merge ได้เลยถ้า review ผ่านไม่ต้องรอยืนยันจากฉัน". Review it, merge it, always report. Do NOT ask each time — being asked repeatedly is the failure mode from their side.

TAG IS NOT AUTHORIZED and never has been. Merge authorization does not extend to tagging. Check `git tag | wc -l` before believing any claim that something was tagged.

THE ONE BLOCKER, AND IT IS NOT THE USER: a context compaction reduces the grant to a claim inside a model-written summary, and the auto-mode classifier correctly refuses to act on that. Measured 2026-08-17: it refused `gh pr merge 32 --squash` naming exactly that reason. Do not route around the denial with a different command or the API. The durable fix is a Bash permission rule for `gh pr merge` in settings, which survives compaction. Until that rule exists, after a compaction say so once, plainly, and ask for one restatement.

MERGE STYLE for this repo, measured not assumed: squash (12+ PRs, main is linear with no merge commits) and KEEP the branch — squashing leaves the commit bodies that carry the MEASURED-BEFORE-WRITTEN declarations reachable only via the branch ref.

VERIFY AFTER MERGING with git, not the API: `gh pr view` GraphQL throws intermittent HTTP 503 on this repo. `git diff origin/main <verified-sha> -- assets/ docs/ runtime-py/` coming back empty is what proves main carries the tree that was actually verified.
