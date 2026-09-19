# The conformance harness

`tools/conformance/run.mjs` runs the Python runtime and the Node runtime over the same
inputs and diffs their answers. It is the only reason the claim "the two runtimes write the
same bytes" is a measurement rather than an opinion.

```
node tools/conformance/run.mjs --all
node tools/conformance/run.mjs --suite store
node tools/conformance/run.mjs --list
```

Exit code is `0` on pass, `1` on any failure, `2` on a usage error or a missing reference
interpreter.

## Why a Python lives inside a Node port's test tooling

It is a **development-time** dependency of the harness. The shipped package declares
`files: ["dist", "assets"]`, so nothing under `tools/` is published, and `npm test` never
invokes this. The "no Python at runtime" ruling is about what a teammate downloads from npm.

Deleting the reference would mean the byte-compatibility claim rests on someone having read
two sources and agreed they match — which is the check that has never once caught the
difference that mattered. Every defect this job found in the port was found by running both
sides, not by reading either.

## The nineteen suites

| suite | what it compares |
|---|---|
| `cli` | the `bantamkit-mcp` command line as a process: stdout, stderr, exit code. **Extended 2026-09-11 by J46-28** to the question of WHO is on the other end of stdin: the bare invocation at a real terminal (the help, on stdout, exit 0), the bare invocation over a pipe driven with a real `initialize`, and `--store` at a terminal, which still SERVES because the empty argv is a scope and not a second signal. Five of its cases are NOT differential — what each side printed at a terminal, which stream carried it, that it is that runtime's own `-h` bytes, that a flagged terminal launch served, and that a piped bare launch answered — because a revert applied to BOTH runtimes leaves every differential green: measured, `--suite cli` goes from 4 failures on a one-sided revert to **3** on the two-sided one, and the differential `bare-at-a-tty/stdout` is one of the cases that goes back to passing |
| `charsets` | `runtime-ts/src/charsets.ts` against the live CPython codec registry: the file against what `runtime-ts/scripts/charsets-table.py` writes today (header excluded), all 256 bytes of every single-byte codec decoded by the reference against the port's table, the alias map and the module list |
| `codec` | fact-file frontmatter: emit byte-identically, and parse each other |
| `dream` | the cross-layer consolidation: one pair of stores materialised twice, `dream()` run on both, and three things compared per scenario — the returned `DreamResult`, the project directory byte for byte, and the profile directory byte for byte. Two of its cases are NOT differential: the mtime tie-break and the day-arithmetic calendar edge are rules written on both sides and asserted on neither, so they are pinned as typed literals against each runtime separately |
| `docread` | the reader as a library: `sniff`, the rows per part, the omission dicts, every `DocumentReadError` sentence and the `page()` window over the same 99 paths (96 files, plus `''`, `a/b/.` and `/dev/zero`, which are not), plus the thirteen checked-in fixtures under `runtime-py/tests/data/docread/` (a checked-in name wins over a built one), `a\x00b`, three `charset-<label>.eml` parts over the charset table's five bytes and the `<xmp>` 4301-digit charref, and the rulings — pdf/doc/rtf (refused on Node), bzip2/lzma (read by the reference, refused on Node by method number), utf-7, RFC 2231 and `<!ATTLIST>` defaults (both read, one row apart) — each with its refusal-bit companions |
| `mcpreport` | `--mcp-report` as a process, over one synthetic host-log/event-log pair |
| `install` | install-shape self-diagnosis (AS-7a) over ELEVEN matched installs BUILT PER RUN — a real `.dist-info` with a real `direct_url.json` on the reference side, a real `node_modules` with npm's real hidden lockfile on the port side — because the two runtimes' OWN installs are not alike in this harness and comparing them compares environments, not code. Shape, origin, reason, `install_source_exists`, the refusal bit and the whole `install-source-missing` sentence, path included: the origin is shared between the two halves so nothing is relativised into agreement. Four ruled divergences, each with the non-ruled companion `docs/porting.md` requires |
| `memorycli` | `bantamkit-memory` against `python -m bantamkit.memory` as processes: the transcript of every step, the exit codes, and the store afterwards |
| `pricing` | AS-1(b)'s price table: a token count converted into money. Every table travels as raw JSON TEXT so both decoders are under test, every sentence as base64, and the normalised table as ORDERED PAIRS because `JSON.parse` hoists an integer-like model name and `json.loads` does not — the one ordering the two runtimes are NOT claimed to share. 81 cases over the validator's every fault sentence, the four token classes priced separately, the per-class refusal, the 2**53-1 ceiling and `format_micros`. Six of its cases are NOT differential: the constants, the half-up rounding at the exact half and **the shipped table's emptiness** are pinned as typed literals against each runtime separately — the last of those is what makes pasting an unsourced rate into `assets/pricing/default.json` a visible act, and a differential cannot see it because both sides read the same file |
| `recall-gate` | roadmap #6's precision gate: the same store and the same `min_ratio` through both runtimes — which facts survive, the directory afterwards (a gated fact must not be stamped), and which ratios are refused. The ladder scores 4/3/2/1 so a floor can land EXACTLY on a fact: `0.5 * 4` is 2.0 and `0.25 * 4` is 1.0, exact in IEEE754 on both sides, and those are the only inputs that separate `>=` from `>`. `NaN`, `Infinity` and `-Infinity` are constructed inside each reference because JSON has no literal for them, and the constant is compared as its IEEE754 BITS because `json.dumps(0.0)` is `0.0` where `JSON.stringify(0)` is `0`. Four of its cases are NOT differential: the value of the constant, the at-threshold admission, the relative-gate property and the refusal sentence are each written twice and asserted on neither side, so they are pinned as typed literals against each runtime separately |
| `recall-strings` | the binding layer: every sentence an empty recall can produce |
| `repomap` | roadmap #10's ranked definition map: the walk, the per-file scan (comment-stripped digest, definitions, reference-set digest), the whole edge map, every node's IEEE-754 SCORE BITS, every rendered listing as bytes, every omission, and the `repo_map` tool's rendered reply — over five purpose-built trees (ordinary, boundary, astral, single-file, document-frequency) and 8 budget calls plus per-tree foci, and 7 `pagerank` scenarios with no filesystem at all. Every float travels as its big-endian bit pattern and every string as base64, because a differential comparing `String(x)` measures the serialisers. **The corpus is BUILT, never this repository**: J45-10 measured three wrong answers from mapping the checkout while writing into it, one of which scored four equivalent mutants as KILLED. Five of its cases are NOT differential — the constants, the astral-plane tie-break, the omission vocabulary, the reply tail and the empty-listing sentence are pinned as typed literals against each runtime separately, and the tie-break is the one rule NO Python test can make non-vacuous (CPython's `str` comparison IS code-point comparison), so only a case can prove the two agree |
| `shiftwork` | the checkpoint writer: `ensure_ascii`, `sort_keys`, separators, `5.0` |
| `skillaudit` | the catalogue auditor: the whole `Audit` document over the committed nineteen-skill fixture tree, every finding kind, every omission and every refusal sentence. **Added to this table 2026-09-07 by J45-11, which found it missing** — the suite has run in `--all` since job44 and the header said "fourteen" over fourteen rows for fifteen suites, so a reader counting this page was one short and nothing compared the page against `--list` |
| `statusline` | `--statusline` as a process, over synthetic event logs ([statusline.md](statusline.md)) |
| `store` | save/recall/index: the directory after the call, byte for byte |
| `tokenledger` | AS-1(c)'s transcript ledger: what a session cost, read off the host's own transcripts. The whole `as_json()` document over a FROZEN corpus in git (`tools/ledger/fixtures/token-ledger/`) plus five corpora built into the harness scratch — the walk order as a sequence, the `requestId` dedupe across files, every omission subject, the four argument refusals with the class that raised each, the 2**53 ceiling, and the cost, whose default answer over the shipped price table is the REFUSAL. **It never reads `~/.claude/projects`**: the operator scripts under `tools/ledger/` do, and J46-1 measured two runs of one of them on one day disagreeing because the session in between added a call — a differential over a live corpus is a case that goes red for a reason nobody caused and is then "fixed" by weakening it. Six of its cases are NOT differential: the omission vocabulary, the committed corpus's headline counts and the shipped table's refusal are pinned as typed literals against each runtime separately, because a `requestId` dedupe deleted from BOTH sides leaves two runtimes agreeing perfectly on a wrong number |
| `validate` | the validator: every sentence a schema failure can produce |
| `wire` | the MCP surface: twelve tools, one prompt, two templates, and the frames themselves — including a `retired` session over `repo_map` and `bantamkit_read`, refused by name on both sides with the event log on, now that job50 I5 (2026-09-12) retired them from the roster and removed the six sessions that used to exercise the reader over the wire (`read`, `read-ruled`, `read-edges`, `read-round2`, `read-round3`, `read-cache`); the reader's own parity stays gated at the library layer, `tools/conformance/suites/docread.mjs` |

`cli`, `mcpreport`, `memorycli` and `statusline` are the odd ones out and deliberately so:
every other suite compares two library functions, and that comparison cannot see which stream
a message lands on or what the process exits with. Those four spawn both CLIs and diff the
three things only a process has. `mcpreport` and `statusline` reuse `ref/cli_ref.py` rather
than adding a second reference script — it already is "spawn the CLI with this argv and hand
back both streams", which is their question with a different argv. `memorycli` carries its
own `ref/memorycli_ref.py` because it compares a fourth thing those three do not: the store
on disk after every step.

**Amendment, 2026-09-11 (J46-28): `cli` now carries a second script, and the sentence above
is the reason to explain why.** `ref/cli_tty_ref.py` is not a second "spawn the CLI with this
argv" — it is a TERMINAL. Both runtimes discriminate a person from a host on `stdin.isatty()`
/ `process.stdin.isTTY`, so comparing their answers needs a real pty on fd 0 of each, and Node
has no pty in its standard library. The alternative was two different fakes, one per runtime,
and a differential over two fakes measures the fakes. So this one script allocates a single
`pty.openpty()` and runs **either** side over it — the only script under `ref/` that runs the
port as well as the reference, and the reason it is allowed to is that what it contributes is
the harness's terminal, not either runtime's behaviour. Where the platform has no pty
(Windows) it answers `{"unsupported": …}` and the suite emits a note naming what went
unmeasured, rather than a case nobody earned.

Suites are discovered by **directory listing**, not by a registry someone has to remember to
edit. Drop a module in `suites/` and it runs.

## The four kinds of case

Each case is `{ name, kind, expected, actual, ruling? }` where `expected` is Python's answer
and `actual` is Node's.

- **`bytes`** — compared as buffers. The strongest claim; satisfies `--require-byte-identical`.
- **`string`** — compared as text.
- **`json`** — compared structurally.
- **`ruling:`** — a case that is **supposed** to differ. It carries the reason, it is
  *required* to differ, and **a ruling whose case has quietly started matching also fails**,
  with `STALE RULING: the case no longer differs`.

### A ruling pins the wording, not the outcome

This distinction cost a defect once and is the harness's sharpest edge, so read it twice.

A `ruling:` case fails when the two sides **match**. That means a ruling can only ever prove
"these two sentences still differ" — it cannot prove "both sides still refuse". If the Node
side silently went back to *answering* where Python refuses, all 50 `checkSchema` rulings
would have stayed green, because an answer and a refusal are also different strings.

So wherever the *refusal itself* is the property, it gets **its own non-ruled case comparing
the refusal bit** alongside the ruling that compares the words. Both exist today for
`checkSchema`, for the constructor-less YAML tags, and for the reader's pdf/doc/rtf rulings
in `docread` and `wire` — where each ruled fixture also carries a literal saying which side
is *required* to refuse it, so a port that quietly started reading a PDF fails as loudly as
a reference that stopped. The utf-7 ruling in `docread` is the inverse shape: both sides
*read* the file and the row differs by one codepoint, so its companion pins that neither
side refuses and that everything around the ruled row (kind, part count, row count,
omissions) still matches.

### Rulings have to be shown to have teeth

The review unit found **3 of 19** rulings that could never have failed: one compared a JS
`str.replace` against itself (differs iff the text has a newline, i.e. always), and two
compared `'(valid)'` against `'null'` while *both* runtimes said valid, because their
instances were arrays and `minimum`/`pattern` never fired.

If you add or touch a ruling, demonstrate it: make the case match and confirm the run goes
red with `STALE RULING`.

## Finding the reference interpreter

In order:

1. `--python <path>` or `BANTAMKIT_CONFORMANCE_PYTHON`
2. `<repo>/.venv/bin/python`, `<repo>/.venv/Scripts/python.exe`
3. the same two under the **main** worktree, resolved via `git rev-parse --git-common-dir`

Step 3 matters because the harness is usually run from a worktree, where `.venv` is a symlink
that may not resolve. CI has no `.venv` at all, so the workflow writes
`BANTAMKIT_CONFORMANCE_PYTHON=$(python -c 'import sys; print(sys.executable)')` into
`GITHUB_ENV` before the step.

## A reference child that stops answering

Each reference script is bounded at **600 s**, killed with `SIGKILL`, and reported as its
own failure naming the script, the interpreter, and whether the child had written anything:

```
conformance: reference script did not finish within 600s and was killed
  script : .../tools/conformance/ref/store_ref.py
  python : .../.venv/bin/python
  stdout : nothing at all
  stderr : nothing at all
```

The bound is measured, not chosen. Instrumenting `runPython` over a full `--all` run timed
355 calls; the slowest was `store_ref.py` at **50,139 ms** and everything else finished under
1.5 s. 600 s is twelve times the slowest honest call, which leaves an order of magnitude for a
Windows runner and still lands far short of anything a working call reaches.

It exists because `spawnSync` waits forever. On 2026-09-05 a full run sat for **1h09m** with a
`shiftwork_ref.py` child stuck and produced no output at all — no case, no note, no error — and
ended only because it was killed by hand.

`.github/workflows/ci.yml` also caps each job at 30 minutes, and the ordering is deliberate:
the job cap kills the runner and reports "took too long", which names nothing, so this bound is
set to fire first and say which script it was.

**Demonstrating the arm** — `BANTAMKIT_CONFORMANCE_REF_TIMEOUT_MS` overrides the bound so the
failure can be watched rather than asserted:

```
BANTAMKIT_CONFORMANCE_REF_TIMEOUT_MS=1 node tools/conformance/run.mjs --suite validate
```

exits 2 and names `validate_ref.py`. Under an override the message says so and prints the
default instead of claiming the twelve-times-headroom sentence, which would be false. The
override is a demonstration seam, not a knob for slow machines: if a real call needs more than
ten minutes, the call is the thing to look at.

## Reading the output

```
✔ store: 185 cases (97 json, 88 bytes), 0 differed
  note: [store] live index: 13472 bytes on disk, 13472 bytes rebuilt, 65 lines, 10528 bytes of headroom under the 24000 default
  ...
PASS: 6132 cases, 1500 byte-identical, 3267 exact-string, 1365 structural, 123 ruled-different, 0 failures
```

(The totals are a sample from one run and move with the suites: measured 4841 at `2c208f4`,
4874 once the `memory-compact` wire session landed — 33 cases — and 4878 after its review
hardened four of them, all on 2026-08-27; 4880 at `ce46fc3`, then 5512 on 2026-08-28 when
the `docread` suite landed — 575 cases, 8 ruled — and the `wire` suite grew from 232 to 289
with the `bantamkit_read` sessions, 7 of them ruled; 5600 at c8a62aa with 2 failures — the `badcd.xlsx` constructor-name artefact in the docread suite's `errorOf`, fixed in F4 — and 5760 after F4 on 2026-08-28: `docread` 633 -> 774 (9 ruled, the utf-7 ruling added), `wire` 289 -> 308 with the `read-edges` session; 116 ruled-different, 0 failures; 5855 at 905965a (job43 G2) with 6 failures — bzip2.docx and lzma.docx pending their ruling — and 5954 after G3 on 2026-08-29: `docread` 869 -> 935 (12 ruled: bzip2, lzma and RFC 2231 added, the seven checked-in fixtures and `a\x00b` read), `wire` 308 -> 341 with the `read-round2` session (20 ruled); 122 ruled-different, 0 failures; and 6132 after round 3's H3 on 2026-08-29 — at 643e323 the `docread` suite did not START, a name-collision throw over the checked-in `corrupt-deflate.docx`, lifted so the checked-in bytes win — `docread` 935 -> 990 (13 ruled: the `<!ATTLIST>` ruling added with its both-read companions; six round-3 checked-in fixtures, three `charset-<label>.eml` parts and the `<xmp>` charref unruled), `wire` 341 -> 371 with the `read-round3` session (unruled, 20 ruled unchanged), and the new `charsets` suite, 93 cases (`node tools/conformance/run.mjs --all`: 6132 cases, 123 ruled-different, 0 failures).

**AMENDED 2026-09-04, review round 4 (M6 / I3-F4): the `6132 cases, 123 ruled-different,
0 failures` above did NOT reproduce, and one of the two reasons was a defect.** Measured at
`952586e`, the same command answered `6199 cases, 125 ruled-different, 0 failures`. The CASE
total legitimately co-moves with the operator's live memory store — that is a standing fact of
the corpus-backed suites, and CI, which has no store, says so in its own notes. The RULED count
must not, and it moved because two more rulings had landed since; a ruled count is a decision
total, not a corpus function, and the record read as if the whole triple were rerunnable.
Worse, at that same commit the command FAILED on a clean checkout: `runtime-ts/assets/` is
gitignored and only `prepack` creates it, so the `--assets-root` ruling went stale and the gate
went red on any tree that had not published a tarball. That is fixed in this round — the `cli`
suite vendors the pack itself and asserts it as a precondition — so the number below is the
first one in this paragraph that a fresh clone can reproduce.

**Measured at `1cf8df2`, on this branch, by running it:**

```
PASS: 6280 cases, 1535 byte-identical, 3271 exact-string, 1474 structural,
      127 ruled-different, 0 failures
```

Against `6199 / 125` at `952586e`: **+81 cases and +2 rulings**, and every one of them is
named. The two new rulings are `hz.eml` and `iso2022kr.eml` (`docs/porting.md`, "`hz` and
`iso-2022-kr` on Node") — the divergence H1 uncovered, priced this round. The cases: `codec`
and `store` +2 for I3b's corpus-integrity gates; `cli` +1 for the pack precondition; `docread`
999 -> 1062 (the fixture-shadow declaration; `max-column.xlsx`, `xfd-column.xlsx`,
`iso2022jp.eml`, `hz.eml`, `iso2022kr.eml` and three `charset-raises-*.eml`, plus the two
column-ceiling literals — and twelve cases that appeared because six `charset-*.eml` fixtures
stopped being refused, see the note below); `memorycli` 210 -> 212 for the two eviction-order
literals; `charsets` 93 -> 88, which is a DROP, because H1 (`666f14f`) removed seven byte
tables that were never byte codecs and this round added two key-set cases (86 + 2); `wire`
371 unchanged, one case removed and one added.

**AMENDED 2026-09-05, twice, on the `feat/tool-usage-ledger` branch.** The `archive <name>`
subcommand took the run to `6294 / 130` — `memorycli` 212 -> 250 and three new rulings, all
of them the `archive -h` help form joining the four that were already ruled. Review round 5
of that subcommand then took it to:

```
PASS: 6316 cases, 1560 byte-identical, 3272 exact-string, 1484 structural,
      130 ruled-different, 0 failures
```

**+22 cases, no new ruling**, every one of them in `memorycli` (250 -> 272) and every one
added because a mutation showed the existing case could not see the thing it was named for:
two `unreadable-*-archive` rows reaching the two new "could not be stat'd" sentences that
NOTHING referenced (both were corrupted in the Node build and `--all` stayed at 0 failures);
two typed-literal `content-of-…` cases on the already-archived refusal, because
`archived-names: ['alpha']` is what the refusal AND the overwrite both leave; one
`archived-at-step-2` literal, because a round trip's CLOSING state is also what a jointly
dead archive/restore pair leaves; and two name-validation scenarios. The mutation counts are
in the commit messages.

**A number in this paragraph that was measuring nothing:** the three `charset-<label>.eml`
cases counted in the `6132` line above sent their bytes `8bit`, which made the file's HEAD
undecodable, so the container sniffed `unknown` and BOTH runtimes refused before any codec was
consulted. They were green and they pinned a refusal. Corrected to `quoted-printable` this
round; the cases they now generate are real.)

**AMENDED 2026-09-06 — job44 (`fix/job44-register-drain`), the register-drain job.** Measured
at the tree that bumps the version to 0.29.2, on Node v25.2.1 and `.venv` CPython 3.12.13,
with the runner given a message of its own — `pytest` and `run.mjs --all` in one message hang
each other, measured at over an hour with a stuck reference child, and about two minutes apart:

<!-- provenance: value=6662 cases, 149 ruled-different, 0 failures; commit=f484c70 plus this commit's working tree; command=node tools/conformance/run.mjs --all -->
```
PASS: 6662 cases, 1614 byte-identical, 3397 exact-string, 1651 structural,
      149 ruled-different, 0 failures
```

Per suite, at that tree: `validate` 3015, `docread` 1107, `shiftwork` 596, `codec` 510,
`wire` 417, `memorycli` 310, `store` 186, `charsets` 148, `cli` 106, `recall-strings` 96,
`skillaudit` 94, `statusline` 52, `mcpreport` 25 — every one at 0 differed.

**AMENDED 2026-09-06 — job45 (`feat/job45-dream-precision-repomap`), roadmap row 5.** The
`dream` suite landed: 78 cases over 18 scenarios and a 16-term day-arithmetic boundary.

<!-- provenance: value=6760 cases, 149 ruled-different, 0 failures; commit=3f9bb55 plus job45's working tree; command=node tools/conformance/run.mjs --all -->
```
PASS: 6760 cases, 1654 byte-identical, 3397 exact-string, 1709 structural,
      149 ruled-different, 0 failures
```

Per suite, at that tree: `validate` 3015, `docread` 1169, `shiftwork` 596, `codec` 468,
`wire` 417, `memorycli` 310, `store` 186, `charsets` 148, `cli` 106, `recall-strings` 96,
`skillaudit` 94, `dream` **78**, `statusline` 52, `mcpreport` 25 — every one at 0 differed.

**THE TOTAL WENT DOWN BEFORE IT WENT UP, AND THE CAUSE IS THE OPERATOR'S STORE, NOT THIS
JOB.** Job45's own baseline run, before a line of the new suite existed, measured **6682**
against the 6724 job45's plan recorded — a fall of 42 with the suite code unchanged.
`codec.mjs` generates exactly THREE cases per corpus fact (emit, python-parses-node,
node-parses-python) over 65 adversarial facts plus the live project store, so 42 is 14 facts:
`codec` 510 -> 468, and 510 is precisely the number the job44 provenance line above records
when that store held 101 facts. It holds 87 now. `CORPUS_FLOOR` is 32, deliberately far below
any real store, so a shrink of that size passes silently — the floor exists to catch a corpus
that resolved to nothing, not to pin a number that moves whenever the operator saves or
archives a fact. Quote a total against the tree AND the store it was taken on.

Non-vacuity for the new suite is measured rather than asserted: **17 mutants applied and 17
killed**, each restored and sha256-verified. Fifteen were one-sided and reddened between 1 and
21 differential cases apiece. **The other two were symmetric** — the mtime tie-break flipped on
both runtimes at once, and the calendar edge moved by one day on both at once — and each
reddened exactly 2 cases, both of them literals, and not one differential case. That is the
shape `differential-is-blind-to-symmetric-regression` names, caught here by design.

**AMENDED 2026-09-07 — job45 (`feat/job45-dream-precision-repomap`), roadmap row 6.** The
`recall-gate` suite landed: 37 cases over 11 store scenarios, 3 layered scenarios, the
constant, and four literal pairs.

<!-- provenance: value=6797 cases, 149 ruled-different, 0 failures; commit=3f9bb55 plus job45's working tree; command=node tools/conformance/run.mjs --all -->
```
PASS: 6797 cases, 1667 byte-identical, 3406 exact-string, 1724 structural,
      149 ruled-different, 0 failures
```

Per suite, at that tree: `validate` 3015, `docread` 1169, `shiftwork` 596, `codec` 468,
`wire` 417, `memorycli` 310, `store` 186, `charsets` 148, `cli` 106, `recall-strings` 96,
`skillaudit` 94, `dream` 78, `statusline` 52, `recall-gate` **37**, `mcpreport` 25 — every
one at 0 differed.

**THE WHOLE DELTA IS THE NEW SUITE, and that is checked rather than assumed.** 6760 -> 6797
is +37, and diffing the per-suite lines of the two runs — one taken before a line of the new
suite existed, one after — shows every other suite at a byte-identical count. The operator's
store held 87 facts for both runs, so `codec`'s 3-cases-per-fact did not move this time. It
is still the reason a total must be quoted against the tree AND the store.

Non-vacuity: **22 mutants applied on a `cp -R` copy, 21 killed and 1 equivalent by design.**
A control run on the unmutated copy is green, so a red result is the mutation. Eighteen were
one-sided — twelve against the reference, six against the port — and reddened between 1 and
17 differential cases apiece; the survivor is the gate
moved below the top-`k` slice, which both runtimes' implementers independently proved
equivalent (the survivors are always a prefix of the score-sorted list), so this suite
deliberately writes NO case that could distinguish the placement. Two of the one-sided
mutants are worth naming because they each pin ONE case: the range check MOVED to after the
facts are read — not deleted, so every readable store still refuses correctly — is seen by
exactly one case, the unreadable-store ordering; and a floor that ignores the ratio entirely
(`floor = max(...)`) is the only mutation an explicit `0.0` can see, which is what a no-op
default means.

**Four more symmetric mutants, and each reddened only literals.** The constant flipped on
both runtimes at once, the sentence respelled on both, `>=` weakened to `>` on both, and the
floor made absolute on both: **zero differential cases red** in every one of the four, and 2,
2, 4 and 2 literal cases respectively. That is `differential-is-blind-to-symmetric-regression`
measured a second time, on a second suite.

**Two vacuous cases were found and dealt with, both tree comparisons that survived all 22
mutants.** One was repaired: a multi-ratio scenario whose call list began at `0.0` stamped
every fact on the first call, so its end state was saturated and no later call could change
it — the list is now `1.0 -> 0.6 -> 0.5`, none of which admits the weakest fact, and the tree
reddens under three mutants. The other was DELETED: the unreadable-store scenario cannot
write a byte under any mutation of this rule, so its tree case could not fail. The claim it
was meant to carry — a refused ratio touches no disk — is made non-vacuously by the six-ratio
scenario over a readable store, whose tree reddens when the range check is deleted and `-0.1`
stamps all four facts.

**What job44 added, as its own units measured it** (the totals between the `6316` above and
this one are recorded where they were made — row 11 of `docs/roadmap-toolbox.md` for
`skill_audit`, and `docs/eval-data/` for the units here — rather than re-derived as
arithmetic in this paragraph):

* **`charsets` 88 -> 148, 0 -> 12 rulings** (unit U18). The CJK residual is pinned against a
  recipe checked in at `tools/conformance/ref/cjk_ref.py` instead of a script nobody kept.
  Each codec gets one ruling and four NON-ruled literal companions — match count, a digest of
  CPython's own answers, a digest of ICU's own answers, and the first disagreeing input with
  both answers. **The justification for the companions is a probe, not taste:** appending the
  same string to BOTH sides for all ten codecs left every ruling green and every match count
  green while 30 anchor cases went red, so a ruling-only pin would have passed that run.
* **`docread`: the `bzip2Styles` ruling, two non-ruled disclosure companions, and a CONTROL**
  (unit U17). The control is `deflate-date-styles.xlsx`, the same `xl/styles.xml` content and
  CRC behind method 8 instead of 12, pinned as a literal on both sides — without it, a reader
  that stopped resolving date styles altogether would make the ruling start MATCHING and be
  reported as stale, which reads as good news.
* **+82 cases in one change: `docread` +29, `memorycli` +38, `wire` +15** (unit U3), covering
  every behaviour change the job landed, with `ruled-different` unmoved at 149 — every case
  added is an unruled comparison or a typed literal. New machinery came with them: a summaries
  protocol in `docread_ref.py` (rows as SHA-256 plus counts and edges) so a 16 MiB fixture
  costs one digest rather than two 16 MiB comparisons; `links:` fixture support in `memorycli`
  with a Windows symlink probe that skips by name; and a `{conformance: write}` driver
  directive honoured in lock-step by both wire loops and never forwarded to the server.

**The mutations are the reason to believe any of it, and two are worth quoting.** Removing the
`lexists` guard from BOTH sides made both mutants agree on "a filesystem error stopped the move
of back" — a sentence false about a move nobody attempted — and the differential was blind to
it. Keying the document cache on `realpath` alone on both sides left the differential green
while the typed literals went red. Every mutation this job applied was applied SYMMETRICALLY,
and in every case the differential stayed green while the typed literal went red, which is the
whole reason the literals are there.

**Not everything measured this job became a case, and one refusal is deliberate.** The zlib
damaged-member cause clause differs between the two runtimes on macOS (803 of 6,306 co-raising
inputs) and not at all against a stock madler zlib, because the phrase comes from whichever
`libz` the reference is linked against. Its expected value is a function of the HOST, so a
ruling would be red where the sides agree and a parity case red where they do not; it is
recorded in `docs/porting.md`'s gaps with the corpus and the commands, and NO case was written.

**AMENDED 2026-09-10 — job46 (`feat/job46-register-and-agent-stack`), `docs/porting.md`
register item 7.** The band in which `compact` was a no-op is closed on both runtimes, and the
gate for it is `wire.mjs`'s new `index-band` session plus a ceiling-parity sweep in
`store.mjs`. This entry records a RED the harness found and a red it could not have found.

<!-- provenance: value=7064 cases, 149 ruled-different, 0 failures; commit=55575c3 plus J46-6's working tree; command=node tools/conformance/run.mjs --all -->
```
PASS: 7064 cases, 1790 byte-identical, 3423 exact-string, 1851 structural,
      149 ruled-different, 0 failures
```

Against the commit this unit started from (`55575c3`): **7034 cases, 149 ruled-different, 1
failure**. The delta is +30 cases — `store` 186 -> 189 and `wire` 417 -> 444, every other suite
at a byte-identical count — and `ruled-different` did not move, so nothing in the job became a
deliberate divergence.

**THE ONE FAILURE WAS ALREADY THERE, AND THE UNIT THAT CAUSED IT COULD NOT HAVE SEEN IT.**
`memorycli/compact-spares-feedback-until-the-other-classes-are-gone/archived-names` pinned
`['cpj','dpj']` as a literal. Bisected by RUNNING rather than reasoned: green at `6e506ca`
(310 cases, 0 differed), green at `181744a`, **11 differed at `87cc1f7`** — the reference-only
commit — and 1 differed at `55575c3` once the port caught up. `87cc1f7`'s own verify was
`.venv/bin/python -m pytest runtime-py/tests -q`, which does not run this harness at all, so a
unit that changed a memory-store default had no gate that could see the suite comparing the
two runtimes over that default. **The verify for a unit that changes shared-store behaviour is
`--suite <the suites that drive that store>` beside its own unit tests**, not the unit tests
alone.

The repair is an explicit `--reserve 62` on that scenario, not a bumped literal. Bumping it to
the three names the new default archives would also be green and would make the case's answer
identical to its sibling `compact-archives-feedback-once-nothing-else-is-left`, so the pair
would stop separating "the priority holds" from "the priority is not a veto" — the only thing
the pair exists for. An explicit reserve is what every eviction-order node here already passes,
so the case fails on ORDER and never on reserve policy. Checked: under a symmetric removal of
the class rank from both runtimes the repaired case still goes red.

**Non-vacuity, and the symmetric one is the finding.** Three mutations, each applied to a
`cp -R`/`git checkout` copy and reverted, with a green control either side:

* `Math.floor` -> `Math.trunc` in the port's `undegradedIndexCeiling`: **2 red**, both new
  ceiling cases.
* the `- 1` dropped from the same expression: **2 red** — and with the corpus trimmed to
  budgets that are NOT multiples of ten, the ceiling case goes **GREEN** under that same
  mutation. That is why the corpus carries a membership case pinning that both divisibility
  classes are still in it.
* **the default reserve reverted to `budget - largest line` on BOTH runtimes at once** — the
  exact change job46 made, undone symmetrically. `--suite memorycli`: **310 cases, 0 failures,
  green.** `--suite wire`: every per-frame differential comparison **green**, and 6 red, all of
  them per-side literals. A fourth mutation, the eviction class rank removed from both sides,
  reddened 4 literals in `wire` and 2 in `memorycli` and again not one differential case.

So the differential half of this harness was blind to the whole of register item 7 in both
directions, which is why `index-band`'s four assertions per side are literals and not one
runtime's answer handed to the other.

**GitHub Actions is off for this account — it bills the user — so nothing here was checked by
CI and nothing in this repository should be written as if it were.** The substitute is four
local gates, each run alone. At this tree:

<!-- provenance: value=2416 passed, 4 skipped, 1 deselected, 3 xfailed; commit=f484c70 plus this commit's working tree; command=.venv/bin/python -m pytest runtime-py/tests -q -->
<!-- provenance: value=All checks passed!; commit=f484c70 plus this commit's working tree; command=.venv/bin/ruff check runtime-py -->
<!-- provenance: value=595 tests, 593 pass, 0 fail, 2 skipped; commit=f484c70 plus this commit's working tree; command=cd runtime-ts && npm test -->
`.venv/bin/python -m pytest runtime-py/tests -q` **2416 passed, 4 skipped, 1 deselected,
3 xfailed**, with `grep -iE 'warnings summary|Warning'` over the run returning nothing;
`.venv/bin/ruff check runtime-py` **All checks passed!**; `cd runtime-ts && npm test`
**595 tests, 593 pass, 0 fail, 2 skipped**; and the `--all` line above. A pass count is a
function of repo content rather than of test code, so each is quoted with the tree it was
measured at and none of them is a standing number.

**The notes are part of the result, not decoration.** Several measurements this project
depends on exist only there — the live index byte count, the corpus SHA on both sides, how
many emitted files carry PyYAML's 80-column wrap, and the one remaining `NOT MEASURED HERE`
item that only a Windows runner can settle.

A failure prints both sides in full:

```
✖ store/os.replace names both paths
    python : "[WinError 3] The system cannot find the path specified: '…' -> '…'"
    node   : "[Errno 2] No such file or directory: '…' -> '…'"
```

## The real store is copied, never opened in place

**The size of that store is not written down here on purpose (corrected 2026-09-04, review
round 4).** Three places used to say "the real 65-fact store" — this line and the `codec` and
`store` suite headers — while the store was at 99 facts / 20,767 bytes when this line was last
read. A count of a directory the operator writes to every day cannot be kept true in prose, and
a wrong one reads as a claim about the corpus a case was measured over. Every run prints
today's number in its own notes (`real corpus: N facts copied from …`, and `live index: N bytes
on disk`), and the corpus-integrity case added by I3b is what makes a SHRINKING corpus a
failure rather than a smaller number. These are pointers, not records, so they are corrected in
place.

The `store` suite uses the live fact store as a fixture because synthetic facts do not carry
the shapes real ones do. It **copies it to scratch with
`cpSync(..., { preserveTimestamps: true })`** and runs there. Timestamps are preserved so the
`created`-from-mtime fallback reads the same number on both sides instead of two `cp` clock
samples.

Never point a suite at a store it does not own. A defect in exactly this area destroyed a
13,472-byte index once already.

**AMENDED 2026-09-19 — `codec` no longer reads the live store at all (J55-1).** It generates
exactly three cases per corpus fact, so reading a gitignored directory the operator writes to
all day made the suite's SIZE an input nobody could reproduce: job54 recorded 8166, 8169 and
8172 cases from `--all` at one unchanged commit, and J55-1 measured `--suite codec` going
**390 → 393 → 390** at `2b5c2ad` across one `memory_save` and its removal, with no code
change. Its real half is now **57 fact files frozen in git** at
`tools/conformance/fixtures/codec-corpus/`, copied byte for byte out of the live store on
2026-09-19 with four left out and named in that fixture's `README.md`; the adversarial set is
unchanged at 65. `--corpus` / `$BANTAMKIT_CONFORMANCE_CORPUS` therefore steer `store` only.
Measured at `2b5c2ad` plus this change, three consecutive runs and a run with an extra fact in
the live store: **379 cases, 0 failures** every time. The floor case is kept and joined by a
typed literal pinning the exact committed file count — `CORPUS_FLOOR` is 32 and would sit green
through a fixture that lost twenty files. Shown red rather than asserted: removing one fact
reds 1 case at 376, halving the corpus to 28 reds 2 at 292, deleting the fixture reds 2 at 208.

## Platform

The harness runs on ubuntu and Windows in CI. Two results are **Windows-only by
construction**. The first has since been read off a runner, so its note now carries the
measurement and cites the run; only the second still prints `NOT MEASURED HERE` on macOS or
Linux:

- **The index-budget arithmetic.** `write_text` translates `\n` to `\r\n` on Windows while
  `_check_index_budget` counts the untranslated text. Measured on the runner as exactly one
  byte per line: `index.md` 42 bytes on disk against 41 counted (1 line), a fact file 134
  against 124 (10 lines), a checkpoint 2609 against 2516 (93 lines). CPython gates the
  translation on `#ifdef MS_WINDOWS`, so macOS cannot construct the state. **The port now
  reproduces the arithmetic**, difference included: the budget counts the LF text and the
  writer translates, so the disk file is one byte per line larger than the number checked —
  on both runtimes, on both platforms.
- **The Win32 message table.** `FormatMessage for every winerror the port claims to render`
  asks `ctypes.FormatError` for all fifteen wordings, and `ctypes.FormatError` exists only on
  Windows. Off Windows the case does not run and the notes say so.

**The CRLF ruling is gone.** It was the only ruling in the codec suite and it is now two
ordinary cases: `toCrlf` against CPython's own `newline="\r\n"` translation, and
`Path.write_text` on whatever platform is running. Both are decidable everywhere.

Set `.gitattributes` to `* -text`. Without it, `core.autocrlf` on the Windows runner image
changes the working-tree bytes and the same commit produces a different `assets_digest`.
