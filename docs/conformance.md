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

## The six suites

| suite | what it compares |
|---|---|
| `codec` | fact-file frontmatter: emit byte-identically, and parse each other |
| `recall-strings` | the binding layer: every sentence an empty recall can produce |
| `shiftwork` | the checkpoint writer: `ensure_ascii`, `sort_keys`, separators, `5.0` |
| `store` | save/recall/index: the directory after the call, byte for byte |
| `validate` | the validator: every sentence a schema failure can produce |
| `wire` | the MCP surface: seven tools, two templates, and the frames themselves |

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
side silently went back to *answering* where Python refuses, all 53 `checkSchema` rulings
would have stayed green, because an answer and a refusal are also different strings.

So wherever the *refusal itself* is the property, it gets **its own non-ruled case comparing
the refusal bit** alongside the ruling that compares the words. Both exist today for
`checkSchema` and for the constructor-less YAML tags.

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
✔ store: 184 cases (96 json, 88 bytes), 0 differed
  note: [store] live index: 13472 bytes on disk, 13472 bytes rebuilt, 65 lines
  ...
PASS: 4463 cases, 804 byte-identical, 3162 exact-string, 497 structural, 73 ruled-different, 0 failures
```

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
