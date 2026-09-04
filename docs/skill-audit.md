# skill_audit — pricing the catalogue every session pays for

    skill_audit(root, enabled?, usage?, check?, budget?, versions?)

A skill's `description:` frontmatter is loaded into the agent's context in EVERY session; its
body is read only when the skill is invoked. The descriptions are therefore a standing bill,
and this tool is what reads it: how many skills are counted, how many bytes they cost, which
of them collide, and which have never fired.

Served eleventh by both runtimes. `catalogue_bytes` is the UTF-8 byte count of the counted
skills' `description:` values — not their names, and bytes rather than characters, which on a
catalogue containing Thai trigger literals differ by 76.

## What it will not do

**No similarity score, by measurement rather than taste.** The obvious design — rank pairs of
skills by token overlap — was built and refuted before this tool was written. Over the 820
pairs in a real 41-skill catalogue the maximum Jaccard was 0.239, so the 0.35 threshold
originally proposed would have returned nothing, ever. Worse, the ranking was wrong where it
mattered: `test-driven-development` and `verification-before-completion`, which genuinely fire
at the same moment, scored **0.000** and ranked 791st of 820, while the metric's own top pair
shared vocabulary and fired at different times. It measures vocabulary similarity, and trigger
collision is not vocabulary similarity. No threshold rescues it.

**It does not read the machine.** `root`, `enabled`, `usage` and `versions` all arrive as
arguments. A tool that consulted `~/.claude` directly could not be compared across two
runtimes, and the conformance gate is the only thing that makes "ported" mean more than
"written twice". The three optional maps are the three facts a directory of files cannot
answer: which plugins the host has switched on, how often each skill has fired, and which
version directory of each plugin the host actually serves.

## The five findings

| kind | severity | fires when |
|---|---|---|
| `shared-trigger-phrase` | high | two non-router skills quote the same literal phrase — which one fires is a coin flip |
| `catalogue-over-budget` | high | `catalogue_bytes` exceeds the `budget` the caller passed |
| `never-invoked` | low | a counted skill has zero calls in the caller's `usage` map |
| `frontmatter-malformed` | medium | no frontmatter block, an unterminated one, or no `description:` |
| `name-mismatch` | medium | frontmatter `name:` is not the skill's directory name |

`never-invoked` fires only when `usage` is supplied: an absent map is no measurement, and
reporting every skill as uncalled on the strength of it would be an assertion about data the
tool was never given.

**Two of the five cannot cite the real corpus as evidence.** `frontmatter-malformed` and
`name-mismatch` fire zero times on this machine; only the fixture proves they can fire at all.

## Trigger phrases, and the two rules that make them usable

A phrase is the text between a matched pair of quotes INSIDE a description. Two rules earn
their place:

- **A whole-value quoted scalar is unwrapped first.** Real skills are written
  `description: "Use this skill whenever …"`, and reading that literally makes the entire
  description one giant phrase and hides the real ones inside it. 17 of 31 enabled skills on
  this machine are written that way.
- **`'` delimits only when not flanked by letters.** Otherwise contractions become phrases:
  an early probe produced `'don'`, `'why didn'` and `'— that'` before this rule existed.

A router — a skill whose job is to name its siblings' phrases — declares itself with
`router: true` and is dropped from the phrase index entirely. Its bytes still count, because
the session still pays them. This is a declaration and not a heuristic on purpose: a name
pattern or a phrase-count threshold would exempt an ordinary skill by accident.

## One version per plugin, resolved before anything is counted

The plugin cache holds stale version directories. Deduping by skill NAME across them
**resurrects a skill its own release deleted**: on this machine `kkskills-essentials` ships 5
skills at `0.5.0` and 14 at the stale `0.4.0`, and the 9 that moved to another plugin had no
`0.5.0` counterpart, so nothing displaced them. The tool answered **31 skills / 9,280 B** where
the host serves 22 / 3,396 — found by running the finished tool against this machine, after 66
conformance cases and 20 mutations had all passed.

Exactly one version directory is now resolved per `(marketplace, plugin)` before counting, and
its skills are that plugin's skills. Skills in the losing directories become `stale-version`
omissions — a separate subject from `duplicate-skill`, because a duplicate's bytes are already
paid by the copy displacing it while a stale version's are paid by nobody, and folding the two
together is precisely what kept the defect invisible.

**The candidates are the version DIRECTORIES on disk, not the skills that survived reading.**
A directory holding no `SKILL.md`, or only files that will not decode or will not parse, still
exists and the host still serves it. Choosing among surviving skills instead made an empty
newer version invisible and let an older directory win in silence — the resurrection defect
above arriving through the other door, and one both runtimes committed identically, so the
differential could not see it.

**The tie-break is byte order of the version directory name, last wins, and it is wrong for
`10.0.0` against `9.0.0`.** Semver is not available: `frontend-design` on this machine has nine
version directories named as content hashes (`0120fb83da5d` … `ed404106fcd8`) plus the literal
`unknown`. Byte order is total over all of them and computed identically by both runtimes,
which is the property that matters more here. Every loser is named in an omission record.

**…and byte order is only the fallback, because the caller can just say.** `versions` maps
`<plugin>@<marketplace>` to the version directory name the host serves — the `installPath` in
the same `installed_plugins.json` `enabled` is read out of — and where it names a plugin, no
guess is made. Measured 2026-09-05: byte order picks `unknown` for `frontend-design` where the
host serves `1dd995193ba2`, so the installed directory is thrown away as a duplicate, harmless
only because all nine copies carry a byte-identical description. `versions` is not refused
when it names a plugin or a directory this `root` does not hold: a plugin with no version
directory here is not resolved at all, and a directory that is not here means every directory
that IS here loses and is named in a `stale-version` record. That is the same discipline
`enabled` follows — the caller is the authority on its own host.

## First run — 2026-09-05, this machine

Root `~/.claude/plugins/cache`, `enabled` from `settings.json`, `usage` from
`tools/ledger/tool-usage.mjs --group skill --json`.

```
22 skills   3,396 catalogue_bytes   3 omissions
   plugin-not-enabled  19 skills   7,773 B
   duplicate-skill     15 skills   5,764 B
   stale-version        9 skills   5,884 B
```

Nine `never-invoked`: `frontend-design`, `kkskills-personal:feedback-use-full-filenames`, and
seven superpowers skills — `dispatching-parallel-agents`, `executing-plans`,
`requesting-code-review`, `using-git-worktrees`, `using-superpowers`,
`verification-before-completion`, `writing-skills`.

Zero `shared-trigger-phrase` on this catalogue, which is the honest result and not a
disappointment: the four collisions an earlier probe found all lived in plugins that have since
been switched off.

**"Never invoked" is not "useless."** `secret-hygiene` and `timezone-handling` are correct and
merely unmatched. The tool supplies the count; shrink, disable or keep is a ruling.

## The same catalogue, before and after this session's work

Measured on one basis — UTF-8 bytes of `description:` values over the enabled set:

| | skills | catalogue_bytes |
|---|---:|---:|
| session start | 34 | 13,949 |
| after trimming, splitting and retiring | 22 | **3,396** |

76 % less, with every skill still installed and one `enabledPlugins` toggle away.
