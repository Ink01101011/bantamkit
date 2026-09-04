# `skill_audit` fixture tree

Sixteen `SKILL.md` files laid out the way a plugin cache lays them out, engineered so every
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
    budget   = 1024   (below the tree's 1296 bytes, so the budget finding fires)

## What the tree should answer

Measured by hand over these files, applying the spec in `assets/tools/skill_audit.json`:

    skills            12
    catalogue_bytes   1296
    omissions          4      (12 counted + 4 omitted = 16 SKILL.md on disk)

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
|  84 | `frontmatter-kit:misnamed` | `kit-market/frontmatter-kit/2.3.1/skills/misnamed/` |
|   0 | `frontmatter-kit:no-description` | `kit-market/frontmatter-kit/2.3.1/skills/no-description/` |
| 112 | `dup-kit:echo-check` | `kit-market/dup-kit/1.1.0/skills/echo-check/` |
|  92 | `solo-check` | `personal/skills/solo-check/` |

These twelve numbers are the AUTHOR'S ARITHMETIC, not the tool's output — the tool did not
exist when they were written. They are here to be disagreed with: if an implementation answers
something else, one of the two is wrong and the difference names which clause is in dispute.

## Findings, and the file that triggers each

### `shared-trigger-phrase` (severity high)

Two or more non-router skills quote the same literal phrase, so which one a session reaches for
is a coin flip. Two must fire:

- `'race condition'` — `trigger-kit/1.0.0/skills/race-review/` and `.../race-debug/`. Single
  quotes, opened after a space and closed before a space or a comma.
- `"flaky in prod"` — `.../race-debug/` and `.../deadlock-hunt/`. Double quotes, so the two
  delimiters are both exercised and a reader that implements only one is visible.

Neither finding may list `loop-router`, and neither may list `off-kit:never-loaded` (which also
quotes `'race condition'`, from a plugin that is not enabled).

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

No file triggers this — the caller does, by passing a `budget` below 1296. Pass `1024` and the
finding fires with an overage of 272 bytes; omit `budget` entirely and it must not fire at all.

### `never-invoked` (severity low)

`usage.json` is the caller's own measurement, in the shape
`node tools/ledger/tool-usage.mjs --group skill --json` produces once its `rows` are folded into
a map. Three counted skills must be reported, and they exercise the two ways of being zero:

- `trigger-kit:deadlock-hunt` — present in the map with the value `0`.
- `solo-check` — present in the map with the value `0`.
- `frontmatter-kit:no-description` — ABSENT from the map, which means zero, not unknown.

`dup-kit:echo-check` has 7 calls under one key even though two copies are on disk; usage is
keyed by the id the host uses, which has no version in it.

## Omissions, and the file that triggers each

An omission is `{subject, count, size, what}` — the same discipline as `bantamkit_read`, where
what the reader could not deliver is a record and not silence. Counted skills plus omissions
account for all sixteen files; if that sum stops holding, something is being dropped quietly.

| subject | file | size | why |
| --- | --- | ---: | --- |
| `plugin-not-enabled` | `kit-market/off-kit/1.0.0/skills/never-loaded/` | 112 | `off-kit@kit-market` is not in `enabled.json`. Readable, quotes `'race condition'`, and must contribute to nothing — not the count, not the bytes, not a phrase finding. The size is what enabling the plugin would cost. |
| `duplicate-skill` | `kit-market/dup-kit/1.0.0/skills/echo-check/` | 44 | Same (marketplace, plugin, name) as the copy under `1.1.0`. `1.1.0` sorts last in byte order and wins; the 44-byte stale copy is omitted. The two descriptions differ in length on purpose, so which copy was counted is visible in `catalogue_bytes` (1296 with the right one, 1228 with the wrong one). |
| `unreadable-file` | `kit-market/frontmatter-kit/2.3.1/skills/bad-bytes/` | 0 | The description line ends with a lone `0x80`, which is not valid UTF-8. A strict decoder raises; the file is a record, not a crash and not a description with `U+FFFD` substituted into it. Chosen over a permissions bit because an invalid byte behaves the same on Windows. |
| `unparsed-frontmatter` | `kit-market/frontmatter-kit/2.3.1/skills/broken-open/` | 0 | See `frontmatter-malformed` above: this file is both an omission and a finding. |

## The one skill outside a plugin

`personal/skills/solo-check/` sits four segments below the root, not six, so no marketplace,
plugin or version can be read off its path. Its id is the bare `solo-check` and `enabled` does
not speak to it: a skill that belongs to no plugin cannot be disabled by a plugin list, and
dropping it would under-report a real personal skills directory by every file in it.

## Known limitation, stated rather than fixed

The duplicate tie-break is a byte-order comparison of version directory names, so a plugin
holding `9.0.0` and `10.0.0` counts `9.0.0`. A semver comparison would be right and would be a
second thing the two runtimes have to agree about character for character; the byte order is
free. No fixture pins the `9.0.0`/`10.0.0` case, because pinning it would freeze the wrong
answer. The omission record names the loser, so an operator can always see which copy was read.
