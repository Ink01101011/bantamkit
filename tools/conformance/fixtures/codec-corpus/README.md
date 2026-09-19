# The frozen codec corpus

`facts/` holds **56 real fact files**, copied byte for byte out of this machine's live
project memory store on 2026-09-19, plus the `index.md` the store itself wrote for exactly
those 56 (the excluded rows removed, nothing else touched). `tools/conformance/suites/codec.mjs`
reads this directory and nothing else.

## Why it is frozen

The suite used to build its corpus from the **live** store at `.bantamkit/memory/facts/`,
which is gitignored, untracked, and rewritten by anything that saves or recalls a memory.
`codec.mjs` generates three cases per fact, so the suite's size was a function of what the
operator had done that afternoon. Measured at one unchanged commit, `run.mjs --all` reported
**8166, 8169 and 8172** cases; measured again in J55-1 on `2b5c2ad`, one `memory_save`
between two runs moved `--suite codec` from **390 to 393** with no code change at all.

Nothing was failing — cases were being *added* — but a gate whose size nobody can reproduce
is a gate nobody can quote. This is the same reason `tools/ledger/fixtures/token-ledger/`
exists, written up in `tokenledger.mjs`'s header: a differential over a live corpus is a case
that will go red for a reason nobody caused and will then be "fixed" by weakening it.

## Why real files, and not just `adversarialFacts()`

The adversarial set is built to be nasty in ways someone thought of. These files are nasty in
ways nobody thought of: 56 of 56 descriptions long enough to hit PyYAML's 80-column wrap, one
description PyYAML chose to **single-quote** (`job45-repomap-gate-refuted-built-anyway`), four
carrying a raw U+2014 em dash that `allow_unicode` keeps unescaped across that wrap, a body
carrying leaked `</body>` and `<links>[...]` markup, `---` document markers inside two bodies,
`last_recalled: null` on three facts beside dates on 53, links lists of 0 (×15), 1 (×1) and up
to 5, non-ASCII in 47 of the bodies and Thai prose in 13 of them. **A codec that round-trips
only its own output is the
failure this suite exists to catch**, and the files Python actually wrote are the only
evidence of what Python actually writes.

Every feature class the live store exhibited is present here, including each one that had
only a single carrier — see the counts in J55-1's report.

## What was left out, and why

A fixture is a public file in a public repository. **Five** of the 61 live facts are left
out. Four were excluded when the corpus was first frozen, after reading all of them; the
fifth was removed afterwards, and the section below this table says why that took a second
pass.

| fact | why |
|---|---|
| `otp-prompts-cannot-be-answered-in-the-bang-channel` | carries credential-shaped strings (`--otp=<digits>`, a `pypi-…` token placeholder). Expired and worthless, but it is the one file whose own lesson is "never write an example secret", and it would trip a secret scanner. |
| `stay-inside-the-ticket-scope` | names a third-party employer system and a live Jira key; nothing to do with bantamkit. |
| `project-branch-model-releases` | another project's production topology — deploy branches, hosted services, a cluster namespace. Not ours to publish. |
| `this-account-pays-no-dollars-tokens-are-the-currency` | verbatim fields from the operator's `~/.claude.json` account block (billing type, organization type, rate-limit tier). |
| `cache-miss-tail-is-cold-resume-of-huge-threads` | a week of the operator's own API usage — total call count, total prompt tokens, a dollar shadow price for the week and for sixteen further per-class breakdowns, and a model identifier. Removed 2026-09-19 on the user's ruling (J55-5). |

Dropping them cost no feature class: every codec-relevant shape above still has at least as
many carriers here as it had there.

### The fifth one, and where the line had been drawn wrong

This is written out rather than added quietly as a fifth row, because the first four were
chosen by one rule and the fifth shows that rule was applied too narrowly.

`this-account-pays-no-dollars-tokens-are-the-currency` was excluded for carrying the
operator's account block. The file it **links to** — `cache-miss-tail-is-cold-resume-of-huge-threads`
— was kept, and that one carries the actual spend profile: how many calls the account made in
a week, how many prompt tokens they cost, and what they would have been billed. Account
*metadata* was judged unfit for publication and usage *magnitude* was not, and there is no
principle that separates them. The same reason covers both, so the same decision now covers
both.

None of those figures had ever appeared in a tracked file outside this fixture, so publishing
the fixture was what would have made them public. The row above gives the reason without
reprinting them.

**It cost no carrier.** The corpus was classified by the feature table above before and after
the removal: every class that had exactly one carrier — the single-quoted description, the
leaked-markup body — still has it, the `---`-in-body pair and the `last_recalled: null` trio
are untouched, and the links histogram keeps its 0, 1 and 5 endpoints. Only classes with
double-figure carriers moved at all (the wrap count, `links: 3`, non-ASCII bodies, dated
`last_recalled`), each by exactly one.

The file was linked TO by nothing else in the fixture, and the `links:` lists that remain
already name 32 targets this corpus does not contain — a frozen snapshot of a real store is
full of dangling wiki-links, the suite treats `links` as opaque strings, and none of the
other files was edited to tidy up after this one.

## Changing it

Adding or removing a file here is a deliberate act and the suite is built to say so. Update
`FROZEN_FACTS` in `tools/conformance/suites/codec.mjs` in the same commit, or the
`frozen corpus: the committed fixture is intact` case goes red — that is the point of it.
These facts are a **snapshot**, not a mirror: they are not expected to track the live store,
and re-syncing them would give the case count back its old habit of moving on its own.
