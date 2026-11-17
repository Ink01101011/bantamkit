# Python 1.0.0 migration note

← [README](../README.md) · [Install](install.md) · [Porting](porting.md)

In 1.0.0 the PyPI package runs Python generated from the npm package's TypeScript (`bantamkit/_generated/`).
On a few edge-case inputs it therefore answers differently than 0.40.0 did. The entries, written
from the user's side with before and after examples, are in
[CHANGELOG.md → Changed (Python)](../CHANGELOG.md#changed-python). This page maps each entry to the
case that pins it and to the `docs/porting.md` section that records the change.

**How each row was settled (J90-D, #333).** One probe per entry was run three times on the same
input: on the released 0.40.0 source (a worktree at tag `v0.40.0`), on this tree, and on the
Node build. An entry is listed only when 0.40.0 gave the "before" answer. 0.40.0 is the last
release; earlier releases were not checked. Rows 1–14 ran on CPython 3.12.13. Rows 15–17 ran on
3.11.15, 3.13.18 and 3.14.10, each interpreter for both sides, with the same probes. In every row
the after answer equals Node's, except row 13 (a ruled difference) and row 16, where
`--suite shiftwork` compares Node's sentence and this probe did not run Node.

| # | change | pinned by | recorded in `docs/porting.md` |
|---|---|---|---|
| 1 | log-segment JSON numbers read as doubles | `--suite storage-log` (the G2 rows) | *The event log, the token ledger and the log segment* |
| 2 | cold-index tf sums past 2^53 rounded | **no case yet** (open; see below) | *The last speed gap and what the hand-written Python got wrong* |
| 3 | price-table JSON numbers are doubles | `--suite pricing` | *Pricing and the job budget* |
| 4 | work-plan refusals spell numbers as JS | `--suite ts2py`: `adversarial/touches/1e21`, `adversarial/touches/1e-7`, `adversarial/touches/int-beyond-2^53` (`fixtures/workplan-cases.json`) | *Generated modules* (the workplan table) |
| 5 | work-plan priorities past 2^53 tie | `--suite ts2py`: `adversarial/priority/2^53-plus-one-ties-in-js` | same |
| 6 | a node with no `id`: refusal, not `KeyError` | `--suite ts2py`: `ts/shape-no-id`; the tool's `KeyError` by `--suite workplan` `tool/no-id` | same |
| 7 | price-table directory or empty path: `PriceTableError` | `--suite pricing`: `load: a-directory.json`; the empty path has **no case** (open) | *Pricing and the job budget* |
| 8 | `format_micros(-1)` | **no case** (the suite compares only values ≥ 0; open) | same |
| 9 | an empty `<log>.1.gz` counts as skipped | `--suite storage-log` | *The event log, the token ledger and the log segment* |
| 10 | one "not JSON" sentence for cold-index files | `--suite storage-cold`: `J90-3F a ColdIndexError for a manifest, segment or shard that is not JSON — one sentence, no parser wording` | *The cold index, retention and the tiers* |
| 11 | retention / skill-audit switches trimmed as JS | `--suite storage-retention`: `J90-3 the BANTAMKIT_RETENTION switch is read through JS trim` | same |
| 12 | dotless / dotted *i* and long *s* in a relative date | `--suite dream`: `` `tonight` spelled with U+0131 (dotless i) ``, U+0130, U+017F | *The dream* |
| 13 | config crashes become refusals (Node differs, ruled) | `--suite recall-strings`: `RULED: config outside the reader's language — <document>` with `J89-5b outcome bit per side: <document>` | *Three crashes ruled, and a digit fixed* |
| 14 | U+2028 / U+2029 / U+0085 kept, control characters read in fact files | `--suite ts2py-codec`: classes `yaml11-breaks`, `pyyaml-refuses` | *The fact-file codec* |
| 15 | argparse wording on 3.11 / 3.13 / 3.14 | `--suite cli` `install-bad-host`; `--suite memorycli` `bad-choice`, `list-bad-filter` (run with `--python` per interpreter) | *CPython 3.13 and 3.14 answer 3.12's answers* |
| 16 | checkpoint JSON sentence on 3.13 / 3.14 | `--suite shiftwork`: `unparseable-checkpoint` | same |
| 17 | date sentences on 3.14 | `--suite recall-strings`: `load_grants over the config family` | same |

**Open.** Rows 2, 7 (the empty path) and 8 have no case. The probes above measured them, but no
gate holds them yet. A two-runtime case for each closes that; adding one changes no answer.

**Recorded in `docs/porting.md`, not re-run here.** Several more changes in the *Generated
modules* chapter were not re-run for this note: the usage ledger's tie at the ninth decimal and
its far-future weight, retrieval's NaN ordering, the queries sidecar nested past 512, the hot
index's realpath through a dangling symlink, and others. Most need an input that a user's data does not produce, or a Python caller who builds
values by hand. They stay in porting.md and are not listed as 1.0.0 changes until a probe has
run them against 0.40.0.
