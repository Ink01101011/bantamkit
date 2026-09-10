# Porting CPython behaviour to Node

`runtime-ts/` is a second implementation of the MCP server, in TypeScript, that shares a
memory store with the Python one. This is the maintenance manual for it: what was ported by
hand, why the obvious library was rejected, and which behaviours must never drift.

For how to verify any of it, see [conformance.md](conformance.md). For how to run the
package, see [`runtime-ts/README.md`](../runtime-ts/README.md).

## The bar, and why it is this high

The store on this machine holds real facts written by CPython and PyYAML. Both servers read
and write it. A port that "basically" round-trips a fact corrupts it on the first save,
silently, in a file the user believes is theirs.

So the rule is: **the two runtimes emit the same bytes, and every place they do not is a
written ruling with a measured reason.** Never an accident found later.

## What the port actually covers

The behavioural closure was measured with `sys.settrace`, not guessed from imports: **545
executable statements across 7 modules**. The AST import closure is 8,396 lines across 20
modules, but most of that arrives through `__init__` re-exports and never executes.
`client.py` and `memory/divergence.py` execute **zero** call-time lines on the MCP path.

Two earlier estimates were wrong — ~1,846 lines and ~3,700 lines — both from reading imports
instead of running the code. If you need this number again, measure it again.

```
src/memory/pyfs.ts        the CPython os/pathlib syscall seam
src/pyjsonschema.ts       the validator, including best_match
src/memory/pyyaml.ts      the PyYAML 6.0.3 emitter and SafeConstructor
src/memory/store.ts       MemoryStore
src/pyjson.ts             CPython's json, both dump and raw_decode
src/memory/layers.ts      store binding and the layered walk
src/memory/factfile.ts    the fact codec
src/contract.ts           contract loading and schema_error
src/memory/component.ts   Memory
src/memory/dream.ts       the cross-layer consolidation pass (dream.py)
src/shiftwork.ts          clock_in / clock_out / status
src/mcp/*                 server, identity, arg coercion, transport, SDK JSON
src/pyargparse.ts         argparse's help, usage, errors and parse rules; textwrap
```

## `argparse` and `textwrap`, ported by hand

`cli.ts` used to carry one hardcoded `USAGE` string and a `switch` over whole argv tokens.
`tools/conformance/suites/cli.mjs` — the first thing in the repository ever to run the Node
CLI as a PROCESS — found four defects in it at once: the help went to **stderr** and was one
line where CPython puts 678 bytes on **stdout**, the constant had already gone stale (no
`[--assets-root]`), `--store=/path` exited 2 against a reference that accepts it, and
`--inde` did not abbreviate. `src/pyargparse.ts` replaces all of it: there is no literal
usage string anywhere in the runtime, only a `ParserSpec` in `cli.ts` that the formatter
renders at whatever width `shutil.get_terminal_size()` would have reported.

**`textwrap` had to be written.** `grep -rln 'textwrap\|wrap('` over `runtime-ts/src/`
returned nothing and Node has no stdlib equivalent, so `wrap`/`fill` are a port of
`TextWrapper`, not a call into one.

**`break_on_hyphens` IS implemented, and the decision was a measurement.** Sweeping every
width from 5 to 300 against `textwrap.wrap` with the flag on and off: it changes this help
text at help widths 27–31 and description widths 34–39 (plus everything below 18). Those are
reachable from an ordinary `COLUMNS` — 53 through 57, and 36 through 41 — not only at the
absurd widths the 11-column floor allows. The conformance matrix (60/80/105/106/200, and 80
by no-tty fallback) reaches **none** of them, so `runtime-ts/test/cli-surface.test.mjs` pins
four extra widths measured out of CPython: 15 and 20 (where the usage line takes the
long-prog branch and `_handle_long_word` breaks `project-store` at its hyphen), 38 (the
description splits at `per-`) and 55 (an option's help splits at `project-`).

**A coverage gap in the suite, named rather than hidden.** `_max_help_position` is
`min(24, max(width - 20, 4))` and it evaluates to 24 at every width the conformance matrix
uses. Mutating it to a hardcoded `24` leaves `--suite cli` at **0 failures**; only the three
narrow widths in `cli-surface.test.mjs` catch it. The conformance matrix cannot see that
constant move.

**NOT PORTED**, because these parsers cannot reach them and an unmeasured port is a
liability. This list is **shorter than it used to be**, and the reason is the second CLI:
`bantamkit-memory` is a subparsers tree with five commands, a required subcommand, a `type=`
that raises `ArgumentTypeError` and a positional under `restore`, so `consume_positionals`,
`_match_arguments_partial`, `_get_nargs_pattern`, `_check_value` and the `required_actions`
sweep were all written against the running CPython and ARE here now — this paragraph named
every one of them as absent. Re-derived against the `NOT PORTED` markers in
`src/pyargparse.ts`, what is still out is:

- every `nargs` outside the three `_getNargsPattern` names. `None` (a `store` or a
  positional), `0` (`store_true` and `help`) and `PARSER` are declared; `?`, `*`, `+`,
  `REMAINDER`, `SUPPRESS` and an integer count are not.
- `choices` on anything but a subparsers action — `_check_value` exists only on the arm that
  turns a bad subcommand into `invalid choice: …`.
- `required=` as a DECLARED field. Required-ness is a predicate here: every positional is
  required (`nargs=None`, and the one subparsers action is `add_subparsers(required=True)`)
  and no optional is. A future `required=True` on an optional, or a subparsers action
  without it, wants a field rather than the predicate.
- required mutually exclusive groups (`one of the arguments … is required`), and in
  `_format_actions_usage` the arm that strips the outer `[]` off a positional INSIDE a group.
- the `SUPPRESS` arm of `_format_actions_usage` (drop the action and the `|` beside it).
- `fromfile_prefix_chars`.
- `parse_intermixed_args`.
- in `textwrap`: `initial_indent`/`subsequent_indent` (argparse's only `fill` call sits at
  indent 0), `expand_tabs` and `replace_whitespace`, `fix_sentence_endings`, and
  `max_lines`/`placeholder`. Both `wrap` callers pre-normalise with argparse's own
  `re.compile(r'\s+', re.ASCII)`, so no tab or newline can reach the wrapper.

**Two divergences that are latent, not observable today.** `textwrap.wordsep_re` uses `\w`
and `[^\d\W]`, which are Unicode in Python and ASCII in JavaScript; every string in this
help text is ASCII, so nothing differs, and a non-ASCII help string would be a new
measurement. And **`options:` is interpreter-dependent**: 3.10+ prints `options:`, 3.9 and
earlier print `optional arguments:`. The port matches the pinned 3.12.13, so a 3.9 CI would
turn the `cli` suite red on the section heading — that would be a ruling, not a code change.

## Four libraries rejected, and what replaced them

### PyYAML's emitter — `js-yaml` cannot do it

35 of the 65 live fact files carry PyYAML's 80-column plain-scalar wrap, and **no `js-yaml`
option reproduces it.** The rule is not "break at 80":

> At a run of **exactly one** space, if `column` is **already** greater than 80 — checked
> *after* the preceding word is written — swap the space for a line break plus a two-space
> indent. A run of two or more spaces never splits. Columns are counted in **codepoints**.

Also ported: `SafeConstructor` for `bool` / `int` / `float` / `timestamp`. The `merge`,
`value` and `yaml` buckets raise.

Quoting is narrower than it looks. Only a **leading** `'` forces a quoted scalar — `it's`
emits plain. A `\n` produces a multi-line **single**-quoted scalar, not a double-quoted one.

### CPython's `json` — `JSON.stringify` is a different function

- `ensure_ascii=True` escapes `[^ -~]`. `DEL` escapes; `/` does not.
- With `indent=2` the item separator is `,` with **no trailing space**. The familiar
  `", "` / `": "` pair is the `indent=None` form.
- `json.loads` refuses a leading BOM by name —
  `Unexpected UTF-8 BOM (decode using utf-8-sig)` — while `raw_decode` has no such check and
  reports `Expecting value`. Both behaviours are ported, separately.

### `jsonschema`'s `best_match` — the descent inverts

`best_match(iter_errors(...))` returns a single error chosen by a relevance heuristic, and
the descent **inverts** preference via `heapq.nsmallest`, so inside `anyOf` / `oneOf` the
**deepest** child wins. A straightforward "most relevant error" implementation picks the
wrong one.

`checkSchema` runs **before** validation, as `jsonschema.validate` does. It is the keyword
*shape table* applied recursively — deliberately not the metaschema, which would need
`$ref` / `$dynamicRef` support this validator does not implement. Measured over 50 malformed
schemas: 50/50 refuse on both sides.

One trade taken deliberately: `{"pattern": "("}` compiles eagerly, which closes the wrong
answer at the cost of refusing Python-only regex syntax in branches that are never reached.
Ruled, with a measured case both ways.

Regex classes are not the same alphabet: `\d` in Python matches any Unicode decimal digit, so
the port uses `\p{Nd}` with the `u` flag.

### CPython's `listsort` — recall's tie-break can raise

`recall` sorts by `(score, name)`. With a non-string name the comparison **raises**, and
*which pair the sort probes first* decides which sentence comes out. So `count_run` and
`binarysort` are ported over `tuplerichcompare` — `==` down the tuple, `<` only at the first
position that differs.

Pinned by 50,000 seeded lists, `n` from 2 to 300: CPython's `sorted` raises on **45,629** of
them, and the port reproduces the order or the sentence for **50,000 of 50,000**.

Two shortcuts were tried and refuted. "Raise if any equal-score pair is incomparable" makes
the right *decision* 20,000/20,000 but the wrong *sentence* 1,087/30,000. "Just call `<` where
the scores tie" raises `'NoneType' and 'NoneType'` where CPython answers an order.

## `PyScalar`: what a `Fact` field holds

YAML frontmatter is not typed by the schema, so `description: 2026` gives Python an `int`.
The port originally refused such a file — which bricked the **whole store** for Node while
Python served it fine, for 13 of 17 scalar shapes.

A field now holds:

- a JS `string` when PyYAML resolves `str`
- `null` for `null`
- otherwise a frozen **`PyScalar`** carrying six observable things: the tag,
  `type(v).__name__`, `str(v)`, `safe_dump`'s spelling, `bool(v)`, and what `<` orders on.

**Two spellings and not one number**, because they part: `True`/`true`, `inf`/`.inf`,
`1e+50`/`1.0e+50`.

Nine places render a field, and all nine were found by making the corpus red rather than by
reading: `_index_line`, `_fact_path`, `_tokens` in both the duplicate gate and the recall
score, the recall tie-break, `created or _mtime_date(path)` truthiness, `list(links or [])`
truthiness *and* iterability, `_write_fact`'s `safe_dump` bytes, `component._format`, and the
layered `seen` set — which is Python `hash`/`==`, not `str`.

Helpers: `pyText`, `pyHashKey`, `pyEqualValue`, `pyCompareLt`.

Not every shape is representable. Three YAML **scanner** questions the codec has no scanner
for are ruled to differ, and `!` is filed alone because it is the one where **CPython answers
`None` and the port refuses**; `&`, `*`, `<<` and `=` refuse on both sides with different
words.

Surprises worth keeping: `1e+17` is a **`str`**, not a float — PyYAML's float regex needs a
`.` before the exponent. So are `00:00` and `y`.

## The syscall seam

`src/memory/pyfs.ts` exists so the rest of the port can call something shaped like `os` and
`pathlib` and get CPython's answers.

- **The errno three-way** in `store._listing` is keyed on `os.path.lexists`, deliberately not
  on an errno.
- **libuv's numbering is not CPython's.** `ENOENT` arrives from Node as `-4058` on Windows.
  Key on `os.constants.errno[code]`, never on the raw number.
- **`%r`, not `%s`.** `OSError.__str__` uses `repr` for the filename, so
  `[Errno 2] No such file or directory: "/a/it's.md"` — double quotes, because the path
  contains an apostrophe. `os.replace` prints **both** names; `filename2` is not decoration.
- **A dangling symlink is one shape on POSIX and two on Windows.** `symlink_to(t)` makes a
  FILE reparse point → `NotADirectoryError`, errno 20, winerror 267.
  `symlink_to(t, target_is_directory=True)` makes a DIR reparse point → `FileNotFoundError`,
  errno 2, winerror 3. POSIX collapses both to the second. A test that builds the wrong shape
  passes for the wrong reason. **libuv does not reproduce the first shape**: it opens the
  reparse point itself and reports `ENOENT` where `FindFirstFileW(p + "\\*")` reports
  `ERROR_DIRECTORY`, so `pyScandirNames` restates the shape before rendering the sentence.
- **`OSError.__str__` prints `[WinError %d]` when `winerror` is set,** and only calls through
  the WIN32 API set it. `open()` goes through the C runtime and keeps `[Errno %d]` with the
  UCRT's own wording — which is not glibc's, and not libuv's errno either: opening a
  directory is `EACCES` there where libuv says `EISDIR`.
- **libuv threw the Win32 number away.** `ERROR_FILE_NOT_FOUND` (2), `ERROR_PATH_NOT_FOUND`
  (3) and `ERROR_INVALID_NAME` (123) all arrive as one `ENOENT`, so which one CPython would
  have carried has to be RE-DERIVED from which component is missing and whether any
  component holds a character Win32 forbids. See `winerrorFor` in `pyfs.ts`.
- **`PureWindowsPath` is not `PurePosixPath` with backslashes.** `//a/b` is a share whose
  whole text is the drive and which has NO parents, `///a` is relative (pathlib's test is a
  SUBSTRING test and `'' in '?.'` is True), and `ntpath.isabs` disagrees with
  `PureWindowsPath.is_absolute` by design. All of it is pure algebra CPython computes
  identically on every OS, so keep it in flavour-explicit functions and drive them against
  `ntpath` from a laptop rather than from a runner.
- **`realpathSync` does not expand 8.3 short names**; only `realpathSync.native` does.
- One UTF-8 decoder in the package, with `ignoreBOM: true`, in `pyDecodeUtf8`.

## Where the two runtimes deliberately differ

| | reason |
|---|---|
| `build_id` | hashes the executing tree; two runtimes, two trees. `assets_digest` **is** identical (`sha256:d47dcf4b…` over 87 files, remeasured 2026-09-05; the `sha256:b03141bf…` this row carried was written at #75 and has been stale since the pack last changed) and that is the one that matters — but only because both walks now EXCLUDE `__pycache__`. That is a precondition, not a given: the pack ships eleven `.py` fixtures, `pip install` byte-compiles them, and on the published 0.27.0 artifacts the wheel answered `sha256:fa8372f6…` over 98 files against npm's `sha256:d47dcf4b…` over 87 while this row already claimed they were identical. Gated per side by `build_identity: a __pycache__ does not move assets_digest` in `tools/conformance/suites/wire.mjs` — per side, because pointed at one polluted pack both runtimes moved together and the cross-runtime comparison stayed green. |
| the event log's build identity | **not a difference — an omission, for this reason.** A `build_id` hashes the executing tree and the two runtimes are two trees (row above), so no build identity is a field in an event-log record at all; the `build_identity` record carries the COUNT of underivable fields instead. Same for `sessionId` (the server cannot observe it), pids and absolute paths. See [eventlog.md](eventlog.md). |
| the YAML scanner cases | the codec has no scanner; 5 shapes ruled, `!` filed alone |
| `checkSchema` wording | 50 cases; both sides refuse, the sentences differ |
| accounting via `fromJs` | an integral float; the `parseJson` route is byte-identical |
| on Windows, CRLF | **no longer a difference.** N11 reversed it: the emitter builds LF text, the WRITER translates, and the budget still counts the LF text — which is what CPython does. See [conformance.md](conformance.md). |
| the memory CLI's `prog` | `python -m bantamkit.memory` against `bantamkit-memory`. There is no third spelling: the reference's prog is a Python `-m` invocation and a pure-npm install has no Python in it, while `bantamkit-memory` names a console script CPython does not install. It moves the usage line, every `…: error:` prefix, and the two remediation sentences that name a command the reader must type — `lint`'s `try: … compact …` and `compact`'s `restore one with: …`. It also moves the WRAP, because argparse's hanging indent is `len(prefix) + len(prog) + 1`: 10 columns apart at COLUMNS=80, and at COLUMNS=40 the two runtimes take different `_format_usage` branches outright. 24 ruled cases in `tools/conformance/suites/memorycli.mjs`, **all 24 PAIRED with an unruled case over the same bytes after the substitution** since 2026-08-25 — 19 against an unruled case over exactly the same region (13 `…/stderr-raw` against `…/stderr`, 2 `…/remediation-line-raw` against `…/remediation-line`, and each of the 4 `w80/usage-block` rulings against its `usage-block-compensated`, which re-runs the reference 10 columns wider and requires the wrapped blocks to match exactly), and 4 `w200/prog-line-raw` against the unruled `w200/usage-block` that covers that same line 1 with the substitution applied. **The 24th, `help-top/w40/usage-block`, got its companion on 2026-08-25** and this row previously said it could never have one. The reason given was that no compensation exists at 40, because the reference sits in argparse's FLAT branch there and widening it over-corrects an indent that no longer depends on `prog`. That overlooks what widening actually does: the branch test is `len(prefix) + len(prog) <= 0.75 * (COLUMNS - 2)`, and COLUMNS is the term the compensation changes — at 40 the reference needs 33 against an allowance of 28.5 and goes flat, at 40+10 it needs 33 against 36 and hangs. So at the compensated width BOTH sides are in the hanging branch, where the compensation is exact, and the blocks match byte for byte. The emission condition in the suite is now `ruling` rather than `width === 80`, which is the property that was wanted all along: a companion belongs wherever a ruling is. `BRANCH_SPLIT_RULING`'s SIBLING argument — at COLUMNS=40 the three sub-parser forms are unruled and byte-identical, their longer progs putting both runtimes in the flat branch, so the split is a BAND the top parser alone falls out of rather than a second rendering algorithm — still holds and is still worth keeping, but it now stands beside a gate instead of in place of one. |
| `tools/list` key order | **key order only; the content is compared with keys sorted and is identical.** `mcp` 2.0.0's outbound serializer reorders the tool entry and its `inputSchema` on the way out: `memory_compact`'s manifest says `type, properties` and the reference emits `properties, type`; `memory_save` and `memory_recall` say `type, required, properties` and arrive as `properties, required, type`; the other six already read `properties, [required,] type[, title]` and arrive unchanged. `Tool.input_schema` is a plain dict and `model_dump_json` was measured to preserve manifest order, so the reordering has no seam this package can reach; the port serves the manifest bytes as written. Ruled in `tools/conformance/suites/wire.mjs`: `tools/list: the reference reorders keys the port emits in manifest order` is the ruling over the raw frame, and beside it the unruled `advertisement: id 2` compares the same frame with keys sorted, so a port that changed a VALUE rather than an order still fails. |
| the `index-budget-low` remedy | **the same substitution, one surface further out.** The degraded status report ends `archive or shorten facts with `…``, and `mcpserver.py` names `python -m bantamkit.memory compact` where `runtime-ts/src/mcp/status.ts` names `bantamkit-memory compact` — for the reason in the row above, and with no third spelling for the same reason. Printing the reference's command to someone holding an npx install is an instruction that cannot be followed. It is a LITERAL on both sides and not an import: neither MCP server imports its CLI module, so the coupling is held from OUTSIDE, by `runtime-py/tests/test_status_surface.py::test_the_index_remedy_names_the_command_this_install_actually_provides` and by `runtime-ts/test/server.test.mjs`'s degraded-report test, which reads `package.json`'s `bin` rather than spelling the name. Ruled in `tools/conformance/suites/wire.mjs`: `status-degraded: the remedy lines, raw` is the ruling, and it is a LIST, so a runtime that moved the report's copy and left the footer's alone fails it; beside it `…, after the one substitution` is unruled over the same sentences, and `…: the command each side tells the operator to type` pins the two literals. Changing either sentence alone reddens the run; making them equal fails as a stale ruling. |
| pdf, doc and rtf on Node | **the port identifies the three kinds and refuses them by name; the reference reads them.** `docread.py` reads PDF through `bantamkit.pdfread` (stdlib, written for this program) and real OLE2 `.doc` and `.rtf` through `/usr/bin/textutil`, a macOS built-in it probes at every call and refuses by name where absent. `docread.ts` has neither: `sniff` still names the container, the size on disk and the suffix disagreement exactly as `_refuse` does, and the remedy clause says which server can read it — `pdf is not readable by the Node server yet (the Python server reads it); see docs/porting.md` and `<doc|rtf> is read through /usr/bin/textutil by the Python server and not by the Node server; see docs/porting.md`. No runtime dependency is allowed into `runtime-ts` (one runtime dep, `package.json`), so the pdf side is a PORT and not an install: **job44 ports `pdfread`** and closes the pdf half of this row; doc/rtf stay refused on Node until a reader that is not a macOS binary exists. Ruled in `tools/conformance/suites/docread.mjs` — `extract: <fixture>: <kind> is RULED` over eight fixtures (`tiny.pdf`, which the reference READS to one row; `doc.pdf`, `sheet.xlsx.pdf`, `named.xlsx`, header-only PDFs both refuse; `real.doc` and `sheet.xls`, OLE2 signatures both refuse; `bad.rtf`, both refuse; `note.rtf`, read by the reference exactly where textutil is) — and in `tools/conformance/suites/wire.mjs`, `read-ruled: id 2..7` over the same shapes on the wire plus `read-ruled: the outcome sequence` for the event log. **Every ruling has two companions**: `…: the refusal bit each side is required to carry`, a literal `{python, node}` pair that says which side must refuse (the reference's bit is a function of `textutil_path()`, reported by the reference itself, never assumed), and where both refuse `…: both refuse (the refusal bit, side to side)`, the unruled comparison CLAUDE.md requires. On a host without textutil nothing is skipped: the rulings still differ and the companions still both refuse, and the suite's note prints which host it measured. Teeth demonstrated 2026-08-28: making the ruled cases match reddened all eight as `STALE RULING`. **AMENDED 2026-09-11 (J46-24). THE PROMISE IN THIS ROW WAS NOT KEPT, AND THE COST OF KEEPING IT IS NOW MEASURED.** The sentence above says "**job44 ports `pdfread`**". Job44 (`fix/job44-register-drain`) was the register-drain job; `NODE_REFUSED` in `runtime-ts/src/docread.ts` still contains `'pdf'` and the port still refuses it. The port is still owed — J46-2's AS-6 audit rules `pdfread` **product-and-must-port**, the only one of thirteen unported Python modules that is product. What J46-24 adds is the price, and it is NOT the module's 1402 lines. **Measured with stdlib `trace` over `runtime-py/src/bantamkit/pdfread.py` (1097 executable lines, 184 of them import-time defs and tables, so 913 BODY lines):** the whole two-runtime gate — `tiny.pdf` plus the three header-only PDFs, which is every PDF any suite compares — reaches **398 of 913 body lines (43.6 %)**. `runtime-py/tests/test_pdfread.py` reaches **695 (76.1 %)**. **Twenty-one functions are reached by the differential gate not at all**, and they are not the edges: `parse_cmap` (38 body lines — the `/ToUnicode` reader that IS this module's whole provenance argument), `_do_xobject` (37), `_png_predictor` (33), `_lzw` (30), `_cid_widths` (24), `_runlength` (15), `_flate`'s truncated/raw/leading-junk tolerance cascade (14 of which the gate reaches 0 and pytest 3), `glyph_to_unicode` and the AGL (12), `_parse_hex_string` (10), `_ascii85` (10), `_unvouched_rows` (8), `_tiff_predictor` (8), `_asciihex` (6), and the `PdfText`/`PdfPage` count properties. **`_lzw`'s 30 body lines are reached by NEITHER gate — not the conformance suite and not pytest.** So a port that turns this gate green ports 43.6 % of the module and ships the other 56.4 % as code no differential case can see, which this job has measured nine separate times to be the exact blind spot of a two-runtime suite. `pdfread.py`'s own docstring sets the standard the port would be breaking: "any decryption code here would be unmeasured code, which this program does not ship". **The extractor is not the hard part, and that is measured too.** Every CPython facility `pdfread` leans on has a Node equivalent, probed on this machine 2026-09-11 rather than assumed: `zlib.decompressobj().decompress` on a truncated stream ↔ `zlib.inflateSync(buf, {finishFlush: Z_SYNC_FLUSH})` (both recover `hello world hello world` from a 4-byte-short deflate; plain `inflateSync` throws `Z_BUF_ERROR`, which is why the option is load-bearing); `unicodedata.category` ∈ {Cc, Cf, Cn, Co, Cs} ↔ the single regex `/\p{C}/u` (verified true for U+0081/U+200D/U+E000/U+0378/lone surrogate and false for `A`); `cp1252`/`mac_roman` ↔ `TextDecoder('windows-1252')`/`TextDecoder('macintosh')`, which CONVERGE with CPython despite disagreeing — CPython raises `UnicodeDecodeError` on the five unmapped cp1252 bytes (0x81, 0x8D, 0x8F, 0x90, 0x9D) and skips them, WHATWG decodes them to the matching C1 control and `_vouchable` then drops them as `Cc`, so both sides omit the same five codes; `utf-16-be` ↔ `TextDecoder('utf-16be')`; `base64.a85decode` and bytes-mode `re` have no builtin, and are a hand-rolled decoder and the latin-1 1-byte-1-char string idiom respectively. **The one divergence no conformance case can pin is UCD SKEW.** `_vouchable` drops `Cn` (unassigned), and `Cn` is a function of the Unicode version each runtime ships: this machine measures CPython 3.12.13 at `unicodedata.unidata_version` **15.0.0** and Node v25.2.1 at `process.versions.unicode` **16.0**. A codepoint assigned in Unicode 16 but not 15 is dropped-and-counted by the reference and emitted by the port, and that difference moves with the installed interpreter and runtime rather than with either codebase — so it is a divergence a ruling would have to describe rather than pin. **Therefore the port is its own job, registered in `.shiftwork/backlog.md` (2026-09-11), and its cost is dominated by FIXTURES, not by arithmetic:** the ~25-line `tinyPdf` generator in `tools/conformance/suites/docread.mjs` is what the SIMPLEST possible PDF costs, and byte-exact fixtures reaching CMaps, CID fonts, LZW, both predictors, XObjects, ASCII85 and the flate tolerance cascade do not exist and cannot be borrowed. **What J46-24 DID land here is a hole in this row's own evidence.** The row says every ruling has two companions; `tiny.pdf` — the sharpest ruling in the file, the one PDF the reference READS — had the ruling and the refusal-bit literal `{python: false, node: true}`, and NOTHING pinning what the reference read. MEASURED by mutation 2026-09-11: truncating every row by one character in `pdfread._rows_from_runs` moved `tiny.pdf` to `Hello conformanc` and `node tools/conformance/run.mjs --suite docread` still answered **1169 cases, 0 failures** — the only thing that moved was a printed note, and a note is not a case. A ruling proves the two sides still DIFFER; it never proves the READING side still reads what it read. Closed by giving `tiny.pdf` the `reads`/`sentence` pair the bzip2/lzma entries already had, which the existing companion branch then emits unchanged: ``extract: tiny.pdf: the reference reads the row as measured (`Hello conformance`)`` and `extract: tiny.pdf: the port refuses in the sentence the ruling quotes`. **Suite 1169 → 1171 cases, 16 ruled-different, 0 failures. Teeth demonstrated BOTH ways 2026-09-11:** the row-truncating mutation now reddens the first case by name, and dropping `'pdf'` from `NODE_REFUSED` in the built `runtime-ts/dist/docread.js` reddens the second; both probes were reverted and the suite is green. |
| utf-7 on Node | **the two runtimes decode a MIME text part through two different codec registries, and only one of them has utf-7.** `docread.py` decodes a `text/*` part by its declared `charset` through CPython's codec registry, which has `utf-7`, so a part declaring `charset=utf-7` with `caf+AOk- done` in it reads as `café done`. `docread.ts` decodes through the WHATWG Encoding Standard's `TextDecoder`, whose label table deliberately has no utf-7 (the standard dropped it as a security hazard), so the label is unrecognised, the fallback is UTF-8, and the same bytes read as `caf+AOk- done` — one row on both sides, one token apart. Both sides READ the file; neither refuses. The port DOES now carry CPython's single-byte codec tables — `runtime-ts/src/charsets.ts`, generated by `runtime-ts/scripts/charsets-table.py` from the interpreter's own `encodings` package (79 single-byte codecs, 326 aliases, 121 modules at CPython 3.12.13 — **AMENDED 2026-09-04: 72 single-byte codecs.** Review round 4's H1 (`666f14f`) found the generator judging statelessness with a six-lead-byte probe containing neither ESC (`0x1b`) nor `~` (`0x7e`), so SEVEN stateful modules — `hz` and the six `iso2022_jp*` — had been written out with a 256-character byte table they cannot have. The generator now sweeps all 65,536 ordered pairs and refuses all seven; 326 aliases and 121 modules are unchanged) and pinned against the live registry by the `charsets` conformance suite (`src/charsets.ts is what scripts/charsets-table.py writes for the live registry`, plus all 256 bytes of every codec decoded by the reference and compared to the table) — so the earlier reasoning here, that a second registry would be a maintenance burden, no longer applies to byte tables. It still applies to utf-7: utf-7 is a stateful modified-base64 transform, not a byte table, the generator cannot write it out, and no decoder for it is written, so the label still falls to UTF-8 on the port. Ruled in `tools/conformance/suites/docread.mjs`: `extract: utf7.eml: utf7 is RULED` over the whole answer, with `…: the refusal bit each side is required to carry` pinning `{python: false, node: false}`, `…: both read (the refusal bit, side to side)` as the unruled companion, and `…: the same shape around the ruled row` comparing kind, part names, row counts and omissions unruled so the ruling cannot hide a second difference. Teeth demonstrated 2026-08-28: forcing the ruled case to match reddened it as `STALE RULING` (`node tools/conformance/run.mjs --suite docread`: 774 cases, 1 failure), then the probe was removed. |
| `hz` and `iso-2022-kr` on Node | **the same divergence as the row above, under two more names — two stateful escape codecs CPython has and the WHATWG Encoding Standard does not.** `docread.py` decodes a `text/*` part by its declared `charset` through CPython's codec registry, which has `hz` and `iso2022_kr`; `docread.ts` decodes through `TextDecoder`, whose label table has neither, so the label is unrecognised, the fallback is UTF-8, and the escape machinery comes back as literal text. MEASURED 2026-09-04 on the two fixtures built in `tools/conformance/suites/docread.mjs`: `hz.eml`'s `~{:O::~}` reads `合汉` on the reference and `~{:O::~}` here; `iso2022kr.eml`'s `ESC $ ) C SO = " SI` reads `숱` there and `\x1b$)C\x0e="\x0f` here. Both sides READ the file to one row; neither refuses. THIS IS NOT NEW BEHAVIOUR and it is not a regression: `decodeCharset`'s own docstring already said these labels fall to UTF-8. What was missing was the PRICE — review round 4 found it with no divergence row, no `ruling:` case and no companion, which is a CLAUDE.md violation whatever the behaviour is. The cause is the same as `utf-7 on Node`: each is a stateful escape transform, not a byte table, so `runtime-ts/src/charsets.ts` cannot carry it. H1 (`666f14f`) is what made this visible — the generator's statelessness probe used to be six hand-picked lead bytes containing neither ESC (`0x1b`) nor `~` (`0x7e`), so seven stateful modules were written out with a 256-character byte table they cannot have; the full 65,536-pair sweep refuses all seven (79 -> 72 tables) and the labels now reach the decoder chosen by measurement over 8,829 inputs against CPython (ICU 5,664 correct, byte table 5,021, utf-8 4,339). `hz`, `iso2022_kr` and `utf_7` score 0 % through WHATWG, which is why six labels route to ICU and not nine. Not ported, because lifting it means three modified-escape decoders written by hand under the no-dependency rule, for shapes nothing in the measured corpora (`docs/eval-data/`) uses. Ruled in `tools/conformance/suites/docread.mjs`: `extract: hz.eml: statefulCjk is RULED` and `extract: iso2022kr.eml: statefulCjk is RULED` over the whole answer, each with `…: the refusal bit each side is required to carry` pinning `{python: false, node: false}`, `…: both read (the refusal bit, side to side)` as the unruled companion — which is the case that catches one side starting to REFUSE, something a ruling can never do — and `…: the same shape around the ruled row` comparing kind, part names, row counts and omissions unruled. Teeth demonstrated 2026-09-04: before the rulings existed the same two fixtures gave `FAIL: 1050 cases, 4 failures`; with them, `PASS: 1048 cases, 15 ruled-different, 0 failures`. |
| bzip2 and lzma zip members on Node | **the reference reads a zip member stored with compression method 12 (bzip2) or 14 (lzma); the port refuses it by member, method number and name.** CPython's `zipfile` links the `bz2` and `lzma` modules and decompresses both methods transparently, so a `.docx` whose `word/document.xml` was written with `ZIP_BZIP2` or `ZIP_LZMA` reads to its row (`hello` in the fixture). `docread.ts` decompresses through `node:zlib`, which has deflate and nothing else the zip format names, and `runtime-ts` may carry no runtime dependency beyond the one in `package.json` — so the port refuses with `<name> is a zip but its <member> uses compression method 12 (bzip2), which the Node server cannot decompress (the Python server reads it); see docs/porting.md` (14 (lzma) for the other). **AMENDED 2026-09-04 (review round 4, M1): this row rules the REQUIRED member only.** An OPTIONAL member stored with the same method is now PARITY, not a ruling: `isUnreadableOptional` omitted `DocumentReadError`, so a `.xlsx` whose `xl/styles.xml` was written with `ZIP_BZIP2` made the port refuse the whole document the reference reads. Fixed in `aa49760` with the fixture `bzip2-optional-styles.xlsx` (built in `runtime-ts/test/docread-fixtures.mjs`), compared UNRULED in the `docread` suite: a member this port cannot decompress costs that MEMBER and never the document, and both sides answer the same bytes. **Residual, unfixed — MEASURED AND FIXTURED 2026-09-06 (job44 U17), and it now has a row of its own:** a bzip2 `xl/styles.xml` that carries DATE FORMATS still diverges — the reference decompresses it and emits the `number-format` omission, and this port cannot produce it. Same cause as this row, and still unfixed for the same reason; what changed is that it is no longer a prediction. The fixture the residual said did not exist is `bzip2-date-styles.xlsx`, with the control `deflate-date-styles.xlsx` beside it, and the ruling is the row below, "a bzip2 `xl/styles.xml` that carries date formats". Was roadmap row 8 (t). Method 9 (deflate64), the encrypted flag and a damaged member are NOT rows here — since round 3 (H1/H2) each has its own sentence and BOTH sides print it, pinned unruled in `docread` (the checked-in `compression-method-9.docx`, `encrypted-member.docx`, `encrypted-mimetype.odt`, `bad-crc.docx`, `corrupt-deflate.docx`) and in `wire`'s `read-round3` session as literals: `<name> is a zip but its <member> uses compression method 9, which this reader cannot decompress` (method 9 used to print the encrypted sentence, because `zipfile` raises `NotImplementedError` for both; the reference now reads the method off the member's header first); `<name> is a zip but its <member> is encrypted, so this reader cannot read it without a password`; and `<name> is a zip but its <member> is damaged (<cause>), so this reader cannot read it`, where the parenthesised cause is CPython's own words — `Bad CRC-32 for file 'word/document.xml'` from `zipfile`, `Error -3 while decompressing data: invalid block type` from `zlib` — which the port reproduces byte for byte **for every cause zlib names** (`docread.ts` `isDamagedMember`, the `BadZipFile` and `zlib.error` sentences). **AMENDED 2026-09-04 (review round 4, L3): the unqualified "byte for byte" was wider than what is measured.** The port rebuilds the sentence by hand as `` `Error ${e.errno} while decompressing data: ${e.message}` ``, which is exact for the shape a fixture exercises (`corrupt-deflate.docx`, zlib return code -3 with `msg = "invalid block type"`). CPython's `zlib_error` formats `"Error %d %s"` with NO cause clause when `zst.msg` is `NULL`, and substitutes its own fixed strings (`incomplete or truncated stream`, `inconsistent stream state`, `invalid input data`) before that; `node:zlib`'s message in those cases is its own and the two sentences would differ. No input that makes zlib return an error with a null `msg` has been constructed, so this is a GAP, honestly unmeasured, and not a measured divergence — which is exactly why the claim is narrowed to the class a fixture holds rather than left standing over a class nobody has reached. Registered as roadmap row 8 (s). Ruled in `tools/conformance/suites/docread.mjs` (`extract: bzip2.docx: bzip2 is RULED`, `extract: lzma.docx: lzma is RULED`, each with `…: the refusal bit each side is required to carry` as the literal `{python: false, node: true}`, `…: the reference reads the row as measured` pinning `hello` — generated from the reference's own run, not typed — and `…: the port refuses in the sentence the ruling quotes` pinning the port's sentence with its method number) and in `tools/conformance/suites/wire.mjs`'s `read-round2` session (ids 7 and 8 ruled, the same three companions on the wire, and `…: the reference's manifest names one part of one row`). Neither side refuses on BOTH, so there is no side-to-side refusal-bit companion; the literal pair is what says which side must read. Teeth demonstrated 2026-08-29: forcing the ruled case to match reddened it as `STALE RULING` (`node tools/conformance/run.mjs --suite docread`), then the probe was removed. Lifting it means a bzip2 and an lzma decoder written for this program under the no-dependency rule; nothing in the measured corpora (`docs/eval-data/`) uses either method, so it waits. |
| a bzip2 `xl/styles.xml` that carries date formats | **neither runtime refuses and both read the same row; only the reference can say what the number IS.** The row above rules the REQUIRED member and records, since round 4 (M1), that an OPTIONAL member stored with method 12 costs that member and not the document — `bzip2-optional-styles.xlsx` pins that as parity. What M1 left standing, and named as a residual with no fixture, is that the two runtimes do not lose the same AMOUNT when the member carries something. `bzip2-date-styles.xlsx` (built in `runtime-ts/test/docread-fixtures.mjs`) is that fixture: an `.xlsx` whose `xl/styles.xml` declares `yyyy-mm-dd` at the `cellXfs` index cell A1 uses, and whose A1 is the bare number `46235`. `docread.py` decompresses the member through `bz2`, resolves the style and emits `Omission(subject='number-format', count=1, where=('A',), what='yyyy-mm-dd')`; `docread.ts`'s `dateFormats` catches the method-12 refusal as an unreadable OPTIONAL member (`isUnreadableOptional`, which is what M1 made it do) and answers no formats, so the part's omission list is empty. Everything else matches: kind `xlsx`, one part `Sales`, one row `46235\tok`, `text_bytes` 8, no document-level omission, no refusal on either side. In an `.xlsx` the number format is the ONLY thing separating a serial date from a plain number, so the port hands back a workbook whose `46235` it cannot explain. Same cause and same remedy as the row above — `node:zlib` has deflate and nothing else the zip format names, and runtime-ts may carry no new runtime dependency, so lifting this means the same bzip2 decoder that row waits on. Was roadmap row 8 (t); MEASURED 2026-09-06 (job44 U17), which is what turned the register's prediction into a fixture. Ruled in `tools/conformance/suites/docread.mjs` as `extract: bzip2-date-styles.xlsx: bzip2Styles is RULED`, with four companions, three of them NON-ruled: `…: the refusal bit each side is required to carry` pinning the literal `{python: false, node: false}`, `…: both read (the refusal bit, side to side)`, `…: the same shape around the ruled row (kind, parts, row counts, omissions)`, and — because the divergence here is a missing OMISSION rather than a differing row, which the shape case does not reach — `…: the reference discloses what the unreachable member carries, as measured` and `…: the port discloses nothing, because the member holding it is method 12`, each pinning one side's omission list as a literal. **The ruling comes with a CONTROL, which no other row here has**, and it is the reason this row can be believed: `deflate-date-styles.xlsx` is the same workbook with the same `xl/styles.xml` CONTENT — same CRC `0x7e197e5f`, same 225 uncompressed bytes, one header field apart — behind method 8, and `the bzip2-styles ruling has a control: the same styles behind method 8 make BOTH sides disclose` pins that both runtimes emit the omission on it. Without that case a reader that stopped resolving date styles ENTIRELY would leave both sides silent, the ruled comparison would start matching and be reported as a stale ruling, and the two disclosure companions would both read `[]` — a green suite over an input that had lost its teeth, which is the exact shape three parity bugs already survived in this repo. **Teeth demonstrated 2026-09-06**, by making that very regression: the styled cell's `s="1"` was changed to `s="0"` in `runtime-ts/test/docread-fixtures.mjs` — the M1 blind spot, deliberately re-created — and `node tools/conformance/run.mjs --suite docread` reddened three cases by name, `extract: bzip2-date-styles.xlsx: bzip2Styles is RULED — STALE RULING: the case no longer differs`, `…: the reference discloses what the unreachable member carries, as measured`, and the control, then the probe was reverted and the suite is green (1,078 cases, 16 ruled-different, 0 failures at the time of the run; the case count moves with the repo). The unit layer has the same teeth: treating `bzip2-date-styles.xlsx` as parity in `runtime-ts/test/docread.test.mjs`'s `DIVERGENT` map fails 2 of its 50 tests on the missing omission. |
| RFC 2231 charset continuations on Node | **the two runtimes reassemble a `Content-Type` parameter differently, and only one of them reassembles it at all.** RFC 2231 lets a parameter arrive in numbered pieces (`charset*0=utf-8; charset*1=…`) or as an encoded value (`charset*=utf-8''…`). `docread.py` reads a MIME part's charset through `email.policy.default`'s header parser, which joins the pieces with semantics that are its own: `charset*1=x; charset*0=y` joins to `yx`, and a plain duplicate `charset=utf-8` on the same header LOSES to the continuation. So `rfc2231-charset.eml` (checked in under `runtime-py/tests/data/docread/`) decodes as UTF-8 and reads `café au lait`. `docread.ts` reads the plain `charset=` parameter only, finds no usable label, and decodes the same bytes through UTF-8 with replacement: `caf� au lait`. Both sides READ the file to one row of one part; the row differs by two bytes' worth of replacement characters (the reference's row is 12 UTF-8 bytes, the port's 14), and the `text_bytes` figure moves with it. Not ported, because porting it means carrying `email`'s parameter reassembly — its piece ordering, its duplicate rule, its language tag and its percent-decoding — for one row on one shape, far over the port budget. Ruled in `tools/conformance/suites/docread.mjs`: `extract: rfc2231-charset.eml: rfc2231 is RULED` over the whole answer, with `…: the refusal bit each side is required to carry` pinning `{python: false, node: false}`, `…: both read (the refusal bit, side to side)` as the unruled companion, and `…: the same shape around the ruled row` comparing kind, part names, row counts and omissions unruled. On the wire, `read-round2: id 10` in `tools/conformance/suites/wire.mjs` is the ruling, with the same two companions and `…: the same manifest around the ruled row`, which blanks the row and its byte count and compares the rest of the manifest byte for byte. Teeth demonstrated 2026-08-29: forcing the ruled case to match reddened it as `STALE RULING`, then the probe was removed. |
| `<!ATTLIST>` defaults on Node | **the reference's `expat` applies an internal DTD's `<!ATTLIST>` default attribute values; the port's internal-subset walk skips the declaration.** `attlist.xlsx` (built in `tools/conformance/suites/docread.mjs`) is a sheet whose XML opens `<!DOCTYPE worksheet [<!ATTLIST c t CDATA "s">]>` and holds a `<c r="A1"><v>0</v></c>` written WITHOUT a `t` attribute. `docread.py` reads it through `xml.etree`'s expat, which supplies the default `t="s"`, so the cell is a shared-string index and reads `SHARED`; `docread.ts`'s `parseDoctype` reads `<!ENTITY>` declarations (pinned unruled by `internal-dtd-entity.docx`) and skips `<!ATTLIST>` over its quoted strings, so the cell is a number and reads `0`. Both sides READ the file to one row of one part; the row differs by that one cell (`SHARED\tplain` against `0\tplain`, measured 2026-08-29 on both). Not ported, because applying defaults means carrying expat's attribute-declaration model (per-element, per-attribute, `#IMPLIED`/`#REQUIRED`/`#FIXED`, the CDATA/NMTOKEN normalisation) into a walk that exists to read four element names, and no OOXML writer emits an internal DTD at all — this was a "gap the differential cannot see" until H3 built the fixture that shows it. Ruled in `tools/conformance/suites/docread.mjs`: `extract: attlist.xlsx: attlist is RULED` over the whole answer, with `…: the refusal bit each side is required to carry` pinning `{python: false, node: false}`, `…: both read (the refusal bit, side to side)` as the unruled companion, and `…: the same shape around the ruled row` comparing kind, part names, row counts and omissions unruled. Teeth demonstrated 2026-08-29: removing the `<!DOCTYPE>` from the fixture made the two rows match and reddened the case as `STALE RULING` (`node tools/conformance/run.mjs --suite docread`: 983 cases, 1 failure), then the fixture was restored. |
| `str.isalpha()` against `\p{L}` in `skillaudit` | **the two runtimes read two different Unicode databases, and they are compiled against two different revisions of the standard.** `skillaudit.py` asks CPython's own tables through `str.isalpha()` and `str.isalnum()`; `skillaudit.ts` asks V8/ICU through `/\p{L}/u` and `/[\p{L}\p{N}]/u`. MEASURED 2026-09-05 by brute force over all 1,112,064 code points (`0x0000`-`0x10FFFF` less the surrogate range) on this machine: CPython 3.12.13 carries `unicodedata.unidata_version` 15.0.0 and Node 25.2.1 carries `process.versions.unicode` 16.0 (ICU 77.1); **4,924 code points disagree for alpha and 5,004 for alnum, and every disagreement is ONE-DIRECTIONAL** — the port answers letter where the reference does not, never the reverse, because 16.0 only added characters to the letter categories. The first is U+1C89 (CYRILLIC CAPITAL LETTER TJE), which is `Cn`, unassigned, in 15.0.0. It reaches TWO sites and it moves them in OPPOSITE directions. In `_is_letter` / `isLetter` it is the apostrophe guard, so `\u1C89'race condition'\u1C89` is `['race condition']` on the reference (the flank is not a letter, so the quote delimits) and `[]` on the port — **the reference emits a `shared-trigger-phrase` the port does not**. In `_has_content` / `hasContent` it is the punctuation filter, so `"\u1C89"` is `[]` on the reference (no alnum in the phrase) and `['\u1C89']` here — the PORT keeps a phrase the reference drops. NEITHER SIDE IS WRONG: each is telling the truth about the Unicode revision it was built against, and the same reference on a CPython built against 16.0 would answer what the port answers today. Not lifted, because the fix is one of two things this program will not do: vendor a 136,104-entry category table into `runtime-ts` and re-vendor it on every CPython upgrade (the shape `runtime-ts/src/charsets.ts` takes for single-byte codecs, which is 79 tables of 256 entries, three orders of magnitude smaller and PINNED against the live registry by a suite — nothing pins a Unicode category table against a CPython that has not shipped yet), or make the reference stop asking CPython, which would make it disagree with the host it is auditing. No `SKILL.md` in either measured corpus contains a code point from the disagreeing set. Ruled in `tools/conformance/suites/skillaudit.mjs`: `phrases: the apostrophe guard over U+1C89: the Unicode version is RULED` and `phrases: the punctuation filter over U+1C89: the Unicode version is RULED`, each with `…: the answer each side is required to carry` as a LITERAL companion pinning `{python: ['race condition'], node: []}` and `{python: [], node: ['\u1C89']}` — the case that fails on its own line if CPython upgrades or ICU downgrades, rather than behind "they still differ". **There is no refusal-bit companion, and this is the judgement CLAUDE.md asks for: the difference is not refusal-shaped.** Neither runtime refuses this input; both return a list of phrases, and they differ in the CONTENT of that list. A refusal bit compared side to side would be `{python: false, node: false}` on every input this module has ever been given, ruled or not, which is a case that can never go red and is exactly the vacuous gate the rule exists to prevent. What the rule is protecting against — a ruling staying green while the port quietly stops answering at all — is instead covered by FOUR non-ruled ascii twins, two per ruled site: the same constructions with `A` in place of U+1C89, in both polarities. One of each pair is where the shared rule SUPPRESSES the phrase (both sides answer `[]`, which says the rule is still there) and one is where it KEEPS it (both answer a non-empty list, which is the case a reader that finds nothing fails). Each also carries a both-sides literal, so a twin cannot pass because both runtimes broke the same way. The second of each pair is not decoration: MEASURED 2026-09-05 by making `phrases` return `[]` for every input, the punctuation-filter ruling self-detects — it goes `STALE RULING`, because both sides then answer `[]` — and the apostrophe-guard ruling does NOT, because the reference's answer there is the non-empty one; the guard's `guard does not fire` twin is the only case in the suite that catches it, and the first draft of this row had only the vacuous half of the pair. Teeth demonstrated the same day: replacing U+1C89 with `A` in the two ruled texts reddened both as `STALE RULING` (4 differed), and killing `phrases` reddened 36 cases including two twins while one ruling stayed green; both probes were removed. |
| `--install`'s recorded command | **each runtime registers ITSELF, and that is the point.** `--install <host>` writes an MCP entry into a host's configuration; `runtime-ts` records `npx -y bantamkit-mcp` and `runtime-py` records its own console script by absolute path (falling back to `<python> -m bantamkit.mcpserver` when invoked that way). Making them agree would mean one distribution sending a host to look for the other's runtime — a pure-npx install has no Python, and a `pip install` has no npm. Everything else about the report and the written file is IDENTICAL: the file, the key (`servers` for VS Code, `mcpServers` for the other three), the entry shape, the backup name, the refusal sentences, and the exit codes. Ruled in `tools/conformance/suites/cli.mjs` as `install-<host>/stdout-command-line`, over three hosts, and **each ruling has a companion**, `…/stdout-everything-else`, comparing every byte of the report the ruling does not cover — so a runtime that changed the file it writes, the key it writes under, or the backup it takes fails while the ruling still "differs". The idempotent arm (`install-cursor-again`) is deliberately NOT ruled: a second run prints no `command:` line at all, so its whole report is compared as bytes. Attaching a ruling there was tried and the harness reported `STALE RULING: the case no longer differs`, which was right. |
| `--install`'s JSON parse error | **both refuse; the reason after the colon is each parser's own.** A host config that does not parse is never overwritten — it is somebody's file, mid-edit, and the only copy. Both runtimes print `<path> is not valid JSON, so this refuses to touch it: <reason>` and exit 1; the reference appends CPython's `Expecting value (line 1, column 1)` and the port V8's `Unexpected token …`. Neither can produce the other's: `JSON.parse` does not expose a line and column at all, and inventing a third wording would throw away the position the reference gives a reader. Ruled in `tools/conformance/suites/cli.mjs` as `install-broken-json/stderr`, **with the refusal-bit companion CLAUDE.md requires** — `…/both refuse (the refusal bit, side to side)` — because a ruling proves only that the sentences differ and would stay green if one runtime started writing the file. `…/wrote-no-config` is not needed here: the refusal bit and the byte-identical stdout (empty on both) already say nothing was produced. |
| the ten CJK codecs on Node | **the reference decodes them through CPython's own multi-byte tables and the port through ICU's, and four of the ten labels are not even the same codec on the WHATWG side.** `charsets.ts` carries CPython's SINGLE-byte tables and is pinned against the live registry (the row's whole point, above); `euc_jp`, `euc_kr`, `cp932`, `gb18030`, `gbk`, `shift_jis`, `big5`, `big5hkscs`, `cp949` and `gb2312` are not in that file at all — `docread.ts`'s `MULTI_BYTE_LABELS` sends each to a `TextDecoder`, with CPython's replacement policy layered on top by `decodeMultiByte`. The WHATWG label's table is not the codec's in every cell: `gb2312` is decoded by ICU's **gbk**, `big5` carries **HKSCS**, `euc-kr` is **cp949**, `shift_jis` is **cp932**. MEASURED 2026-09-06 over 300 seeded byte strings of 2–8 random bytes (the recipe is `tools/conformance/ref/cjk_ref.py`, re-seeded per codec so all ten answer about the SAME inputs), CPython 3.12.13 against Node v25.2.1 / ICU 77.1 — how many of the 300 the two sides answer alike: `euc_kr` 298, `gb18030` 293, `euc_jp` 295, `cp932` 285, `gbk` 277, `shift_jis` 247, `big5hkscs` 211, `big5` 210, `cp949` 205, `gb2312` 141. The port collapses three of the pairs outright: `big5`/`big5hkscs` produce **byte-identical** answers here (one ICU decoder) where the reference's two differ, and so do `euc_kr`/`cp949` and `gbk`/`gb2312` — pinned as data, the two `port` digests equal and the two `reference` digests not. **THE COUNTS ARE NOT THE ONES `docs/roadmap-toolbox.md` ROW 8 (o) QUOTES, AND THAT ROW'S NUMBERS DO NOT REPRODUCE.** (o) says "300 random byte strings per codec … (seed 7)" and gives euc_jp 297 / euc_kr 296 / cp932 295 / gb18030 292 / gbk 278 / shift_jis 268 / big5 208 / big5hkscs 205 / cp949 192 / gb2312 141, and the script that produced them was never checked in. Ninety-odd reconstructions of that sentence were run on 2026-09-06 — `randbytes` and `randrange` byte streams, fixed lengths 1 through 32, `randrange`/`randint` length ranges, a corpus shared across codecs and one re-seeded per codec — and not one reproduces the ten together; the row's own profile rules a single corpus out, because it pairs `euc_jp` 297 (a rate only very short inputs reach) with `gb2312` 141 (a rate only longer ones fall to). The recipe now lives in code so the next reader is not in that position. Not lifted, because lifting it means writing CPython's CJK tables into TypeScript the way `charsets.ts` does for single-byte codecs — 79 tables of 256 entries there against tens of thousands of multi-byte mappings here — for a difference that lands on MALFORMED input: every one of the 300 is random bytes, and where the bytes are valid text in the codec both sides agree. Ruled in `tools/conformance/suites/charsets.mjs` as `ruling: cjk <codec>: ICU's table against CPython's over 300 seeded byte strings`, ten of them, **and every one carries FOUR non-ruled companions that are LITERALS in the suite** — `…: how many of the 300 the two sides answer alike` (the count, so `gb2312` moving from 141 to 150 is a failure and not a re-measurement), `…: the reference's own 300 answers, anchored`, `…: the port's own 300 answers, anchored` (two digests, which are what catch a SYMMETRIC regression a ruling structurally cannot see), and `…: the first input the two sides answer differently, both answers spelled out`. A `cjk: the seeded corpus is the same 300 inputs …` case pins the corpus digest, so a CPython whose RNG stream moved is a named failure rather than a silent re-measurement of a different corpus. **Teeth demonstrated 2026-09-06, all four in the run and then removed:** (1) forcing `gb2312`'s port answers to equal the reference's reddened it as `STALE RULING` plus 3 companions (148 cases, 4 failures); (2) editing the pinned `gb2312` count to 150 reddened exactly one case; (3) **the symmetric-regression probe, which is why the digests exist** — appending the same string to BOTH sides' answers for all ten codecs left all 12 rulings GREEN and all ten `matched` counts GREEN, and reddened 30 cases, every one of them an anchor (148 cases, 30 failures). A ruling-only pin would have passed that run. |
| ISO-2022-JP's eight characters on Node | **the same cause under a stateful codec, and unlike the row above this one bites on VALID text.** `docread.ts`'s `ESCAPE_LABELS` sends the six `iso2022_jp*` modules to ICU's `iso-2022-jp` decoder whole (a plain `TextDecoder`, never `decodeMultiByte`, because that walk assumes a byte under 0x80 is its own ASCII character, which is exactly what an escape sequence is not). ICU maps six JIS X 0208 code points the way Windows-31J does where CPython maps them the way JIS X 0208 does, and rejects two controls CPython passes through. MEASURED 2026-09-06 as a **census, not a sample**: every one of the 7,008 characters CPython's `iso2022_jp` round-trips, encoded by the reference and decoded one at a time by both sides. Eight differ, and they are `U+00A2 -> U+FFE0` (CENT SIGN -> FULLWIDTH CENT SIGN), `U+00A3 -> U+FFE1` (POUND SIGN), `U+00AC -> U+FFE2` (NOT SIGN), `U+2016 -> U+2225` (DOUBLE VERTICAL LINE -> PARALLEL TO), `U+2212 -> U+FF0D` (MINUS SIGN -> FULLWIDTH HYPHEN-MINUS), `U+301C -> U+FF5E` (WAVE DASH -> FULLWIDTH TILDE), and `U+000E`/`U+000F` (SHIFT OUT / SHIFT IN) which CPython passes through and ICU answers `U+FFFD` for — a refusal rather than a remapping. **THIS REFUTES THE "EVERY ONE" HALF OF `docs/roadmap-toolbox.md` ROW 8 (o)'s AMENDMENT**, which says the residual is "12 of 900 valid-text inputs, and every one of the 12 is the WAVE DASH". The wave dash is ONE of eight, and it is simply the most-cited member of a well-known family; the register generalised from a sample that happened to contain only it. The sample shape was re-run too (900 seeded strings of 1–8 of those characters, same seed): **7 of 900 differ here, not 12, over five of the eight characters** — the same point from the other side, that a sample cannot settle a claim about WHICH characters. Not lifted, for the reason the row above gives. Ruled in `tools/conformance/suites/charsets.mjs` as `ruling: cjk iso2022_jp: ICU's JIS X 0208 mapping against CPython's, over every character CPython round-trips` and `ruling: cjk iso2022_jp: the same difference in the shape roadmap row 8 (o) sampled`, **with the companion that matters pinning the CHARACTERS and not the count** — `cjk iso2022_jp: WHICH characters the port answers differently, by code point — the case a count cannot be` is the literal map above, beside `…: how many characters the reference round-trips at all` (7,008) and four anchored digests, two per side per corpus. **Teeth demonstrated 2026-09-06:** swapping the pinned `U+301C -> U+FF5E` key for a different character while leaving the NUMBER of differing characters at eight reddened that one case — which is the property the brief asked for, that a count staying 12 while the differing characters change is a gate that missed something. |
| `install_shape: ephemeral` (AS-7a) | **the port answers the word and the reference never does, because only one ecosystem writes the fact down.** npm puts an `_npx` marker into an `npx` cache project's own `package.json`, so an ephemeral environment is a RECORD the port reads; `pipx run` and `uvx` leave no equivalent, and telling one of their environments from an ordinary venv would mean pattern-matching cache directory names — a guess, and this surface does not guess. The word is declared in BOTH vocabularies (`INSTALL_SHAPES`) so a consumer of either runtime handles one set of five rather than two it has to reconcile. **What this row does NOT license:** the shape is the ENVIRONMENT and `install_source` is the ORIGIN, two axes, and the measured incident is both at once — an `npx` cache filled from a tarball that is gone. So the origin survives the environment word: `install_source`, `install_source_exists` and the whole `install-source-missing` sentence are compared UNRULED over the same fixture. Driven both sides 2026-09-11 over one matched install: reference `local-file`, port `ephemeral`, identical origin path, identical condition. `install: an npx cache filled from a tarball is `ephemeral` on the port and `local-file` on the reference` in `tools/conformance/suites/install.mjs`, with `install: the npx cache keeps the origin the environment word did not replace` beside it. |
| an `http(s)` install origin (AS-7a) | **the reference REFUSES it and the port calls it `registry` — a difference in the refusal, not in a sentence.** PEP 610 records an http archive as a direct URL that is not a path, and the reference will not round it to one of five words. On the port the npm registry IS an https URL, and telling a published tarball URL from the configured index would mean knowing which index was configured. Either way the origin is REMOTE, so it can never be the dangling-local-path defect AS-7 exists for, and the route out is a reinstall from a name or from that same URL. Ruled by `install: an http(s) origin is refused by the reference and is `registry` on the port`; **and because a ruling only proves the two still DIFFER, never that either still refuses,** the refusal BIT is pinned per side, unruled, by `install: the three refusal bits against a literal`. The underivable origin the two sides still SHARE is `git+…`, compared unruled over its own fixture. |
| a running file no `package.json` owns (AS-7a) | **the reference answers `checkout` and the port REFUSES — the second refusal difference, and the same companion.** The reference identifies the package from the distributions on `sys.path` and needs no manifest beside the running file, so the absence of any installer record is positive evidence of a checkout. The port has no equivalent index: without a `package.json` above the running file it cannot name the package at all, and `checkout` answered there would be a guess about which package this even is. Ruled by `install: a running file no package.json owns is `checkout` on the reference and refused by the port`, with the refusal bit pinned per side by the same literal case as the row above. |
| the `registry` reason's middle clause (AS-7a) | **one clause, and it names the MECHANISM rather than rewording the finding.** Both sides explain why an ABSENCE is positive evidence of an index install, and the two absences are different files: the reference cites PEP 610 and `direct_url.json`, the port cites npm and `node_modules/.package-lock.json`. Copying the reference sentence verbatim would have a Node server citing PEP 610, which is how `git_commit` diverged on a noun. **What this row does NOT license:** the first clause and the closing sentence are byte-identical and are compared UNRULED by `install: the registry reason opens and closes identically on both sides`. Ruled by `install: the registry reason names PEP 610 on the reference and npm on the port`. |

## Gaps the differential cannot see, named rather than hidden

A row here is **not** a permitted difference. It is a property the two runtimes are
supposed to share where `node tools/conformance/run.mjs --all` is structurally unable to
compare them, so the only thing holding the property is a unit test on each side. Naming
the gap is the whole point: a green `--all` is not evidence about any of these.

**A zip member over 536,870,888 bytes (`ERR_STRING_TOO_LONG`).** V8 caps a string at
2**29 - 24 characters; `docread.ts` decodes a member into one string, so a `word/document.xml`
past that size raises `ERR_STRING_TOO_LONG` on the port where the reference — which holds
`bytes` and decodes in `expat`'s stream — reads it. The port raises HONESTLY (an `Error`, not
a silent cut), but no conformance case pins it: building a 512 MiB fixture per run is not a
cost the suite pays, so the divergence is REPORTED here, not matched, and `docs/roadmap-toolbox.md`
row 8 carries it as a follow-up (job43 G3, 2026-08-29). A green `--all` says nothing about it. It stays a gap and not a ruling because a ruling needs a fixture that shows the two sides differing, and the smallest such fixture is 536 MB; H3 (2026-08-29) re-checked and left it here. The same rule kept the 300,000-cell row (`Math.max` over the cell keys, fixed in H2) out of the suite: the smallest deflated xlsx that shows it measures 1,501,739 bytes, over the 1 MB fixture ceiling, so it is held by `runtime-ts/test/docread.test.mjs` alone.

**Which two type names a mixed-type name set puts in `sorted()`'s TypeError.** `dream`
pairs facts on `Fact.name`, and a hand-edited frontmatter can put an `int` in that field
(`store.pyText`, `store.pyHashKey`). The reference sorts `set(by_project) & set(by_profile)`,
whose iteration order is HASH-derived; `dream.ts` sorts the same names in fact-file order,
because a JS `Set` has no hash order to reproduce. Both runtimes then run the same CPython
`listsort` and both RAISE `TypeError` on the first incomparable pair — but WHICH pair the
binary search probes first can differ, and the sentence names the two types it probed. Where
the order exists at all (every name a `str`, which is every store `save` has ever written)
the two answers are identical, and the whole `dream` algorithm was compared over 24,908
generated cases with zero disagreements. No conformance case pins the mixed-type sentence and
no unit test on either side holds it: constructing the input needs a hand-written frontmatter
with a non-`str` `name` under a name that ALSO collides across two layers. Named here rather
than ruled, because a ruling needs a fixture that shows the two sides differing and nobody has
built one; J45-3, 2026-09-06.

**`detail.type` on a `raised` record.** The event log names an exception by the class
CPython's `OSError.__new__` picks off the errno — `NotADirectoryError` for `ENOTDIR`, not
the JavaScript constructor name `PyOSError`, and not the bare `OSError` — via
`osErrorClassName` in `runtime-ts/src/memory/pyfs.ts`, the single reader of
`OSERROR_SUBCLASS`. **No `wire` session drives a throwing handler**, and making one drive a
real `OSError` needs a `chmod 000` that is meaningless on Windows; a POSIX-only case would
make the matrix compare different case sets on different platforms, which is worse than an
absence you can read. So this is held by
`runtime-ts/test/eventlog.test.mjs`'s `an OSError is recorded under the class CPython picks
off the errno` — a real `readdir` on a plain file, so the mapping has to stay reachable
from `asPyOSError` — plus `an errno outside the table is OSError, which is CPython default
too` for the default branch, and by `test_eventlog.py`'s own `raised` nodes on the Python
side. The differential does not compare this field on any case that exists today.

**`BANTAMKIT_EVENT_LOG`'s whitespace, registered and NOT fixed.** `str.strip()` and
`String.prototype.trim()` do not strip the same set. Python strips the C0 separators
`\x1c`–`\x1f` and JavaScript does not; JavaScript strips U+FEFF and Python does not. So
`"\x1con\x1c"` enables the default log on Python and is taken as a literal *path* on Node,
and `"\uFEFFon"` (a real BOM, spelled as an escape here) does the same thing in reverse. Both sides then behave correctly for the
value each one saw — the divergence is entirely in the stripping. Closing it means a
Python-whitespace `strip` inside `resolvePath`, i.e. a second whitespace table in the port
and a wider surface than the divergence it removes, for an environment variable nobody sets
with a file separator in it. Registered here instead.

**Any `skillaudit` rule the two runtimes get wrong THE SAME WAY.** Both halves are hand-written
from the same contract, so a rule misread once tends to be misread twice, and the differential
compares them to each other rather than to the contract. MEASURED 2026-09-05: regressing the
version resolution in BOTH runtimes at once — choosing the winning version directory from the
skills that survived `load` and `applyEnabled`, rather than from the `<marketplace>/<plugin>/
<version>/skills` directories on disk — leaves `node tools/conformance/run.mjs --suite
skillaudit` at **94 cases, 0 failures** while `test_skillaudit.py` reports 20 failures and
`runtime-ts/test/skillaudit.test.mjs` reports 20. That is not a hypothetical: it is how the
defect shipped in the first place, in both runtimes, past 71 green conformance cases. What
holds these rules is the fixture README's HAND arithmetic — `tools/conformance/fixtures/
skill-audit/README.md` states, per file, which clause it exists to trigger, and states the
number each WRONG reading answers beside the right one — asserted against the tool on both
sides. A green `--all` says only that the two agree.

**The damaged-member cause clause belongs to whichever `libz` the reference is linked against.**
`docread.py::_read` interpolates `str(zlib.error)`, whose cause phrase is `strm->msg` — a pointer
into the zlib build's own string table — and `docread.ts::isDamagedMember` rebuilds that sentence
by hand from `errno` and `message`. The scaffold matches; the phrase is not the port's to
reproduce. CPython links the platform `libz` (macOS 26.5.2 here: `ZLIB_RUNTIME_VERSION 1.2.12`, for
both `/usr/bin/python3` and the mise 3.12.13) while Node bundles its own
(`process.versions.zlib` = `1.3.1-470d3a2`), and **Apple's `libz` merges two upstream messages
into one string that exists in no `madler/zlib` release** — `invalid literal/length/distance
code`, in place of `invalid literal/length code` and `invalid distance code`. MEASURED
2026-09-06 (job44 U14, `docs/eval-data/2026-09-06-job44-zlib-damaged-member.md`, which carries the corpus, the C
probes and the commands): over 8,037 corrupt raw-deflate members, 6,306 raise on both sides and
**803 of those (12.7 %) print a different sentence on macOS**; substitute a stock madler 1.3.1
built from source for CPython's zlib and the count is **0 of 6,306**; replay the same 803 with
`avail_out = 257`, below `inflate_fast`'s 258-byte threshold, and Apple's `libz` answers the two
upstream strings — so the divergence lives in Apple's `inflate_fast` replacement alone, and the
ten other messages the corpus reaches are identical on both sides. It is a GAP and not a ruling
because **the expected value is a function of the host**: a `ruling:` case pinning two sentences
would be red on Linux and Windows, where CPython links a stock zlib and the two sides agree, and
a parity case pinning agreement would be red on macOS. No fixture is checked in for the same
reason; the four-line builder is in the note. The suite is green today because the one fixture
it has, `corrupt-deflate.docx` (`b"\x07\x00\x00\x00\x00"`, a reserved block type), lands on
`invalid block type` — one of the ten messages both zlibs spell the same way. There is no fix:
the port cannot know Apple's string table, and dropping the cause clause would discard real
information on every platform to paper over one. This **supersedes the narrowed claim in the
bzip2/lzma row and roadmap row 8 (s)**, which predicted a different mechanism — CPython's
`zlib_error` taking its null-`zst.msg` branch. That branch is now shown UNREACHABLE through
`zipfile`: `decompressobj(-15)` sets `wrap = 0` so `Z_NEED_DICT` cannot occur; all 25
`state->mode = BAD` assignments in `inflate.c`/`inffast.c` set `strm->msg`, so `invalid input
data` is dead code; and `Decompress.decompress`/`.flush` both list `Z_BUF_ERROR` beside `Z_OK`
and never raise on it, so `incomplete or truncated stream` is unreachable too — 0 null-`msg`
sentences in 8,037 inputs under either `libz`.

## Defects registered against `runtime-py`, not fixed here

A row here is a defect the reference has and the port does not get to fix — either because
closing it is out of the porting unit's layer, or because the port's job is to REPRODUCE the
reference and the disagreement is with CPython rather than with Node. Found while porting:

1. Windows index-budget arithmetic — 13537 bytes on disk against 13472 checked. (The port
   now reproduces it rather than avoiding it; the reference's arithmetic is still the one
   that is wrong, and it is still not fixed here.)
2. `validate_json` lets `SchemaError` / `TypeError` / `_WrappedReferencingError` escape.
3. `shiftwork._read_valid` does not catch `UnicodeDecodeError`.
4. `_pinned_store`'s docstring states a false reason.
5. A `pattern` regex divergence.
6. `memory/store.py`'s `_rebuild_index` and `_write_fact` call `write_text` with
   `newline=None`, so on Windows the reference writes CRLF into `index.md` and into every
   fact file while the port writes LF. One layer BELOW the operator CLI's streams, which had
   the same defect and were fixed (`fbcf7c8`, see the note under the list). Measured by
   `memorycli`'s `…/tree` cases, which compare each file's bytes rather than a digest, and by
   the `store` suite on a real Windows cell; **not** normalised anywhere in
   `tools/conformance/`, deliberately — `ref/cli_ref.py` sets that rule for the whole
   directory, and a suite that decoded with universal newlines would erase the evidence.
7. `mcpserver.py`'s `index-budget-low` fires at `INDEX_PRESSURE_PERCENT` (90) percent of the
   budget, while the `compact` it names archives only while the index is above
   `budget - reserve`, and `reserve` defaults to the largest surviving index line (capped at
   half the budget). The two thresholds are not the same number, so there is a band in which
   the remedy is a **no-op**: it exits 0 having archived nothing. Measured on a real store —
   largest index line 186 bytes against the default 24000-byte budget — `compact` begins
   archiving only above `(24000 - 186) / 24000` = 99.2%, so the whole 90.0%–99.2% band prints
   a command that does nothing. The port carries the SAME two constants
   (`INDEX_PRESSURE_PERCENT` in `mcp/status.ts`, the same default `reserve` in
   `memory/store.ts`), which is why this is a register entry and **not** a divergence row:
   the two runtimes agree to the byte, and a row above would be false. Not fixed here for the
   same reason as 1 — moving either constant is a product decision in both runtimes at once,
   which is not a porting unit's to make. The sentence deliberately says "archive or shorten
   facts **with** `…`" rather than promising the command is sufficient.

   **CLOSED 2026-09-10 (job46, units J46-4, J46-5 and J46-6).** The entry above stays as
   written — the "not fixed here" sentence is a record of what was true when a porting unit
   wrote it, and it was right that the fix was a product decision in both runtimes at once.
   That decision was taken in job46, and it is one substitution: the default `reserve` keeps
   its promise verbatim ("a fact as big as the biggest one you keep will fit") and only the
   line it is measured from moves, from the one the REFUSAL draws to the one the WARNING
   draws.

   ```
   target = undegraded_index_ceiling(budget) - largest index line
   undegraded_index_ceiling(b) = (INDEX_PRESSURE_PERCENT * b - 1) // 100      # integer only
   ```

   `INDEX_PRESSURE_PERCENT` moved down a layer with it — into `memory/store.py` and
   `memory/store.ts`, re-exported from `mcpserver.py` and `mcp/status.ts` — because `compact`
   cannot clear a warning whose line it cannot see, and a second literal 90 is the defect
   being closed. `runtime-py` at `87cc1f7`, `runtime-ts` at `55575c3`. The `index-budget-low`
   sentence is untouched on both sides: diffed programmatically, the two differ in exactly two
   edit operations, `delete "python -m "` and `replace "." -> "-"`, which is the pre-existing
   CLI-name divergence declared in the table above and nothing else. What did NOT move: the
   eviction order, the half-the-budget cap, and an EXPLICIT `reserve` — a caller that passes
   one gets `budget - reserve` byte for byte, which is the escape hatch `tools/hooks/`'s
   auto-compaction arm now uses.

   **WHAT THE CONFORMANCE CASE PINS**, because a feature is not ported until
   `node tools/conformance/run.mjs --all` compares the two answers. `wire.mjs`'s `index-band`
   session drives a store built to sit strictly inside the band — the report warns, the
   command it names runs, the warning goes away — and four cases PER SIDE, as literals rather
   than as one runtime's answer handed to the other: that the fixture is in the band at all
   (both edges DERIVED from what the session left on disk, never a percentage); that the
   remedy archives and the condition then clears; that a second run archives nothing; and that
   the names, their order and their classes are what the eviction order requires, with
   `feedback` exhausted last. `store.mjs` compares `undegraded_index_ceiling` against
   `undegradedIndexCeiling` over 227 budgets spanning both divisibility classes and both
   signs, with a companion case pinning that the corpus still contains each class.

   **The literals are per side because a differential could not have seen this at all.**
   Measured 2026-09-10: with BOTH halves reverted to the old arithmetic, `--suite memorycli`
   was green over 310 cases and every one of `wire.mjs`'s per-frame comparisons was green;
   only the per-side cases above went red. That is this repository's third named vacuity — a
   symmetric regression — happening to the exact change this entry closes.

   **A percentage is not quoted here on purpose.** The band's lower edge is the constant 90 %;
   its upper edge is `(budget - largest index line) / budget`, a function of store CONTENT.
   The register above measured 99.2 % at a 186-byte largest line, and the same store measures
   98.50 % today at 361 bytes. Neither number is wrong and both are dated.

**Three that were registered here and are now CLOSED**, by the job that built
`tools/conformance/suites/memorycli.mjs`: `memory/__main__.py`'s `_cmd_status`, `_cmd_compact`
and `_cmd_archived` let an unreadable `facts/` escape `main` as a CPython traceback
(`a2c6e20`); the same module printed through `print()` onto `newline=None` streams, so every
line it emitted was CRLF on Windows (`fbcf7c8`); and `MemoryStore.compact` moved an archived
fact with `os.rename`, which raises `FileExistsError` on Windows over an existing
`archive/<name>.md` and replaces silently on POSIX (`d239480`, now `os.replace`, which is
what the port always called).

`MemoryStore.archive` shipped with the same `os.rename` and was closed the same way on
2026-09-05, by review round 5. It is not a fourth entry because it never reached this list —
it was found in review before it merged — but the reachability argument is worth recording,
because it is NOT `compact`'s. `compact` needs a real file already sitting at
`archive/<name>.md`; `archive`'s second guard refuses that outright. What reaches `archive`
is the state the guard cannot see: `_reachable` is `Path.exists()`, which FOLLOWS symlinks,
so a **dangling symlink** at `archive/<name>.md` is an occupied directory ENTRY reported as
absent — measured on macOS, `os.path.lexists` True and `Path.exists` False, both guards
passed, and the move landed on top of the link. `restore`'s forward move has the identical
hole one directory over and is registered in `docs/roadmap-toolbox.md` (z) rather than fixed
here: narrowing a shipped command is a product decision, and this list is for defects the
PORT may not fix, which that is not — it is in both runtimes equally. The rollbacks on
both methods stay `rename` against the port's `pyReplace`, on `d239480`'s terms: they move
back onto a path the forward move has just emptied, so no state tells the two calls apart and
there is no red to demonstrate.

**AMENDED 2026-09-06 (job44, units U7 and U8).** The paragraph above says `restore`'s forward
move "has the identical hole one directory over and is registered in `docs/roadmap-toolbox.md`
(z) rather than fixed here". That was true when it was written and is not true now: (z) was
closed in job44. `restore`'s destination guard checks `os.path.lexists` explicitly and refuses a
dangling symlink by name — `facts/<name>.md already exists but cannot be read as a fact; refusing
to restore over it` — in both runtimes, with the same sentence and the same exit code, so it adds
no row here. **The consequence for `d239480` is the part worth recording**: with that guard
closed, no normal operation of `restore` reaches its forward move with the destination entry
occupied, so the `rename`-versus-`pyReplace` difference is **no longer reachable through
`restore`** either. It joins the two rollbacks in the "no state tells the two calls apart"
bucket instead of standing beside them as the one live case, and this list's live count for that
divergence is now `archive` alone. Two readings behind it, both measured rather than reasoned by
symmetry: `restore`'s `_facts()` pre-read — not its move — is what a dangling link actually met
first, one syscall earlier and through a different door (`docs/eval-data/2026-09-06-job44-restore-guard.md`);
and `archive` is unchanged and PINNED unchanged
(`test_archive_still_replaces_a_dangling_symlink_after_the_restore_guard_change`), because its
own destination guard has no pre-read ahead of it and `Path.replace` still silently replaces a
dangling symlink there.

**AMENDED AGAIN 2026-09-06 (job44, unit F4). The amendment above is IMPRECISE in the one word
that carries it, and so is the sentence it corrects.** It says the `rename`-versus-`pyReplace`
difference at `restore` is "no longer REACHABLE" and that "this list's live count for that
divergence is now `archive` alone". Both are wrong at `c6bfdeb`, and the way they are wrong is
the same: the difference at `restore` was not made unreachable, it was **removed**. Measured by
reading the two files at that commit rather than reasoning from the guard: `runtime-py`'s
`restore` forward move is `source.replace(destination)`, changed from `source.rename(destination)`
in `c6bfdeb` itself — `git show f484c70:runtime-py/src/bantamkit/memory/store.py` still has the
`rename`, `git show c6bfdeb:…` has the `replace`, and the reference's own docstring
("THE FORWARD MOVE IS `Path.replace` AND NOT `Path.rename`") says so. So the guard argument is
true but no longer load-bearing: even with an occupied destination there is now no side to pick,
because both sides call `replace`.

And `archive` is not a live count of one, it is a live count of **zero**. `archive`'s forward
move was moved to `source.replace(destination)` by review round 5 on 2026-09-05 — the paragraph
two above says so itself — against a port that always called `pyReplace`. With `compact` fixed at
`d239480`, `archive` at review round 5 and `restore` at `c6bfdeb`, **every forward move in
`MemoryStore` is `replace` on both runtimes**, and grepping the two files at `c6bfdeb` finds the
only remaining `rename` calls on the reference to be `destination.rename(source)` in `archive`'s
and `restore`'s rollbacks — the two the paragraph above already puts in the "no state tells the
two calls apart" bucket. `d239480`'s divergence has no live case left anywhere in this store.

What `archive` IS still alone in is a different fact, and conflating the two is how the wrong
count got written: `archive`'s destination guard is deliberately still `_reachable` alone, so a
dangling symlink at `archive/<name>.md` is still silently replaced there — pinned by
`test_archive_still_replaces_a_dangling_symlink_after_the_restore_guard_change`. That is a guard
difference between two methods of the SAME runtime, not a difference between the runtimes, and it
belongs in no divergence row at all.

They are named here rather than listed above because this list
is for what is **not** fixed, and a closed item left in it is a stale record. None of the
three was ruled: a ruling is the price of a DELIBERATE difference, and an operator CLI that
answers a permission error with a stack trace is not a decision anybody made. The measurement
and the reasoning for each live in `memorycli.mjs`'s header, beside the cases that now
compare the fixed behaviour.

So the sentence this section used to open with — "`runtime-py/` is the reference and was not
modified" — is no longer true, and is removed rather than qualified. What is still true is
narrower and is the rule above: the port does not get to change the reference to make its own
comparison easier. It may hand a defect BACK, and three were.

**Unmeasured, registered rather than guessed:** `cli.ts`'s `--assets-root` output writes `\n`
where the reference's text-mode stdout would write `\r\n` on Windows. No case compares the
two, so this is a suspicion with a location, not a measurement. It is now the only unmeasured
member of its class: the same defect on the memory CLI's streams **was** measured — 27 CRLFs,
19 of them written into `sys.stdout`/`sys.stderr` by `argparse` itself from frames no call
site owns, which is why the fix reconfigures the streams rather than sweeping the `print()`
calls — and item 6 above is what that measurement left open one layer down. `--assets-root`
is the same shape and has simply never been run on Windows by anything that compared it.

## The unported Python modules, one verdict per row

`docs/roadmap-agent-stack.md` AS-6 named sixteen `runtime-py/src/bantamkit/` modules with no
`.ts` counterpart and left them unaudited. J46-2 re-derived the list rather than trusting
AS-6's, because a name-only diff produces false rows — a module can have a counterpart under a
different name (`mcpserver.py` → `mcp/server.ts`, already caught by AS-6) or have its function
folded into another module's file rather than shipping as its own.

**Re-derivation, run clean:**

```
comm -23 \
  <(find runtime-py/src/bantamkit -name '*.py' ! -name '__init__.py' ! -name '__main__.py' \
      | sed 's#runtime-py/src/bantamkit/##; s#\.py$##' | sort) \
  <(find runtime-ts/src -name '*.ts' \
      | sed 's#runtime-ts/src/##; s#\.ts$##' | sort)
```

Run clean, this prints exactly fifteen names, sorted:

```
agent
budget
client
criticreplay
critique
docmanifest
evalrun
filegraph
loopguard
mcpserver
memory/divergence
pdfread
profile
structured
textutil
```

That is AS-6's own sixteen minus `repomap` — `runtime-ts/src/repomap.ts` now exists (AS-6
flagged this row `(J45-10 pending)`; it has since landed), which a bare path-and-suffix diff
already resolves correctly on its own, no rename table needed. Two of the remaining fifteen
are still false rows, found not by name but by reading the actual code:

- **`mcpserver`** — AS-6 already named its counterpart: `mcp/server.ts`. Dropped, per AS-6's
  own caveat.
- **`docmanifest`** — not caught by AS-6. `docmanifest.py` exists only to stop `evalrun.py`
  and `mcpserver.py` from hand-building the same manifest-entry dict twice and drifting (its
  own docstring names the drift this fixed: two different `document_no_rows`-shaped sentences
  for a zero-row part). `runtime-ts` has no second caller to drift against — only
  `mcp/server.ts` reads a document on that side — so the port folds `manifest_entries` /
  `package_entries` / `document_no_rows` inline into the `bantamkit_read` case
  (`runtime-ts/src/mcp/server.ts`, the `documentManifest(...)` call building the same entry
  shape `docmanifest.py` builds), rather than factoring out a module with only one caller.
  Same output, verified on the wire by `tools/conformance/suites/wire.mjs` and
  `tools/conformance/suites/docread.mjs`. Dropped from the list; this is the new finding this
  unit adds to AS-6's own audit.

That leaves **thirteen real rows** — three fewer than AS-6's sixteen: `repomap` (now ported),
`mcpserver` (renamed, already known) and `docmanifest` (inlined, newly found here) are the
difference.

**How "dead" was decided.** Not by reading — by an anchored import grep run separately for
each name, over `runtime-py/src`, `runtime-py/tests` and `tools/`:

```
grep -rn '^from bantamkit\.<name> import\|^from bantamkit import <name>\|^import bantamkit\.<name>\b' \
  runtime-py/src runtime-py/tests tools
```

Every one of the thirteen came back with at least one real import (never only a docstring
mention — `evalrun.py`'s and `docmanifest.py`'s prose mentions of each other were checked and
excluded this way). **Zero rows are dead.**

| module | verdict | why |
|---|---|---|
| `evalrun` | research-and-documented | The eval harness itself. `docs/architecture.md`: "**Measurement** is not a product layer — it is the boundary keeper: `evalrun.py` produces the evidence…". Not a console script (`runtime-py/pyproject.toml`'s only `[project.scripts]` entry is `bantamkit-mcp = bantamkit.mcpserver:main`); `mcpserver.py`'s one `evalrun` hit is a comment, not an import. |
| `agent` | research-and-documented | `docs/architecture.md`'s layer table names `agent.py` as Layer 1 and states the port "implements Layers 1 + 3 and whatever Layer-5 surface it wants" — Layer 1 is not owed whole. Its only product-surface-adjacent caller is `memory/component.py`, whose port (`runtime-ts/src/memory/component.ts`) documents the check directly: "`setup()` and `batch()`, the only two consumers of `Agent`. The prep probe traced a real stdio server through the tools and both resource templates: neither is reachable from the MCP surface." |
| `budget` | research-and-documented | `budget.py`'s own docstring: "Layer 1 — a global spend governor for one agent run". Reached only through `agent.py`/`evalrun.py`, both above — same unreachable-from-MCP finding applies transitively. |
| `client` | research-and-documented | `docs/porting.md` already states it, measured with `sys.settrace`, not guessed: "`client.py` and `memory/divergence.py` execute **zero** call-time lines on the MCP path" (§"What the port actually covers"). Its `BantamError` base class already has a named counterpart — `runtime-ts/src/errors.ts` opens "The error base the Python runtime exposes from `bantamkit.client` as `BantamError`." The remainder (`ModelClient`, `OpenAICompatible`, `Message`/`ToolCall`/`Usage`) is the eval harness's LLM transport and reaches only `agent.py`/`evalrun.py`/`critique.py`/`structured.py`/`criticreplay.py`/`budget.py` — confirmed by checking `assets.load_tool_asset` (what `mcpserver.py` actually calls) returns a plain `dict`, never the `client.Tool` dataclass that `assets.load_tool` (the eval-harness variant, unused by `mcpserver.py`) constructs. |
| `profile` | research-and-documented | `profile.py`'s own docstring: "Layer 4 — named tunable profiles". `docs/architecture.md`: "Layers 2 + 4 are pure asset-pack data, shared verbatim across runtimes" — the data (`assets/profiles/`) is already shared; the code that reads it for the agent loop's tunables is not owed since every caller (`agent`, `budget`, `critique`, `loopguard`, `structured`, `evalrun`) is itself unreachable from the MCP surface. |
| `loopguard` | research-and-documented | `loopguard.py`'s own docstring: "Layer 1 — consecutive identical-observation detection on tool calls". Attaches only via `Agent.use(...)`; same unreachable-from-MCP finding as `agent`. |
| `structured` | research-and-documented | Layer 1 gate mechanics (`docs/architecture.md`'s layer table: "gate mechanics in `critique.py` / `structured.py`"). Reached only through `agent.py`/`critique.py`/`criticreplay.py`/`evalrun.py`. |
| `critique` | research-and-documented | Same Layer 1 gate-mechanics citation as `structured`; `CritiqueGate` is constructed only by `evalrun.py` and `criticreplay.py`, neither reachable from `mcpserver.py`. |
| `criticreplay` | research-and-documented | Names its own layer in its own docstring: "Layer: Measurement. It reads Contract assets (rubrics) and the frozen suite read-only, calls Transport (`client.py`) and Core (`structured()`), and adds nothing to either." Used only by `tools/pinharness/` and its own tests. |
| `filegraph` | research-and-documented | `assets/tools/file_graph.json` declares `"surfaces": ["agent"]` — never `"mcp"`. `docs/filegraph.md` documents it as an `Agent.use(...)` component. `runtime-ts/src/mcp/server.ts` itself names the gap it deliberately leaves open: "of the thirteen manifests (`document_list`, `document_read`, `file_graph`) claim only `agent`." Matches this repo's own prior finding (`filegraph-serves-evalrun-not-the-operator`), re-confirmed here from the asset file and the port's own comment rather than quoted from memory. |
| `textutil` | research-and-documented | Its two real functions (`truncate`, `truncate_counted`) are imported only by `agent.py` (observation truncation in the research agent loop), `contract.py`'s `render_evidence` (critic-transcript rendering, called only by `critique.py`'s `CritiqueGate` — unreachable from MCP), and `filegraph.py` (unreachable, above). `docread.py`, the one product-surface reader, does **not** import it — `docread.page()`'s own docstring explains it computes `dropped` bytes itself, deliberately "WITHOUT `textutil.truncate`'s in-band marker"; `docread.ts` ports that inline byte-accounting directly (`dropped = size - utf8Length(text)` and siblings), which is why row/page truncation is already cross-runtime-conformance-tested without a `textutil.ts`. |
| `memory/divergence` | research-and-documented | `docs/porting.md` already states it (same sentence as `client`, above): executes zero call-time lines on the MCP path. Confirmed independently here: not imported by `memory/__main__.py` (the CLI) or `mcpserver.py` — only re-exported by `memory/__init__.py` and used by its own tests. It is a read-only instrument comparing this repo's memory store against Claude Code's own native store (its docstring: "Do two memory stores hold the same facts? A read-only instrument, owning no writer"), which is a fact about two things neither runtime serves as a tool. |
| `pdfread` | **product-and-must-port** | The one row that is actually owed. `docread.py` imports it directly (`from bantamkit import pdfread`) and `mcpserver.py`'s `bantamkit_read` reads PDFs through `docread.extract` in production. This is not a new finding — `docs/porting.md`'s own "pdf, doc and rtf on Node" divergence row already tracks it, with `ruling:` cases in `tools/conformance/suites/docread.mjs` and `wire.mjs` and a refusal-bit companion case, satisfying the deliberate-divergence bar. What is new here: that row's own text says "**job44 ports `pdfread`**", and job44 (`fix/job44-register-drain`, per `docs/conformance.md`) was the register-drain job, not a PDF port — `runtime-ts/src/docread.ts`'s `NODE_REFUSED` set still contains `'pdf'` today, and `docread.ts` still refuses it with "pdf is not readable by the Node server yet". The divergence row's promise is unfulfilled; the port remains owed. What would have to move: a hand-rolled PDF text extractor in `runtime-ts` under the no-new-dependency rule, the same shape as `pdfread.py`'s own (tokenizer, object graph via the `N G obj` linear scan, `ObjStm` expansion, `ToUnicode`/simple-font/`Differences` character provenance) — `pdfread.py`'s own docstring is effectively the spec for it. Not done in this unit (out of scope: audit, not port). |

**Counts:** 1 product-and-must-port (`pdfread`), 12 research-and-documented, 0 dead. 13 rows
total, against AS-6's 16 (the three-row difference is `repomap`, `mcpserver`, `docmanifest`,
explained above).

**For J46-3, on `evalrun`.** What imports it: `bantamkit/__init__.py` (`CONFIGS`,
`format_report`, `run_suite`), `criticreplay.py` (`TrackingClient`), and a chain of
`runtime-py/tests/test_document_*.py` files plus `tools/devteam/build_tasks.py`. Nothing in
`mcpserver.py` imports it (its one hit there is a comment). What it pulls in, transitively:
`docmanifest`, `agent`, `assets`, `budget`, `client`, `contract`, `critique`, `docread`,
`filegraph`, `loopguard`, `profile`, `structured` — i.e. essentially every module in this
table plus the two shared, already-ported modules (`assets`, `contract`, `docread`). It is
the hub that gives all the Layer-1/3/4/Measurement modules above their only import path; it
has no CLI entry point of its own (no `[project.scripts]` binding, `python -m` only) and no
MCP tool advertises it. For it to reach a surface, either a new MCP tool or CLI subcommand
would have to call `run_suite`/`format_report` directly — nothing today does.

**AMENDMENT (J46-3, AS-3's decision, checked rather than accepted).** AS-3
(`docs/roadmap-agent-stack.md`) names two honest endings for `evalrun` — port it to
`runtime-ts` with a CLI on both sides, or record here that it is a research tool shipping on
**neither** surface — and forbids the third, silence. **The ending is: neither surface,
recorded.** `evalrun`'s own `research-and-documented` verdict above already points this way;
this amendment is the three-part check AS-3's gate demands before taking that ending, run
against the repo rather than assumed:

1. *Not on the surface today.* Same finding as J46-2's paragraph above, re-run independently:
   `grep -n '\[project.scripts\]' -A2 runtime-py/pyproject.toml` shows the one entry,
   `bantamkit-mcp = "bantamkit.mcpserver:main"`; `grep -n evalrun runtime-py/src/bantamkit/mcpserver.py`
   returns one line, a comment, not an import. TRUE.
2. *Porting buys nothing a user can call, for a cost that recurs.* `wc -l
   runtime-py/src/bantamkit/evalrun.py` = 1999 — the "~2000 lines" AS-3 names. Combined with
   check 1 (nothing calls it today, on either side), a port adds a maintenance surface with no
   caller at the end of it. TRUE, and it follows from check 1 rather than being separate.
3. *It reaches for something the pure-node ruling forbids.* Not a feeling about imports —
   traced. `evalrun.py` line 18 is `import yaml`; line 382 is
   `yaml.safe_load(f.read_text(encoding="utf-8"))`, parsing arbitrary task files
   (`assets/evals/tasks/*.yaml`) — e.g. `shop-stock-total.yaml` has a nested mapping
   (`scoring: {kind, expected}`), a list (`tools: [...]`), and a block scalar (`prompt: |`).
   The only YAML code on the Node side, `runtime-ts/src/memory/pyyaml.ts`, is not a general
   parser and says so in its own header: "this is not a YAML emitter. It is PyYAML's emitter
   for one document shape: a root-level block mapping whose values are strings, `null`, or
   lists of strings. Everything outside that shape throws rather than guessing." A
   `scoring:`/`tools:`/`prompt: |` document is outside that shape on every count. The
   dependency this file's own "Four libraries rejected" section (`js-yaml` for the emit side)
   already turned away is exactly what a general parse would need to reach for again, and the
   no-new-runtime-dependency invariant forbids adding it. TRUE.

All three hold, so the decision stands: **`evalrun` ships on neither `runtime-py`'s product
surface nor `runtime-ts`, and that is a recorded fact, not a gap.** J46-2's verdict
(`research-and-documented`) does not contradict this — it is the same conclusion, reached
first from reachability rather than from AS-3's three-part test.

**Whether this is a `ruling:` case.** No. This file's own convention (see the "Where the two
runtimes deliberately differ" rulings, e.g. the charset and compression rows above) reserves
`ruling:` conformance cases for a divergence that pins **wording both runtimes emit** for the
same call — the kind of thing a future edit could silently drift. This row is the other kind:
a module with no counterpart on the other side at all. There is no call either runtime answers
where the presence or absence of `evalrun.ts` produces a wording difference to pin, and no
refusal bit to compare, because `evalrun` is unreachable from both MCP surfaces — there is no
user-facing call on either side that this ending could make diverge. `agent`, `budget`,
`profile`, `loopguard`, `structured`, `critique`, `criticreplay`, `filegraph`,
`textutil` and `memory/divergence`, above, are the same kind of row and none of them carries a
`ruling:` case either, for the same reason. A ruled case here would be unpinnable — there is
no observable behaviour on either side for it to hold constant — so adding one would be a case
that can never fail, which is worse than no case.

## Concurrency

Measured, not assumed: 12 pipelined saves all land in order; a recall behind a save **sees**
the save in Node and does **not** in Python; two processes over 8 trials × 15 saves gave 0
disagreements.

One hazard exists and is **not** a port defect: concurrent same-unit `clock_out` loses a
history entry, 10/10 on Node **and** 10/10 on CPython. Reproduced, not introduced. Do not
"fix" it on one side only.
