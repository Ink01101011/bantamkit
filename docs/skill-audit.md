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

## The rest of the contract — what the served description no longer carries

Until 2026-09-12 the served description was 8,161 characters, and Claude Code truncates a
tool description at 2,048 — mid-sentence, without an error, keeping the input schema. What
was cut was the half that says when to call the tool and how to read its answer, so the
description is now 1,826 characters and earns the call; the reference material it carried
lives here (job50, J50-3; the register row is J49-B4).

**Identity comes from the path.** `<marketplace>/<plugin>/<version>/skills/<name>/SKILL.md`
relative to `root`; any other shape is a skill outside a plugin, identified by its directory
name alone and never excluded by `enabled`. A skill is reported as `<plugin>:<name>` — the
spelling the host uses and the key `usage` is looked up by — or as `<name>` when it has no
plugin.

**The omission record.** Counted skills plus omissions account for every `SKILL.md` found. An
omission is `{subject, count, size, what}` with subject one of `plugin-not-enabled`,
`duplicate-skill`, `stale-version`, `unreadable-file`, `unparsed-frontmatter`; `size` is the
bytes it would have added and `what` names the paths. Inside the resolved version
`duplicate-skill` still covers two files claiming the same (marketplace, plugin, name), which
is reachable only for skills outside a plugin; the last in scan order wins.

**`enabled`, measured.** The plugin cache also holds disabled plugins and stale version
directories; counting those inflated a real audit to 41 skills / 19,065 B against a true
34 / 14,515. `enabled` takes the plugin ids as `settings.json` spells them,
`<plugin>@<marketplace>`.

**Folding and unwrapping, exactly.** A `description:` folded over several lines is joined with
single spaces before it is counted or scanned. A value written as a whole-value quoted YAML
scalar is unwrapped after that fold and before either — the host's parser strips those quotes
before a session sees the description, so they are not `catalogue_bytes`, and only quotes
INSIDE the value delimit a trigger phrase. The unwrap applies to every frontmatter key, not
just `description:`, so `name: "s"` is the name `s` and `router: "true"` is a router. A value
is a whole-value scalar only when it begins with `"` or `'` AND that opening quote's own
closing quote is the value's LAST character, judged by YAML's two escape rules and no others:
inside a `"` scalar a backslash escapes the character after it, so `\"` does not close it and
the sequences `\"` and `\\` resolve to `"` and `\` while every other `\x` is left exactly as
written; inside a `'` scalar a doubled `''` is one literal apostrophe, so it does not close
it and resolves to `'`. Every other value is left as written and scanned literally: `"a" and
"b"` begins and ends with `"` and is NOT one scalar, because its opening quote closes at
index 2, and stripping it would weld the value into one junk phrase and destroy both real
ones. A value that OPENS with a quote and never closes one — including one whose last quote
is escaped — is a LITERAL: it is not unwrapped, its quote character is counted, its unpaired
quote opens no phrase, and it is not a `frontmatter-malformed` finding, which names failures
of the BLOCK and not of one value.

**Two subjects that look alike.** `frontmatter-malformed` (a finding) is no frontmatter
block, an unterminated one, or no `description:` key. A block that cannot be parsed at all is
ALSO omitted as `unparsed-frontmatter` and adds nothing to `skills`; a parsed block with no
description is a skill costing zero bytes.

**Phrases.** The text of the UNWRAPPED value between `"` pairs, or between `'` pairs where the
quote is not flanked by letters. A phrase with no letter or digit in it is ignored.
Collisions are EXACT matches on literal quoted phrases and never a similarity score — see
"What it will not do" above for the 820-pair measurement that refuted the score.

**What refuses, and what does not.** Four argument failures are refused with their own
sentences and never as a partial answer: an unknown `check`, a negative `budget`, a `root`
that is missing or is a file, and an EMPTY `root` — which passes JSON-schema `string` and
would otherwise resolve to the server's own working directory. Nothing about the CONTENT of
the tree refuses. Deterministic: the tool reads nothing but `root`; `usage` is the caller's
own count (`node tools/ledger/tool-usage.mjs --group skill --json`), `enabled` and
`versions` are host truth the caller supplies, never read from the host's transcripts,
settings or plugin registry.

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
