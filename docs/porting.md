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

**NOT PORTED**, because this parser cannot reach them and an unmeasured port is a liability:
positionals and everything serving them (`consume_positionals`, `_match_arguments_partial`,
the intermixed arm), `required=`, required groups, `choices`, `nargs` other than `None`
and `0`, `SUPPRESS`, subparsers, `fromfile_prefix_chars`, and — in `textwrap` —
`initial_indent`/`subsequent_indent`, `expand_tabs`, `replace_whitespace`,
`fix_sentence_endings` and `max_lines`. Both `wrap` callers pre-normalise with argparse's
own `re.compile(r'\s+', re.ASCII)`, so no tab or newline can reach the wrapper.

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
`$ref` / `$dynamicRef` support this validator does not implement. Measured over 53 malformed
schemas: 53/53 refuse on both sides.

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
| `checkSchema` wording | 53 cases; both sides refuse, the sentences differ |
| accounting via `fromJs` | an integral float; the `parseJson` route is byte-identical |
| on Windows, CRLF | **no longer a difference.** N11 reversed it: the emitter builds LF text, the WRITER translates, and the budget still counts the LF text — which is what CPython does. See [conformance.md](conformance.md). |

## Gaps the differential cannot see, named rather than hidden

A row here is **not** a permitted difference. It is a property the two runtimes are
supposed to share where `node tools/conformance/run.mjs --all` is structurally unable to
compare them, so the only thing holding the property is a unit test on each side. Naming
the gap is the whole point: a green `--all` is not evidence about any of these.

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

## Defects registered against `runtime-py`, not fixed here

`runtime-py/` is the reference and was not modified. Found while porting:

1. Windows index-budget arithmetic — 13537 bytes on disk against 13472 checked. (The port
   now reproduces it rather than avoiding it; the reference's arithmetic is still the one
   that is wrong, and it is still not fixed here.)
2. `validate_json` lets `SchemaError` / `TypeError` / `_WrappedReferencingError` escape.
3. `shiftwork._read_valid` does not catch `UnicodeDecodeError`.
4. `_pinned_store`'s docstring states a false reason.
5. A `pattern` regex divergence.

**Unmeasured, registered rather than guessed:** `cli.ts`'s `--assets-root` output writes `\n`
where the reference's text-mode stdout would write `\r\n` on Windows. No case compares the
two, so this is a suspicion with a location, not a measurement.

## Concurrency

Measured, not assumed: 12 pipelined saves all land in order; a recall behind a save **sees**
the save in Node and does **not** in Python; two processes over 8 trials × 15 saves gave 0
disagreements.

One hazard exists and is **not** a port defect: concurrent same-unit `clock_out` loses a
history entry, 10/10 on Node **and** 10/10 on CPython. Reproduced, not introduced. Do not
"fix" it on one side only.
