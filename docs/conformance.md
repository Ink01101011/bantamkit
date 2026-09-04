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

## The twelve suites

| suite | what it compares |
|---|---|
| `cli` | the `bantamkit-mcp` command line as a process: stdout, stderr, exit code |
| `charsets` | `runtime-ts/src/charsets.ts` against the live CPython codec registry: the file against what `runtime-ts/scripts/charsets-table.py` writes today (header excluded), all 256 bytes of every single-byte codec decoded by the reference against the port's table, the alias map and the module list |
| `codec` | fact-file frontmatter: emit byte-identically, and parse each other |
| `docread` | the reader as a library: `sniff`, the rows per part, the omission dicts, every `DocumentReadError` sentence and the `page()` window over the same 99 paths (96 files, plus `''`, `a/b/.` and `/dev/zero`, which are not), plus the thirteen checked-in fixtures under `runtime-py/tests/data/docread/` (a checked-in name wins over a built one), `a\x00b`, three `charset-<label>.eml` parts over the charset table's five bytes and the `<xmp>` 4301-digit charref, and the rulings — pdf/doc/rtf (refused on Node), bzip2/lzma (read by the reference, refused on Node by method number), utf-7, RFC 2231 and `<!ATTLIST>` defaults (both read, one row apart) — each with its refusal-bit companions |
| `mcpreport` | `--mcp-report` as a process, over one synthetic host-log/event-log pair |
| `memorycli` | `bantamkit-memory` against `python -m bantamkit.memory` as processes: the transcript of every step, the exit codes, and the store afterwards |
| `recall-strings` | the binding layer: every sentence an empty recall can produce |
| `shiftwork` | the checkpoint writer: `ensure_ascii`, `sort_keys`, separators, `5.0` |
| `statusline` | `--statusline` as a process, over synthetic event logs ([statusline.md](statusline.md)) |
| `store` | save/recall/index: the directory after the call, byte for byte |
| `validate` | the validator: every sentence a schema failure can produce |
| `wire` | the MCP surface: ten tools, one prompt, two templates, and the frames themselves — including a `bantamkit_read` session over the reader's files and its event-log records, and a `read-edges` session over the inputs F2/F3 fixed (bare `&`, a bad EOCD offset, a 4301-digit key, `''`, `a/b/.`, offset 2**53+1 sent raw, `/dev/zero`), and a `read-round2` session over round 2's (part `"null"`/`"[1]"`/`"{}"` as sent, offset `"null"` as the one `isError`, a NUL in the path, the encrypted member, and the bzip2/lzma and RFC 2231 rulings with companions), and a `read-round3` session over round 3's (the `ß1` cell ref, method 9, the encrypted `mimetype`, bad CRC and corrupt deflate as literal sentences on each side, the capped `<p>` charref, `memory_save` with `links` as a 4303-character string refused as `list_type`, and the zero-row part's `has no rows` sentence pinned on `read` id 12) |

`cli`, `mcpreport`, `memorycli` and `statusline` are the odd ones out and deliberately so:
every other suite compares two library functions, and that comparison cannot see which stream
a message lands on or what the process exits with. Those four spawn both CLIs and diff the
three things only a process has. `mcpreport` and `statusline` reuse `ref/cli_ref.py` rather
than adding a second reference script — it already is "spawn the CLI with this argv and hand
back both streams", which is their question with a different argv. `memorycli` carries its
own `ref/memorycli_ref.py` because it compares a fourth thing those three do not: the store
on disk after every step.

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

**A number in this paragraph that was measuring nothing:** the three `charset-<label>.eml`
cases counted in the `6132` line above sent their bytes `8bit`, which made the file's HEAD
undecodable, so the container sniffed `unknown` and BOTH runtimes refused before any codec was
consulted. They were green and they pinned a refusal. Corrected to `quoted-printable` this
round; the cases they now generate are real.)

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

The `codec` and `store` suites use the live 65-fact store as a fixture because synthetic
facts do not carry the shapes real ones do — 35 of the 65 carry PyYAML's 80-column wrap.

They **copy it to scratch with `cpSync(..., { preserveTimestamps: true })`** and run there.
Timestamps are preserved so the `created`-from-mtime fallback reads the same number on both
sides instead of two `cp` clock samples.

Never point a suite at a store it does not own. A defect in exactly this area destroyed a
13,472-byte index once already.

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
