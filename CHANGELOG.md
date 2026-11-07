# Changelog

Release notes, newest first. Each section is also the body of that version's GitHub release.

## bantamkit 0.39.1 (Unreleased)

### Approve promotes (#301)

`skill_propose approve <id>` now installs the skill **and promotes it to a native link in the
same call**, on both runtimes. Approving is your say-so, so this is not gated by
`BANTAMKIT_SKILL_AUTO`; automatic installs keep the 3-uses rule. The reply gains one line,
`promoted skill <name>`, or `not promoted: <reason>` when the catalogue budget, a foreign file at
the link path or a failed link refuses it. A refusal is recorded as `promote_refused`, exactly as the
daily run records one, and the skill stays in the `[skill]` recall layer.

- **Undo takes two steps after an approve:** the first `undo <name>` demotes (removes the link),
  the second removes the install. `undo`, `demote` and probation are otherwise unchanged.

### Trigger phrases for the `[skill]` layer (#301)

- **Mined:** each cluster gains `triggers`, at most 5 phrases of 2 or 3 tokens taken from your own
  words (`frame()`d prompts of its successful members): in at least 1/2 of them, and in at most
  1/8 of the source's pieces.
- **Stored:** the proposal record's `triggers`, and `metadata.bantamkit-triggers` in `SKILL.md`
  (phrases joined with `|`), written only when there is one, so existing installs stay
  byte-identical.
- **Backfilled:** the daily run adds `bantamkit-triggers` to an unedited skill installed before
  this release, as a new version (`added triggers to skill <name>`). Not gated by
  `BANTAMKIT_SKILL_AUTO`. If the judge rolls that version back, the next run backfills it again,
  at most once per 5 uses (`JUDGE_USES`).
- **Fired:** with `BANTAMKIT_SKILL_TRIGGERS=on`, recall appends **one** `[skill]` line when a
  trigger occurs in the prompt, after every other line. The top-k is byte-identical. The longest
  trigger wins, then the name. Never a promoted, shadowed or already-shown skill, and never on a
  phrase inside pasted text. It counts as a `recall_hit` only when the recall stamps (so a hook
  injection is not a use).
- **`BANTAMKIT_SKILL_TRIGGERS` is off by default** until the ship bar (precision@inject ≥ 0.432
  over ≥ 20 injections, top-3 unchanged, ≤ 5 ms median added hook latency) is measured.
- **Known limit:** clients other than Claude Code recall through `memory_recall`, whose query the
  model writes, so triggers mined from your prompts may fire less often there.

Details: `docs/skills.md`, *Approve promotes* and *Trigger phrases*.
