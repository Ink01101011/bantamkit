# Python 1.0.0 migration note

← [README](../README.md) · [Install](install.md) · [Porting](porting.md)

In 1.0.0 the PyPI package runs Python generated from the npm package's TypeScript (`bantamkit/_generated/`).
On a few edge-case inputs it therefore answers differently than the 0.40 releases (0.40.0 and
0.40.1, the last) did. The entries, written
from the user's side with before and after examples, are in
[CHANGELOG.md → Changed (Python)](../CHANGELOG.md#changed-python). This page maps each entry to the
case that pins it and to the `docs/porting.md` section that records the change.

**How each row was settled (J90-D, #333).** One probe per entry was run three times on the same
input: on the released 0.40.0 source (a worktree at tag `v0.40.0`), on this tree, and on the
Node build. An entry is listed only when 0.40.0 gave the "before" answer. The last release is
0.40.1: from 0.40.0 it changed only the host install (`hostinstall.py`, `hostinstall.ts`) and the
version number (`git diff v0.40.0 v0.40.1 -- runtime-py/src runtime-ts/src`), and J90-RR found it
gives the same "before" answers, so the rows were not re-measured on it. Earlier releases were
not checked. Rows 1–14 ran on CPython 3.12.13. Rows 15–17 ran on
3.11.15, 3.13.18 and 3.14.10, each interpreter for both sides, with the same probes. Rows 18–22
and the added inputs of row 8 (J90-RF) ran on 3.12.13 and Node v26.13.0. In every row the after
answer equals Node's, except row 13 (a ruled difference) and row 16, where `--suite shiftwork`
compares Node's sentence and this probe did not run Node. In row 10 Node's answer changed as
well: both runtimes moved to one new sentence.

| # | change | pinned by | recorded in `docs/porting.md` |
|---|---|---|---|
| 1 | log-segment JSON numbers read as doubles | `--suite storage-log` (the G2 rows) | *The event log, the token ledger and the log segment* |
| 2 | cold-index tf sums past 2^53 rounded | `--suite storage-cold`: `J90-RF a cold query summing tf rows past 2^53 adds them as doubles (migration entry 2)` and a literal per side | *The last speed gap and what the hand-written Python got wrong* |
| 3 | price-table JSON numbers are doubles | `--suite pricing` | *Pricing and the job budget* |
| 4 | work-plan refusals spell numbers as JS | `--suite ts2py`: `adversarial/touches/1e21`, `adversarial/touches/1e-7`, `adversarial/touches/int-beyond-2^53` (`fixtures/workplan-cases.json`) | *Generated modules* (the workplan table) |
| 5 | work-plan priorities past 2^53 tie | `--suite ts2py`: `adversarial/priority/2^53-plus-one-ties-in-js` | same |
| 6 | a node with no `id`: refusal, not `KeyError` | `--suite ts2py`: `ts/shape-no-id`; the tool's `KeyError` by `--suite workplan` `tool/no-id` | same |
| 7 | price-table directory or empty path: `PriceTableError` | `--suite pricing`: `load: a-directory.json`, `load: the empty path` and its literal per side | *Pricing and the job budget* |
| 8 | `format_micros(-1)`, `(0.5)`, `(10**30)` | `--suite pricing`: `format_micros outside its contract: -1, 0.5, 10**30` and its literal per side | same |
| 9 | an empty `<log>.1.gz` counts as skipped | `--suite storage-log` | *The event log, the token ledger and the log segment* |
| 10 | one "not JSON" sentence for cold-index files | `--suite storage-cold`: `J90-3F a ColdIndexError for a manifest, segment or shard that is not JSON — one sentence, no parser wording` | *The cold index, retention and the tiers* |
| 11 | retention / skill-audit switches trimmed as JS | `--suite storage-retention`: `J90-3 the BANTAMKIT_RETENTION switch is read through JS trim` | same |
| 12 | dotless / dotted *i* and long *s* in a relative date | `--suite dream`: `` `tonight` spelled with U+0131 (dotless i) ``, U+0130, U+017F | *The dream* |
| 13 | config crashes become refusals (Node differs, ruled) | `--suite recall-strings`: `RULED: config outside the reader's language — <document>` with `J89-5b outcome bit per side: <document>` | *Three crashes ruled, and a digit fixed* |
| 14 | U+2028 / U+2029 / U+0085 kept, control characters read in fact files | `--suite ts2py-codec`: classes `yaml11-breaks`, `pyyaml-refuses` | *The fact-file codec* |
| 15 | argparse wording on 3.11 / 3.13 / 3.14 | `--suite cli` `install-bad-host`; `--suite memorycli` `bad-choice`, `list-bad-filter` (run with `--python` per interpreter) | *CPython 3.13 and 3.14 answer 3.12's answers* |
| 16 | checkpoint JSON sentence on 3.13 / 3.14 | `--suite shiftwork`: `unparseable-checkpoint` | same |
| 17 | date sentences on 3.14 | `--suite recall-strings`: `load_grants over the config family` | same |
| 18 | the lock file is `0o644` | `--suite storage-lock`: `the permission bits of a held lock file (umask 022)` and its literal per side | *The lock and the hot index* (Settled before generation, J90-1F) |
| 19 | stale temps of a killed writer deleted | `--suite storage-index`, `storage-cold`, `storage-retention`: the three `J90-3F … removes … stale temps` cases | *The cold index, retention and the tiers* (Fixed (J90-3F): the temps a killed writer left) |
| 20 | a store through a dangling symlink: new index file name | `--suite storage-index`: `J90-3 a source through a dangling symlink keeps the link as spelled (realpath and sha16)` | *The lock and the hot index* and *The cold index, retention and the tiers* (Settled: a source through a dangling symlink) |
| 21 | hand-edited hot-index heads and shards read as Node reads them | `--suite storage-index`: the `J90-1 a head whose lens_total holds 1.0 …`, `… full_at … lowercase …` and `a postings shard whose run length is 1.0 …` cases | *The lock and the hot index* (Settled before generation, J90-1F) |
| 22 | retention drops a job doc whose `file` is absolute | `--suite storage-retention`: `J90-RF compaction drops a job doc whose file is absolute (joined under the root, as path.join joins)` and its literal per side | *The cold index, retention and the tiers* (Python answers that moved to Node's) |

**Every row has a case.** Rows 2, 7 (the empty path) and 8 had none when this note was first
written; J90-RF added a two-runtime case and a literal per side for each, each red under a
mutation that restores the 0.40 answer on one side or both.

**Recorded in `docs/porting.md`, not re-run here.** Several more changes in the *Generated
modules* chapter were not re-run for this note: the usage ledger's tie at the ninth decimal and
its far-future weight, retrieval's NaN ordering, the queries sidecar nested past 512, and
others. Most need an input that a user's data does not produce, or a Python caller who builds
values by hand. They stay in porting.md and are not listed as 1.0.0 changes until a probe has
run them against the last release.
