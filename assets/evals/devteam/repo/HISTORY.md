# Release history

`git log --oneline --date=short --pretty='%h %ad %s'`, newest first. Patch files
for selected commits are under `patches/`.

```
9f2c1ab 2026-07-29 fix(retry): read retry_max_attempts from settings, not the constant
7d4e88c 2026-07-22 feat(settle): batch settlement with per-entry retry
6b1a903 2026-07-15 refactor(config): move every tunable into CONFIG_KEYS
5c0de41 2026-07-08 fix(validate): reject zero-amount entries
4a9bb27 2026-07-01 feat(report): render a per-handler summary
3e88f10 2026-06-24 feat(posting): post_entry writes one entry
2d5a6c9 2026-06-17 feat(errors): ValidationError and SettlementError
1c4f0b8 2026-06-10 chore: initial layout
```

Branch `main` is at `9f2c1ab`. Tags: `v0.9.0` on `9f2c1ab`, `v0.8.0` on
`5c0de41`.
