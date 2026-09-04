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
| `build_id` | hashes the executing tree; two runtimes, two trees. `assets_digest` **is** identical (`sha256:b03141bf…`) and that is the one that matters. |
| the event log's build identity | **not a difference — an omission, for this reason.** A `build_id` hashes the executing tree and the two runtimes are two trees (row above), so no build identity is a field in an event-log record at all; the `build_identity` record carries the COUNT of underivable fields instead. Same for `sessionId` (the server cannot observe it), pids and absolute paths. See [eventlog.md](eventlog.md). |
| the YAML scanner cases | the codec has no scanner; 5 shapes ruled, `!` filed alone |
| `checkSchema` wording | 50 cases; both sides refuse, the sentences differ |
| accounting via `fromJs` | an integral float; the `parseJson` route is byte-identical |
| on Windows, CRLF | **no longer a difference.** N11 reversed it: the emitter builds LF text, the WRITER translates, and the budget still counts the LF text — which is what CPython does. See [conformance.md](conformance.md). |
| the memory CLI's `prog` | `python -m bantamkit.memory` against `bantamkit-memory`. There is no third spelling: the reference's prog is a Python `-m` invocation and a pure-npm install has no Python in it, while `bantamkit-memory` names a console script CPython does not install. It moves the usage line, every `…: error:` prefix, and the two remediation sentences that name a command the reader must type — `lint`'s `try: … compact …` and `compact`'s `restore one with: …`. It also moves the WRAP, because argparse's hanging indent is `len(prefix) + len(prog) + 1`: 10 columns apart at COLUMNS=80, and at COLUMNS=40 the two runtimes take different `_format_usage` branches outright. 24 ruled cases in `tools/conformance/suites/memorycli.mjs`, **all 24 PAIRED with an unruled case over the same bytes after the substitution** since 2026-08-25 — 19 against an unruled case over exactly the same region (13 `…/stderr-raw` against `…/stderr`, 2 `…/remediation-line-raw` against `…/remediation-line`, and each of the 4 `w80/usage-block` rulings against its `usage-block-compensated`, which re-runs the reference 10 columns wider and requires the wrapped blocks to match exactly), and 4 `w200/prog-line-raw` against the unruled `w200/usage-block` that covers that same line 1 with the substitution applied. **The 24th, `help-top/w40/usage-block`, got its companion on 2026-08-25** and this row previously said it could never have one. The reason given was that no compensation exists at 40, because the reference sits in argparse's FLAT branch there and widening it over-corrects an indent that no longer depends on `prog`. That overlooks what widening actually does: the branch test is `len(prefix) + len(prog) <= 0.75 * (COLUMNS - 2)`, and COLUMNS is the term the compensation changes — at 40 the reference needs 33 against an allowance of 28.5 and goes flat, at 40+10 it needs 33 against 36 and hangs. So at the compensated width BOTH sides are in the hanging branch, where the compensation is exact, and the blocks match byte for byte. The emission condition in the suite is now `ruling` rather than `width === 80`, which is the property that was wanted all along: a companion belongs wherever a ruling is. `BRANCH_SPLIT_RULING`'s SIBLING argument — at COLUMNS=40 the three sub-parser forms are unruled and byte-identical, their longer progs putting both runtimes in the flat branch, so the split is a BAND the top parser alone falls out of rather than a second rendering algorithm — still holds and is still worth keeping, but it now stands beside a gate instead of in place of one. |
| `tools/list` key order | **key order only; the content is compared with keys sorted and is identical.** `mcp` 2.0.0's outbound serializer reorders the tool entry and its `inputSchema` on the way out: `memory_compact`'s manifest says `type, properties` and the reference emits `properties, type`; `memory_save` and `memory_recall` say `type, required, properties` and arrive as `properties, required, type`; the other six already read `properties, [required,] type[, title]` and arrive unchanged. `Tool.input_schema` is a plain dict and `model_dump_json` was measured to preserve manifest order, so the reordering has no seam this package can reach; the port serves the manifest bytes as written. Ruled in `tools/conformance/suites/wire.mjs`: `tools/list: the reference reorders keys the port emits in manifest order` is the ruling over the raw frame, and beside it the unruled `advertisement: id 2` compares the same frame with keys sorted, so a port that changed a VALUE rather than an order still fails. |
| the `index-budget-low` remedy | **the same substitution, one surface further out.** The degraded status report ends `archive or shorten facts with \`…\``, and `mcpserver.py` names `python -m bantamkit.memory compact` where `runtime-ts/src/mcp/status.ts` names `bantamkit-memory compact` — for the reason in the row above, and with no third spelling for the same reason. Printing the reference's command to someone holding an npx install is an instruction that cannot be followed. It is a LITERAL on both sides and not an import: neither MCP server imports its CLI module, so the coupling is held from OUTSIDE, by `runtime-py/tests/test_status_surface.py::test_the_index_remedy_names_the_command_this_install_actually_provides` and by `runtime-ts/test/server.test.mjs`'s degraded-report test, which reads `package.json`'s `bin` rather than spelling the name. Ruled in `tools/conformance/suites/wire.mjs`: `status-degraded: the remedy lines, raw` is the ruling, and it is a LIST, so a runtime that moved the report's copy and left the footer's alone fails it; beside it `…, after the one substitution` is unruled over the same sentences, and `…: the command each side tells the operator to type` pins the two literals. Changing either sentence alone reddens the run; making them equal fails as a stale ruling. |
| pdf, doc and rtf on Node | **the port identifies the three kinds and refuses them by name; the reference reads them.** `docread.py` reads PDF through `bantamkit.pdfread` (stdlib, written for this program) and real OLE2 `.doc` and `.rtf` through `/usr/bin/textutil`, a macOS built-in it probes at every call and refuses by name where absent. `docread.ts` has neither: `sniff` still names the container, the size on disk and the suffix disagreement exactly as `_refuse` does, and the remedy clause says which server can read it — `pdf is not readable by the Node server yet (the Python server reads it); see docs/porting.md` and `<doc|rtf> is read through /usr/bin/textutil by the Python server and not by the Node server; see docs/porting.md`. No runtime dependency is allowed into `runtime-ts` (one runtime dep, `package.json`), so the pdf side is a PORT and not an install: **job44 ports `pdfread`** and closes the pdf half of this row; doc/rtf stay refused on Node until a reader that is not a macOS binary exists. Ruled in `tools/conformance/suites/docread.mjs` — `extract: <fixture>: <kind> is RULED` over eight fixtures (`tiny.pdf`, which the reference READS to one row; `doc.pdf`, `sheet.xlsx.pdf`, `named.xlsx`, header-only PDFs both refuse; `real.doc` and `sheet.xls`, OLE2 signatures both refuse; `bad.rtf`, both refuse; `note.rtf`, read by the reference exactly where textutil is) — and in `tools/conformance/suites/wire.mjs`, `read-ruled: id 2..7` over the same shapes on the wire plus `read-ruled: the outcome sequence` for the event log. **Every ruling has two companions**: `…: the refusal bit each side is required to carry`, a literal `{python, node}` pair that says which side must refuse (the reference's bit is a function of `textutil_path()`, reported by the reference itself, never assumed), and where both refuse `…: both refuse (the refusal bit, side to side)`, the unruled comparison CLAUDE.md requires. On a host without textutil nothing is skipped: the rulings still differ and the companions still both refuse, and the suite's note prints which host it measured. Teeth demonstrated 2026-08-28: making the ruled cases match reddened all eight as `STALE RULING`. |
| utf-7 on Node | **the two runtimes decode a MIME text part through two different codec registries, and only one of them has utf-7.** `docread.py` decodes a `text/*` part by its declared `charset` through CPython's codec registry, which has `utf-7`, so a part declaring `charset=utf-7` with `caf+AOk- done` in it reads as `café done`. `docread.ts` decodes through the WHATWG Encoding Standard's `TextDecoder`, whose label table deliberately has no utf-7 (the standard dropped it as a security hazard), so the label is unrecognised, the fallback is UTF-8, and the same bytes read as `caf+AOk- done` — one row on both sides, one token apart. Both sides READ the file; neither refuses. The port DOES now carry CPython's single-byte codec tables — `runtime-ts/src/charsets.ts`, generated by `runtime-ts/scripts/charsets-table.py` from the interpreter's own `encodings` package (79 single-byte codecs, 326 aliases, 121 modules at CPython 3.12.13 — **AMENDED 2026-09-04: 72 single-byte codecs.** Review round 4's H1 (`666f14f`) found the generator judging statelessness with a six-lead-byte probe containing neither ESC (`0x1b`) nor `~` (`0x7e`), so SEVEN stateful modules — `hz` and the six `iso2022_jp*` — had been written out with a 256-character byte table they cannot have. The generator now sweeps all 65,536 ordered pairs and refuses all seven; 326 aliases and 121 modules are unchanged) and pinned against the live registry by the `charsets` conformance suite (`src/charsets.ts is what scripts/charsets-table.py writes for the live registry`, plus all 256 bytes of every codec decoded by the reference and compared to the table) — so the earlier reasoning here, that a second registry would be a maintenance burden, no longer applies to byte tables. It still applies to utf-7: utf-7 is a stateful modified-base64 transform, not a byte table, the generator cannot write it out, and no decoder for it is written, so the label still falls to UTF-8 on the port. Ruled in `tools/conformance/suites/docread.mjs`: `extract: utf7.eml: utf7 is RULED` over the whole answer, with `…: the refusal bit each side is required to carry` pinning `{python: false, node: false}`, `…: both read (the refusal bit, side to side)` as the unruled companion, and `…: the same shape around the ruled row` comparing kind, part names, row counts and omissions unruled so the ruling cannot hide a second difference. Teeth demonstrated 2026-08-28: forcing the ruled case to match reddened it as `STALE RULING` (`node tools/conformance/run.mjs --suite docread`: 774 cases, 1 failure), then the probe was removed. |
| `hz` and `iso-2022-kr` on Node | **the same divergence as the row above, under two more names — two stateful escape codecs CPython has and the WHATWG Encoding Standard does not.** `docread.py` decodes a `text/*` part by its declared `charset` through CPython's codec registry, which has `hz` and `iso2022_kr`; `docread.ts` decodes through `TextDecoder`, whose label table has neither, so the label is unrecognised, the fallback is UTF-8, and the escape machinery comes back as literal text. MEASURED 2026-09-04 on the two fixtures built in `tools/conformance/suites/docread.mjs`: `hz.eml`'s `~{:O::~}` reads `合汉` on the reference and `~{:O::~}` here; `iso2022kr.eml`'s `ESC $ ) C SO = " SI` reads `숱` there and `\x1b$)C\x0e="\x0f` here. Both sides READ the file to one row; neither refuses. THIS IS NOT NEW BEHAVIOUR and it is not a regression: `decodeCharset`'s own docstring already said these labels fall to UTF-8. What was missing was the PRICE — review round 4 found it with no divergence row, no `ruling:` case and no companion, which is a CLAUDE.md violation whatever the behaviour is. The cause is the same as `utf-7 on Node`: each is a stateful escape transform, not a byte table, so `runtime-ts/src/charsets.ts` cannot carry it. H1 (`666f14f`) is what made this visible — the generator's statelessness probe used to be six hand-picked lead bytes containing neither ESC (`0x1b`) nor `~` (`0x7e`), so seven stateful modules were written out with a 256-character byte table they cannot have; the full 65,536-pair sweep refuses all seven (79 -> 72 tables) and the labels now reach the decoder chosen by measurement over 8,829 inputs against CPython (ICU 5,664 correct, byte table 5,021, utf-8 4,339). `hz`, `iso2022_kr` and `utf_7` score 0 % through WHATWG, which is why six labels route to ICU and not nine. Not ported, because lifting it means three modified-escape decoders written by hand under the no-dependency rule, for shapes nothing in the measured corpora (`docs/eval-data/`) uses. Ruled in `tools/conformance/suites/docread.mjs`: `extract: hz.eml: statefulCjk is RULED` and `extract: iso2022kr.eml: statefulCjk is RULED` over the whole answer, each with `…: the refusal bit each side is required to carry` pinning `{python: false, node: false}`, `…: both read (the refusal bit, side to side)` as the unruled companion — which is the case that catches one side starting to REFUSE, something a ruling can never do — and `…: the same shape around the ruled row` comparing kind, part names, row counts and omissions unruled. Teeth demonstrated 2026-09-04: before the rulings existed the same two fixtures gave `FAIL: 1050 cases, 4 failures`; with them, `PASS: 1048 cases, 15 ruled-different, 0 failures`. |
| bzip2 and lzma zip members on Node | **the reference reads a zip member stored with compression method 12 (bzip2) or 14 (lzma); the port refuses it by member, method number and name.** CPython's `zipfile` links the `bz2` and `lzma` modules and decompresses both methods transparently, so a `.docx` whose `word/document.xml` was written with `ZIP_BZIP2` or `ZIP_LZMA` reads to its row (`hello` in the fixture). `docread.ts` decompresses through `node:zlib`, which has deflate and nothing else the zip format names, and `runtime-ts` may carry no runtime dependency beyond the one in `package.json` — so the port refuses with `<name> is a zip but its <member> uses compression method 12 (bzip2), which the Node server cannot decompress (the Python server reads it); see docs/porting.md` (14 (lzma) for the other). **AMENDED 2026-09-04 (review round 4, M1): this row rules the REQUIRED member only.** An OPTIONAL member stored with the same method is now PARITY, not a ruling: `isUnreadableOptional` omitted `DocumentReadError`, so a `.xlsx` whose `xl/styles.xml` was written with `ZIP_BZIP2` made the port refuse the whole document the reference reads. Fixed in `aa49760` with the fixture `bzip2-optional-styles.xlsx` (built in `runtime-ts/test/docread-fixtures.mjs`), compared UNRULED in the `docread` suite: a member this port cannot decompress costs that MEMBER and never the document, and both sides answer the same bytes. **Residual, unfixed and unfixtured:** a bzip2 `xl/styles.xml` that carries DATE FORMATS still diverges — the reference decompresses it and emits the `number-format` omissions, and this port cannot produce them. Same cause as this row; no fixture exists for it. Registered as roadmap row 8 (t). Method 9 (deflate64), the encrypted flag and a damaged member are NOT rows here — since round 3 (H1/H2) each has its own sentence and BOTH sides print it, pinned unruled in `docread` (the checked-in `compression-method-9.docx`, `encrypted-member.docx`, `encrypted-mimetype.odt`, `bad-crc.docx`, `corrupt-deflate.docx`) and in `wire`'s `read-round3` session as literals: `<name> is a zip but its <member> uses compression method 9, which this reader cannot decompress` (method 9 used to print the encrypted sentence, because `zipfile` raises `NotImplementedError` for both; the reference now reads the method off the member's header first); `<name> is a zip but its <member> is encrypted, so this reader cannot read it without a password`; and `<name> is a zip but its <member> is damaged (<cause>), so this reader cannot read it`, where the parenthesised cause is CPython's own words — `Bad CRC-32 for file 'word/document.xml'` from `zipfile`, `Error -3 while decompressing data: invalid block type` from `zlib` — which the port reproduces byte for byte **for every cause zlib names** (`docread.ts` `isDamagedMember`, the `BadZipFile` and `zlib.error` sentences). **AMENDED 2026-09-04 (review round 4, L3): the unqualified "byte for byte" was wider than what is measured.** The port rebuilds the sentence by hand as `` `Error ${e.errno} while decompressing data: ${e.message}` ``, which is exact for the shape a fixture exercises (`corrupt-deflate.docx`, zlib return code -3 with `msg = "invalid block type"`). CPython's `zlib_error` formats `"Error %d %s"` with NO cause clause when `zst.msg` is `NULL`, and substitutes its own fixed strings (`incomplete or truncated stream`, `inconsistent stream state`, `invalid input data`) before that; `node:zlib`'s message in those cases is its own and the two sentences would differ. No input that makes zlib return an error with a null `msg` has been constructed, so this is a GAP, honestly unmeasured, and not a measured divergence — which is exactly why the claim is narrowed to the class a fixture holds rather than left standing over a class nobody has reached. Registered as roadmap row 8 (s). Ruled in `tools/conformance/suites/docread.mjs` (`extract: bzip2.docx: bzip2 is RULED`, `extract: lzma.docx: lzma is RULED`, each with `…: the refusal bit each side is required to carry` as the literal `{python: false, node: true}`, `…: the reference reads the row as measured` pinning `hello` — generated from the reference's own run, not typed — and `…: the port refuses in the sentence the ruling quotes` pinning the port's sentence with its method number) and in `tools/conformance/suites/wire.mjs`'s `read-round2` session (ids 7 and 8 ruled, the same three companions on the wire, and `…: the reference's manifest names one part of one row`). Neither side refuses on BOTH, so there is no side-to-side refusal-bit companion; the literal pair is what says which side must read. Teeth demonstrated 2026-08-29: forcing the ruled case to match reddened it as `STALE RULING` (`node tools/conformance/run.mjs --suite docread`), then the probe was removed. Lifting it means a bzip2 and an lzma decoder written for this program under the no-dependency rule; nothing in the measured corpora (`docs/eval-data/`) uses either method, so it waits. |
| RFC 2231 charset continuations on Node | **the two runtimes reassemble a `Content-Type` parameter differently, and only one of them reassembles it at all.** RFC 2231 lets a parameter arrive in numbered pieces (`charset*0=utf-8; charset*1=…`) or as an encoded value (`charset*=utf-8''…`). `docread.py` reads a MIME part's charset through `email.policy.default`'s header parser, which joins the pieces with semantics that are its own: `charset*1=x; charset*0=y` joins to `yx`, and a plain duplicate `charset=utf-8` on the same header LOSES to the continuation. So `rfc2231-charset.eml` (checked in under `runtime-py/tests/data/docread/`) decodes as UTF-8 and reads `café au lait`. `docread.ts` reads the plain `charset=` parameter only, finds no usable label, and decodes the same bytes through UTF-8 with replacement: `caf� au lait`. Both sides READ the file to one row of one part; the row differs by two bytes' worth of replacement characters (the reference's row is 12 UTF-8 bytes, the port's 14), and the `text_bytes` figure moves with it. Not ported, because porting it means carrying `email`'s parameter reassembly — its piece ordering, its duplicate rule, its language tag and its percent-decoding — for one row on one shape, far over the port budget. Ruled in `tools/conformance/suites/docread.mjs`: `extract: rfc2231-charset.eml: rfc2231 is RULED` over the whole answer, with `…: the refusal bit each side is required to carry` pinning `{python: false, node: false}`, `…: both read (the refusal bit, side to side)` as the unruled companion, and `…: the same shape around the ruled row` comparing kind, part names, row counts and omissions unruled. On the wire, `read-round2: id 10` in `tools/conformance/suites/wire.mjs` is the ruling, with the same two companions and `…: the same manifest around the ruled row`, which blanks the row and its byte count and compares the rest of the manifest byte for byte. Teeth demonstrated 2026-08-29: forcing the ruled case to match reddened it as `STALE RULING`, then the probe was removed. |
| `<!ATTLIST>` defaults on Node | **the reference's `expat` applies an internal DTD's `<!ATTLIST>` default attribute values; the port's internal-subset walk skips the declaration.** `attlist.xlsx` (built in `tools/conformance/suites/docread.mjs`) is a sheet whose XML opens `<!DOCTYPE worksheet [<!ATTLIST c t CDATA "s">]>` and holds a `<c r="A1"><v>0</v></c>` written WITHOUT a `t` attribute. `docread.py` reads it through `xml.etree`'s expat, which supplies the default `t="s"`, so the cell is a shared-string index and reads `SHARED`; `docread.ts`'s `parseDoctype` reads `<!ENTITY>` declarations (pinned unruled by `internal-dtd-entity.docx`) and skips `<!ATTLIST>` over its quoted strings, so the cell is a number and reads `0`. Both sides READ the file to one row of one part; the row differs by that one cell (`SHARED\tplain` against `0\tplain`, measured 2026-08-29 on both). Not ported, because applying defaults means carrying expat's attribute-declaration model (per-element, per-attribute, `#IMPLIED`/`#REQUIRED`/`#FIXED`, the CDATA/NMTOKEN normalisation) into a walk that exists to read four element names, and no OOXML writer emits an internal DTD at all — this was a "gap the differential cannot see" until H3 built the fixture that shows it. Ruled in `tools/conformance/suites/docread.mjs`: `extract: attlist.xlsx: attlist is RULED` over the whole answer, with `…: the refusal bit each side is required to carry` pinning `{python: false, node: false}`, `…: both read (the refusal bit, side to side)` as the unruled companion, and `…: the same shape around the ruled row` comparing kind, part names, row counts and omissions unruled. Teeth demonstrated 2026-08-29: removing the `<!DOCTYPE>` from the fixture made the two rows match and reddened the case as `STALE RULING` (`node tools/conformance/run.mjs --suite docread`: 983 cases, 1 failure), then the fixture was restored. |
| `str.isalpha()` against `\p{L}` in `skillaudit` | **the two runtimes read two different Unicode databases, and they are compiled against two different revisions of the standard.** `skillaudit.py` asks CPython's own tables through `str.isalpha()` and `str.isalnum()`; `skillaudit.ts` asks V8/ICU through `/\p{L}/u` and `/[\p{L}\p{N}]/u`. MEASURED 2026-09-05 by brute force over all 1,112,064 code points (`0x0000`-`0x10FFFF` less the surrogate range) on this machine: CPython 3.12.13 carries `unicodedata.unidata_version` 15.0.0 and Node 25.2.1 carries `process.versions.unicode` 16.0 (ICU 77.1); **4,924 code points disagree for alpha and 5,004 for alnum, and every disagreement is ONE-DIRECTIONAL** — the port answers letter where the reference does not, never the reverse, because 16.0 only added characters to the letter categories. The first is U+1C89 (CYRILLIC CAPITAL LETTER TJE), which is `Cn`, unassigned, in 15.0.0. It reaches TWO sites and it moves them in OPPOSITE directions. In `_is_letter` / `isLetter` it is the apostrophe guard, so `\u1C89'race condition'\u1C89` is `['race condition']` on the reference (the flank is not a letter, so the quote delimits) and `[]` on the port — **the reference emits a `shared-trigger-phrase` the port does not**. In `_has_content` / `hasContent` it is the punctuation filter, so `"\u1C89"` is `[]` on the reference (no alnum in the phrase) and `['\u1C89']` here — the PORT keeps a phrase the reference drops. NEITHER SIDE IS WRONG: each is telling the truth about the Unicode revision it was built against, and the same reference on a CPython built against 16.0 would answer what the port answers today. Not lifted, because the fix is one of two things this program will not do: vendor a 136,104-entry category table into `runtime-ts` and re-vendor it on every CPython upgrade (the shape `runtime-ts/src/charsets.ts` takes for single-byte codecs, which is 79 tables of 256 entries, three orders of magnitude smaller and PINNED against the live registry by a suite — nothing pins a Unicode category table against a CPython that has not shipped yet), or make the reference stop asking CPython, which would make it disagree with the host it is auditing. No `SKILL.md` in either measured corpus contains a code point from the disagreeing set. Ruled in `tools/conformance/suites/skillaudit.mjs`: `phrases: the apostrophe guard over U+1C89: the Unicode version is RULED` and `phrases: the punctuation filter over U+1C89: the Unicode version is RULED`, each with `…: the answer each side is required to carry` as a LITERAL companion pinning `{python: ['race condition'], node: []}` and `{python: [], node: ['\u1C89']}` — the case that fails on its own line if CPython upgrades or ICU downgrades, rather than behind "they still differ". **There is no refusal-bit companion, and this is the judgement CLAUDE.md asks for: the difference is not refusal-shaped.** Neither runtime refuses this input; both return a list of phrases, and they differ in the CONTENT of that list. A refusal bit compared side to side would be `{python: false, node: false}` on every input this module has ever been given, ruled or not, which is a case that can never go red and is exactly the vacuous gate the rule exists to prevent. What the rule is protecting against — a ruling staying green while the port quietly stops answering at all — is instead covered by FOUR non-ruled ascii twins, two per ruled site: the same constructions with `A` in place of U+1C89, in both polarities. One of each pair is where the shared rule SUPPRESSES the phrase (both sides answer `[]`, which says the rule is still there) and one is where it KEEPS it (both answer a non-empty list, which is the case a reader that finds nothing fails). Each also carries a both-sides literal, so a twin cannot pass because both runtimes broke the same way. The second of each pair is not decoration: MEASURED 2026-09-05 by making `phrases` return `[]` for every input, the punctuation-filter ruling self-detects — it goes `STALE RULING`, because both sides then answer `[]` — and the apostrophe-guard ruling does NOT, because the reference's answer there is the non-empty one; the guard's `guard does not fire` twin is the only case in the suite that catches it, and the first draft of this row had only the vacuous half of the pair. Teeth demonstrated the same day: replacing U+1C89 with `A` in the two ruled texts reddened both as `STALE RULING` (4 differed), and killing `phrases` reddened 36 cases including two twins while one ruling stayed green; both probes were removed. |

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

## Concurrency

Measured, not assumed: 12 pipelined saves all land in order; a recall behind a save **sees**
the save in Node and does **not** in Python; two processes over 8 trials × 15 saves gave 0
disagreements.

One hazard exists and is **not** a port defect: concurrent same-unit `clock_out` loses a
history entry, 10/10 on Node **and** 10/10 on CPython. Reproduced, not introduced. Do not
"fix" it on one side only.
