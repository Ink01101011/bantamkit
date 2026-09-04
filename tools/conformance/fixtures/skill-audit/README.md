# `skill_audit` fixture tree

Twenty-two `SKILL.md` files laid out the way a plugin cache lays them out, engineered so every
`skill_audit` finding kind and every omission subject fires at least once. The contract they
pin is `assets/tools/skill_audit.json`; this file says, per fixture, WHICH clause it exists to
trigger — so a later unit can tell a fixture that stopped working from one that never worked.

Nothing here is real. No path, plugin, marketplace or version below exists on any machine, and
the tool never reads `~/.claude`: the scan root is `cache/`, the enabled set is `enabled.json`
and the call counts are `usage.json`, all three handed in by the caller. That is what makes the
answer deterministic and therefore comparable between the two runtimes.

    root     = tools/conformance/fixtures/skill-audit/cache
    enabled  = the three ids in enabled.json
    usage    = usage.json
    budget   = 1024   (below the tree's 1713 bytes, so the budget finding fires)

## What the tree should answer

Measured by hand over these files, applying the spec in `assets/tools/skill_audit.json`:

    skills            16
    catalogue_bytes   1713
    omissions          5      (16 counted + 6 omitted = 22 SKILL.md on disk)

Five omission RECORDS over six files: `duplicate-skill` carries two.

The identity of every counted skill, and its description bytes:

| bytes | id | file |
| ----: | --- | --- |
| 136 | `trigger-kit:race-review` | `kit-market/trigger-kit/1.0.0/skills/race-review/` |
| 125 | `trigger-kit:race-debug` | `kit-market/trigger-kit/1.0.0/skills/race-debug/` |
| 124 | `trigger-kit:deadlock-hunt` | `kit-market/trigger-kit/1.0.0/skills/deadlock-hunt/` |
| 104 | `trigger-kit:contraction-a` | `kit-market/trigger-kit/1.0.0/skills/contraction-a/` |
|  97 | `trigger-kit:contraction-b` | `kit-market/trigger-kit/1.0.0/skills/contraction-b/` |
| 107 | `trigger-kit:worktree-sweep` | `kit-market/trigger-kit/1.0.0/skills/worktree-sweep/` |
| 174 | `trigger-kit:loop-router` | `kit-market/trigger-kit/1.0.0/skills/loop-router/` |
| 141 | `trigger-kit:folded-note` | `kit-market/trigger-kit/1.0.0/skills/folded-note/` |
|  88 | `trigger-kit:quoted-scalar` | `kit-market/trigger-kit/1.0.0/skills/quoted-scalar/` |
|  84 | `trigger-kit:quoted-edge` | `kit-market/trigger-kit/1.0.0/skills/quoted-edge/` |
|  83 | `trigger-kit:quoted-single` | `kit-market/trigger-kit/1.0.0/skills/quoted-single/` |
|  84 | `frontmatter-kit:misnamed` | `kit-market/frontmatter-kit/2.3.1/skills/misnamed/` |
|   0 | `frontmatter-kit:no-description` | `kit-market/frontmatter-kit/2.3.1/skills/no-description/` |
| 112 | `dup-kit:echo-check` | `kit-market/dup-kit/1.1.0/skills/echo-check/` |
| 162 | `hash-kit:hashed-check` | `kit-market/hash-kit/unknown/skills/hashed-check/` |
|  92 | `solo-check` | `personal/skills/solo-check/` |

These sixteen numbers are the AUTHOR'S ARITHMETIC, not the tool's output. The first twelve
were written before the tool existed and have not moved since; three were added with the
whole-value-quote rule and are computed by hand from the unwrapped scalar, not read off a run;
the sixteenth was added with the version-resolution rule. They are here to be disagreed with: if an implementation answers something else, one of
the two is wrong and the difference names which clause is in dispute.

## Findings, and the file that triggers each

### `shared-trigger-phrase` (severity high)

Two or more non-router skills quote the same literal phrase, so which one a session reaches for
is a coin flip. Two must fire:

- `race condition` — three skills: `race-review/` and `race-debug/` quote it with single
  quotes, `quoted-edge/` with double quotes. The delimiter is not part of the phrase, so a
  phrase quoted two different ways is still one collision.
- `flaky in prod` — five skills: `race-debug/`, `deadlock-hunt/`, `quoted-scalar/`,
  `quoted-single/` and `quoted-edge/`. Double quotes, so both delimiters are exercised and a
  reader that implements only one is visible.

Two findings, and it is their MEMBERSHIP that the whole-value-quote rule moves — see below.
Neither finding may list `loop-router`; neither may list `off-kit:never-loaded` (which also
quotes `'race condition'`, from a plugin that is not enabled); and neither may list
`dup-kit:retired-check` (which also quotes `'race condition'`, from a version directory that
was not resolved). Those last two are the two different ways of contributing nothing, and they
are deliberately not the same mechanism, so a reader that lost one is not hidden by the other.

### The contraction guard — a finding that must NOT fire

`.../contraction-a/` and `.../contraction-b/` each contain `don't ... didn't` and NO quoted
phrase. Their two descriptions were written so that the text BETWEEN those two apostrophes is
byte-identical in both:

    t happen locally and asks why the last run didn

A reader that treats every `'` as a delimiter therefore reports a third
`shared-trigger-phrase` finding over that junk string. Measured both ways when the fixture was
written: the correct rule (`'` delimits only when it is not flanked by letters) yields two
findings, the naive rule yields three. **Three findings is the failure, not two.** This pair is
the only thing in the tree that separates a correct implementation from a plausible one, so if
it is ever "simplified", the guard is gone.

### The router exemption — a second finding that must NOT fire

`.../loop-router/` declares itself with a frontmatter key:

    router: true

That is the chosen mechanism, and it is a declaration rather than a heuristic on purpose — a
name pattern (`*-router`) or a phrase count would make an ordinary skill exempt by accident.
A router is dropped from the phrase index entirely: it neither raises a finding nor joins one.
It is still COUNTED — its 174 bytes are in every session's bill like any other description.

`loop-router` quotes `'stale worktree'`, and the only other skill quoting it is
`.../worktree-sweep/`. If the exemption is dropped, a third finding appears over that phrase —
a distinct symptom from the contraction failure above, so the two cannot be confused.

`.../folded-note/` quotes `'ledger sweep'`, which nothing else quotes: a phrase held by exactly
one skill is not a finding. Its description is also one YAML scalar folded over two lines, which
pins the joining rule — the folded value is joined with single spaces before it is counted (141
bytes) or scanned, and a reader that keeps only the first line reports 73.

### The whole-value quoted scalar — the rule that is the only way to see three of these

`description: "Use when ..."` writes the WHOLE value as a quoted YAML scalar. The host's parser
strips those two quotes before the description ever reaches a session, so they are not bytes
anyone pays for and the text between them is not a trigger phrase. Measured 2026-09-05 over a
real plugin cache: 17 of 31 enabled skills are written that way. A reader that takes the quotes
literally answers two bytes too many per skill and welds the description into one giant phrase,
which hides any phrase quoted inside it.

Three files pin the rule, and each one fails differently under a different wrong reading:

- `.../quoted-scalar/` — one `"` scalar whole, carrying `\"flaky in prod\"` escaped inside it.
  This is the discriminator for the FINDING: read literally, the two `\"` escapes pair with the
  outer quotes and the phrases are `Use when a suite is \` and
  ` and the whole description is one quoted YAML scalar.` — both junk, both held by one skill,
  so `flaky in prod` loses a member and NOTHING else in the tree says so. Read correctly, the
  value unwraps, `\"` resolves to `"`, and the phrase is found. 88 bytes correct, 92 literal.
- `.../quoted-single/` — one `'` scalar whole, carrying a doubled `''` (`it''s`) and a
  double-quoted phrase. This is the discriminator for the OTHER escape rule: `''` is one
  literal apostrophe, so it does not close the scalar, and once unwrapped it is the `'` of
  `it's`, which the contraction guard above then protects. 83 bytes correct, 86 literal — and
  read literally it also reports two junk phrases torn out of the middle of the description.
- `.../quoted-edge/` — a value that BEGINS and ENDS with `"` and is still not one scalar: its
  opening quote closes at index 15. This is the discriminator for the opposite mistake. A
  reader that unwraps on `startswith` and `endswith` alone strips it, welds
  `race condition" is the phrase to look for when a suite is only ever "flaky in prod` into one
  junk phrase, and drops this skill out of BOTH findings at once. Read correctly the value is
  left exactly as written, so its 84 bytes are the same number either way — the mistake is
  visible only in the two findings and in the headline.

The headline separates all three readings, which is the point of having three files:

    1713   correct
    1720   literal — keeps both outer quotes and both `\` of the escapes
    1711   eager   — also strips a quote off a value that is not a scalar at all

A value that OPENS with a quote and never closes one — including one whose last quote is
escaped — is a LITERAL. It is not unwrapped, its quote character is counted, its unpaired
quote opens no phrase, and it is NOT a `frontmatter-malformed` finding: there is no end point
to unwrap to, guessing one would delete a byte the reader cannot prove is YAML's, and the three
`frontmatter-malformed` tokens name failures of the BLOCK rather than of one value. No file in
this tree holds that case, because it is a property of the reader rather than of a catalogue;
`runtime-py/tests/test_skillaudit.py` pins it in a table beside the rest of the rule.

### One version directory per plugin, resolved before anything is counted

A plugin cache holds every version directory a plugin was ever installed at, and the host
serves exactly ONE of them. So the resolution is per (marketplace, plugin) and it happens
first: one version directory wins, its skills are the plugin's skills, and every `SKILL.md`
under any other version directory of that plugin is omitted. A name absent from the resolved
version is absent — it is never merged in from an older directory.

Two plugins here pin the rule, and they pin different halves of it.

`dup-kit` holds `1.0.0` and `1.1.0`. `1.1.0` sorts last in byte order and is resolved, so:

- `1.0.0/skills/echo-check/` has a same-named skill in `1.1.0` standing in for it, and is
  omitted as `duplicate-skill`.
- `1.0.0/skills/retired-check/` does NOT — `1.1.0` dropped it — and is omitted as
  `stale-version`. **This is the file that reddens the resurrection defect.** Deduping by the
  (marketplace, plugin, name) triple, which is what this tool did until 2026-09-05, has nothing
  to displace `retired-check` with, so it counts it: a skill a release DELETED is resurrected
  by its own audit. Three independent numbers move when that happens, which is why one file is
  enough: the tree reads 17 skills / 1850 bytes rather than 16 / 1713, `stale-version` vanishes
  from the omissions, `'race condition'` grows a fourth member, and `never-invoked` grows a
  fourth finding.

`hash-kit` holds `0120fb83da5d` and `unknown`, and both hold `hashed-check`. Neither name is a
version. This is not invented: measured 2026-09-05, `frontend-design` on this machine has nine
version directories spelled as content hashes plus the literal `unknown`, and the host's own
`installed_plugins.json` records it serving `1dd995193ba2` of them. Byte order puts `unknown` last —
`u` (0x75) after `0` (0x30) — so `unknown` is resolved and the hash copy is a `duplicate-skill`.
The two descriptions differ in length on purpose (162 against 87), so which directory was
resolved is visible in `catalogue_bytes` and not only in the omission record.

The two wrong readings are separated by the headline, the same way the quoting readings are:

    16 / 1713   correct — one version resolved per plugin, then its skills
    17 / 1850   the triple dedupe — versions MERGED, so `retired-check` is resurrected
    17 / 1707   the tie-break inverted — `1.0.0` and `0120fb83da5d` resolved instead

Why a fixture at all, when the real corpus already shows it: on this machine's own plugin
cache, with the seven plugins `~/.claude/settings.json` has switched on, the triple dedupe
answered **31 skills / 9,280 catalogue_bytes** and the resolved rule answers **22 / 3,396** —
the nine `kkskills-essentials` skills that moved out of the plugin in `0.5.0` are now nine
`stale-version` records instead of nine counted skills. 22 / 3,396 is also what the host's own
`installed_plugins.json` gives when the same reader is pointed at each enabled plugin's
`installPath` directly, which is an independent check of the same number. But that corpus is
not committed, it changes when a plugin is updated, and it holds no case where the resolved
version is the OLDER directory. The fixture is the part anybody can rerun.

### `frontmatter-malformed` (severity medium)

Two files, and they differ in whether the skill is still counted:

- `frontmatter-kit/2.3.1/skills/broken-open/` — the `---` block is opened and never closed.
  Nothing in it can be trusted, so this is ALSO omitted as `unparsed-frontmatter` and does not
  reach `skills` or `catalogue_bytes`. The finding names it by its directory name, which is the
  only identity available.
- `frontmatter-kit/2.3.1/skills/no-description/` — the block parses and carries no
  `description:` key. This one IS counted, as a skill costing zero bytes: the host loads
  nothing from it per session, and an operator should still be told it exists.

### `name-mismatch` (severity medium)

`frontmatter-kit/2.3.1/skills/misnamed/` — the directory is `misnamed`, the frontmatter says
`name: renamed-elsewhere`. The host loads by directory, so the frontmatter name is the one that
is wrong. Counted, 84 bytes, id `frontmatter-kit:misnamed`.

### `catalogue-over-budget` (severity high)

No file triggers this — the caller does, by passing a `budget` below 1713. Pass `1024` and the
finding fires with an overage of 689 bytes; omit `budget` entirely and it must not fire at all.

### `never-invoked` (severity low)

`usage.json` is the caller's own measurement, in the shape
`node tools/ledger/tool-usage.mjs --group skill --json` produces once its `rows` are folded into
a map. Three counted skills must be reported, and they exercise the two ways of being zero:

- `trigger-kit:deadlock-hunt` — present in the map with the value `0`.
- `solo-check` — present in the map with the value `0`.
- `frontmatter-kit:no-description` — ABSENT from the map, which means zero, not unknown.

`dup-kit:echo-check` has 7 calls under one key even though two copies are on disk; usage is
keyed by the id the host uses, which has no version in it. The three `quoted-*` skills and
`hash-kit:hashed-check` carry non-zero counts on purpose: they were added to pin a quoting rule
and a version rule, not to grow this list, and a fourth entry here would make a `never-invoked`
regression harder to read, not easier.

`dup-kit:retired-check` is deliberately ABSENT from `usage.json` and must still not appear
here, because it is not a counted skill at all. Under the pre-2026-09-05 dedupe it WAS counted,
so it appeared as a fourth `never-invoked` finding — one more independent signal that the
version rule regressed, on top of the two headline numbers.

## Omissions, and the file that triggers each

An omission is `{subject, count, size, what}` — the same discipline as `bantamkit_read`, where
what the reader could not deliver is a record and not silence. Counted skills plus omissions
account for all twenty-two files; if that sum stops holding, something is being dropped quietly.
Five records over six files: `duplicate-skill` carries two, one per plugin that has more than
one version directory.

| subject | file | size | why |
| --- | --- | ---: | --- |
| `plugin-not-enabled` | `kit-market/off-kit/1.0.0/skills/never-loaded/` | 112 | `off-kit@kit-market` is not in `enabled.json`. Readable, quotes `'race condition'`, and must contribute to nothing — not the count, not the bytes, not a phrase finding. The size is what enabling the plugin would cost. |
| `duplicate-skill` | `kit-market/dup-kit/1.0.0/skills/echo-check/` | 44 | `1.1.0` is the resolved version for `dup-kit` and has a skill of this name, so this copy is displaced rather than lost. The two descriptions differ in length on purpose, so which directory was resolved is visible in `catalogue_bytes`. |
| `duplicate-skill` | `kit-market/hash-kit/0120fb83da5d/skills/hashed-check/` | 87 | `unknown` is the resolved version for `hash-kit` — byte order, over two names that are not versions at all — and has a skill of this name. The record is what tells an operator which of the two directories was read. |
| `stale-version` | `kit-market/dup-kit/1.0.0/skills/retired-check/` | 137 | It is under a version directory that was NOT resolved, and the resolved `1.1.0` has no skill of this name to stand in for it. So it is not a duplicate of anything: it is on disk, in nobody's bill, and this record is the only place the document says so. Its 137 bytes are paid by nobody, which is the difference from a duplicate: a duplicate's bytes are already paid by the copy that displaced it. |
| `unreadable-file` | `kit-market/frontmatter-kit/2.3.1/skills/bad-bytes/` | 0 | The description line ends with a lone `0x80`, which is not valid UTF-8. A strict decoder raises; the file is a record, not a crash and not a description with `U+FFFD` substituted into it. Chosen over a permissions bit because an invalid byte behaves the same on Windows. |
| `unparsed-frontmatter` | `kit-market/frontmatter-kit/2.3.1/skills/broken-open/` | 0 | See `frontmatter-malformed` above: this file is both an omission and a finding. |

## The one skill outside a plugin

`personal/skills/solo-check/` sits four segments below the root, not six, so no marketplace,
plugin or version can be read off its path. Its id is the bare `solo-check` and `enabled` does
not speak to it: a skill that belongs to no plugin cannot be disabled by a plugin list, and
dropping it would under-report a real personal skills directory by every file in it.

## Known limitation, stated rather than fixed

The version a plugin is resolved at is decided by a BYTE-ORDER comparison of the version
directory names, last wins. It is total, it is free, both runtimes already compute it
identically, and it works on names that are not versions — which the alternative does not,
because `0120fb83da5d` and `unknown` have no semver to compare. Two things it gets wrong,
both stated here rather than fixed:

- **`10.0.0` loses to `9.0.0`.** `1` sorts before `9`. A semver comparison would be right and
  would be a second thing the two runtimes have to agree about character for character, and it
  would still leave the hash case undecided. No fixture pins the `9.0.0`/`10.0.0` case, because
  pinning it would freeze the wrong answer into the cross-runtime contract; both runtimes' own
  test files pin it in a `tmp_path` tree instead, which says out loud what each half does.
- **Among names that are not versions the winner is arbitrary.** Deterministic and arbitrary,
  not correct. `hash-kit` pins the determinism, which is the only property available: nothing
  in a content-hash name says which one is newer. On this machine the arbitrariness happens to
  cost nothing — all nine `frontend-design` copies carry a byte-identical 204-byte description,
  measured 2026-09-05 — but that is a fact about that plugin, not about the rule.

What the host itself records — the `installPath` of each enabled plugin in
`~/.claude/plugins/installed_plugins.json` — would decide both cases correctly and is NOT
consulted, because the tool reads `root` and nothing else. Feeding it in would mean a new
input, and it is not one this unit added.

In every case the losing directory is named in an omission record, so an operator can always
see which one was read.

## What moved when the version-resolution rule landed, and what did not

This tree was published at 15 skills / 1551 bytes / 4 omissions / 19 files. It is now
16 / 1713 / 5 / 22. Every figure was recomputed from the tool's output over the tree and
checked against hand arithmetic, not adjusted until it looked tidy; the difference is entirely
the three new files.

| figure | before | after | why |
| --- | ---: | ---: | --- |
| `skills` | 15 | 16 | one file counted: `hash-kit/unknown/skills/hashed-check`. The other two new files are both omitted |
| `catalogue_bytes` | 1551 | 1713 | +162, the resolved `hashed-check`. NOT ONE of the fifteen earlier byte counts moved |
| omission RECORDS | 4 | 5 | `stale-version` is new |
| omitted FILES | 4 | 6 | `duplicate-skill` goes 1 → 2 (`hash-kit`'s hash copy), `stale-version` is 1 (`retired-check`) |
| `SKILL.md` on disk | 19 | 22 | `dup-kit/1.0.0/skills/retired-check`, `hash-kit/0120fb83da5d/skills/hashed-check`, `hash-kit/unknown/skills/hashed-check` |
| `shared-trigger-phrase` findings | 2 | 2 | `retired-check` quotes `'race condition'` and is omitted, so it joins nothing; `hashed-check` quotes nothing |
| `catalogue-over-budget` overage at `budget = 1024` | 527 | 689 | 1713 − 1024 |
| `never-invoked` findings | 3 | 3 | `hashed-check` carries 3 calls in `usage.json`; `retired-check` is not counted, so its absence from the map is not a finding |
| `frontmatter-malformed`, `name-mismatch` | 2, 1 | 2, 1 | untouched |
| literal-quote reading | 1558 | 1720 | +162; none of the new descriptions is a quoted scalar, so the rule's own three numbers stay 7 and 2 apart |
| eager-strip reading | 1549 | 1711 | +162, same reason |
| the triple dedupe (the defect) | — | 17 / 1850 | new: what the tree answers when versions are MERGED instead of resolved |
| the tie-break inverted | 1483 | 17 / 1707 | the old number was one skill's bytes swapping; now a wrong resolution also drags `retired-check` in, so `skills` moves too |

The fifteen earlier byte counts not moving is the load-bearing part: the version rule cannot
have silently re-priced the tree it was added to. Its whole effect is in the three files added
to show it.

One thing did NOT move that might have been expected to. The `duplicate-skill` subject means
the same thing it always did — a file displaced by a same-named skill that IS counted — and
`dup-kit/1.0.0/skills/echo-check` is still exactly that, at exactly 44 bytes. What changed is
that the subject is now reached through a resolved version directory rather than through a
per-name comparison, and that the files it used to swallow silently now have their own subject.

## What moved when the whole-value quote rule landed, and what did not

This tree was published at 12 skills / 1296 bytes / 4 omissions / 16 files, and this rule took
it to 15 / 1551 / 4 / 19. Those are the figures this section is about; the version rule above
then took the same tree to 16 / 1713 / 5 / 22. Every figure below was recomputed rather than
adjusted, and the difference is entirely the three files this rule added:

| figure | before | after | why |
| --- | ---: | ---: | --- |
| `skills` | 12 | 15 | three files added: `quoted-scalar`, `quoted-edge`, `quoted-single` |
| `catalogue_bytes` | 1296 | 1551 | +88 +84 +83 = 255, and NOT ONE of the twelve original byte counts moved |
| `omissions` | 4 | 4 | the new files are all readable, enabled, parsed and unique |
| `SKILL.md` on disk | 16 | 19 | the same three files |
| `shared-trigger-phrase` findings | 2 | 2 | still two phrases; three skills joined `flaky in prod` and one joined `race condition` |
| `catalogue-over-budget` overage at `budget = 1024` | 272 | 527 | 1551 − 1024 |
| wrong-dedupe `catalogue_bytes` | 1228 | 1483 | 1551 − 112 + 44, the same arithmetic over a bigger tree |
| `never-invoked` findings | 3 | 3 | the three new skills carry non-zero counts in `usage.json` |
| `frontmatter-malformed`, `name-mismatch` | 2, 1 | 2, 1 | untouched |

The twelve original byte counts not moving is the load-bearing part: none of the original
descriptions is a whole-value quoted scalar, so the rule cannot have silently re-priced the
tree it was added to. The rule's effect on the ORIGINAL twelve is exactly zero, and everything
it does is visible in the three files added to show it.

One thing did not move that might have been expected to. Measured 2026-09-05 over this
machine's own plugin cache, unwrapping changes NO finding there: all 17 whole-value-quoted
descriptions carry only single-quoted phrases inside them, which the literal reader already
found because its `'` scan is independent of its `"` scan. What it changes on the real corpus
is 34 bytes and 17 junk phrases dropped from the index. The finding failure is real but
LATENT there — it needs a phrase double-quoted inside a double-quoted scalar, and only
`quoted-scalar/` in this tree has one. That is why the fixture exists rather than a note
saying the real corpus already proves it.
