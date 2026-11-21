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

The formatter is 3.12's. CPython 3.13 rewrote how a usage line wraps (a mutually exclusive group
may now break across lines) and how `invalid choice` lists the choices (CPython 3.11.15 lists
them with reprs too), so on every interpreter the Python CLIs parse with 3.12.13's own
`argparse`, vendored verbatim as `bantamkit/_argparse312.py` (`stdlib312.argparse`, J90-P8F), and
every `-h` stays the one this port renders.

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
*shape table* applied recursively and **gated by dialect** — deliberately not the metaschema,
which is several documents wired together across resources, and one resource is all this
validator resolves. Measured over 50 malformed schemas: 50/50 refuse on both sides; and over 28
dialect-gated shapes, each refused under the dialect that knows the keyword and answered under
one that does not (`check_schema/gated` in `tools/conformance/suites/validate.mjs`).

**The dialect is read from `$schema`** (job65, #126), as `validator_for` reads it: drafts 4, 6,
7, 2019-09 and 2020-12 each get their own keyword table and type checker, the URI is normalised
the way `_utils.URIDict` normalises it (an unknown URI, like no `$schema`, is 2020-12), and a
subschema re-dispatches on its own `$schema` as `Validator.evolve` does. Draft 3 is the one
dialect BOTH runtimes refuse, with one sentence — a narrowing of the reference library, not a
divergence between the two runtimes, and `contract.py` applies it before `jsonschema.validate`
so the Python half says the same words.

**`$ref` resolves inside the one resource a caller schema is** (job65, #125): `#`, a JSON
pointer and a plain-name `$anchor`/`$dynamicAnchor` all resolve against the root document, and
`unevaluatedItems`/`unevaluatedProperties` carry both walkers (`_utils` for 2020-12,
`_legacy_keywords` for 2019-09). What is NOT resolved is a second resource: a reference with a
scheme, host, path or query, or an embedded `$id` (`id` under draft 4) beside any reference, is
refused **before** validation with one sentence both runtimes print, answered as
`{valid: false, feedback}` rather than raised. The Python side narrows itself to the same rule
in `contract._unsupported_schema`, eagerly — the reference would resolve an unreached remote
`$ref` lazily and answer `valid`, and that is the price paid for the two never disagreeing. A
pointer to nowhere or an unknown anchor stays lazy on both sides (`referencing`'s
`PointerToNowhere`/`NoSuchAnchor`, caught and answered as the same sentence). Until job65 the
port RAISED on `$ref`, `$dynamicRef`, `$recursiveRef` and `unevaluated*`, and the suite carried
`ruling: $ref is not resolved`; that ruling is now the non-ruled case `$ref into #/$defs resolves
on both sides`, and the whole surface is the `drafts/` matrix.

**`pattern` is Python's `re`, on both sides** (job65, #131). `{"pattern": "("}` compiles
eagerly, as the metaschema's `"format": "regex"` makes the reference do, and from draft 6 a
`patternProperties` key does too. Until job65 the port compiled with `RegExp` (`u`, then a silent
non-`u` fallback that read `\Z` as a literal `Z`), which disagreed on 5 of 5 of the issue's
probes and was carried as two rulings. Now `pyjsonschema.translatePyPattern` parses `re._parser`'s
grammar and re-emits a `v`-mode RegExp whose every construct means what it means in `re`: `\d`
is `\p{Nd}`, `\w` is `[\p{L}\p{N}_]`, `\s` is the 29 codepoints `str.isspace()` names, `\b`/`\B`
are look-arounds over that `\w` (`\B` never matches the empty string — CPython 3.11-3.13; 3.14
changed it), `.` is `[^\n]`, `$` is `(?=\n?$)`, `\A`/`\Z` are the ends, `{,n}` and a `{` that is
not a repeat are what `re` reads them as. Measured over every codepoint, the three classes are
equal except for what Unicode 16 assigned after the reference's Unicode 15 (5,004 for `\w`, 80
for `\d`). Constructs with no faithful translation — inline flags (`(?u)` alone is the default
and passes), look-behind, backreferences, atomic groups, possessive quantifiers, conditional
groups and `\N{...}` — are refused by BOTH runtimes before validation with one sentence,
answered as `{valid: false, feedback}`; `contract._pattern_unsupported` finds them in
`re._parser`'s tree. A narrowing of the reference, not a divergence between the runtimes, so no
row in the table below. Measured: 80,000 random patterns over 36 strings, 0 disagreements on
refused-by-`re` / refused-as-unsupported / the search bit per string; the suite carries a seeded
4,000 of them as `pattern/dialect/*`.

**A document's patterns share a 500 ms budget** (job65, #132): past it the answer is one
sentence on both sides. The port stops a running search with `vm`'s timeout, so the event loop
is blocked for at most the budget; the reference runs each search in a long-lived
`python -I -S` child it can kill, because `re` holds the GIL for a whole search and no thread
can interrupt it. Which side times out first on a borderline pattern is machine-dependent; a
pattern that backtracks catastrophically times out on both.

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

The order is 3.12's. CPython 3.13 relaxed `count_run` (gh-116554), so its own `sorted` now probes
other pairs first; the Python store sorts with the compiled `sort_scored`, the same spelled-out
listsort, so both runtimes still answer 3.12's order on 3.13 and 3.14, and the 50,000-list case
is armed against a 3.11/3.12 reference only (J90-P8F).

## `ex-flow`: a fifth library, evaluated and rejected

The four above are CPython facilities with no usable JS equivalent. `ex-flow` (with
`exsorted`, its topological sort) is the opposite case and belongs here for the opposite
reason: it is a Node library that would have worked, and was rejected anyway.

**What it would have bought.** `workplan.ts` is a Kahn batcher — group the nodes with no
unsatisfied dependency, emit them, repeat. `ex-flow`/`exsorted` do that, and taking them
would have removed on the order of a hundred hand-written lines from `runtime-ts`.

**Why it was rejected.** `runtime-ts` carries **exactly one runtime dependency**,
`@modelcontextprotocol/sdk`. That is not a style preference; it is load-bearing, and three
rows of [Where the two runtimes deliberately differ](#where-the-two-runtimes-deliberately-differ)
cite it *by name* as the reason the port refuses a format the reference reads:

- **pdf, doc and rtf on Node** — "No runtime dependency is allowed into `runtime-ts` (one
  runtime dep, `package.json`), so the pdf side is a PORT and not an install".
- **bzip2 and lzma zip members on Node** — "`runtime-ts` may carry no runtime dependency
  beyond the one in `package.json`", which is why method 12 and method 14 are refused by
  member, method number and name rather than decompressed.
- **a bzip2 `xl/styles.xml` that carries date formats** — the same sentence again, which is
  why the port hands back a workbook whose `46235` it cannot explain.

Those three rows tell a user their document is refused *on principle*. Adding a graph
library to save a hundred lines of arithmetic would have spent that principle on the
cheapest thing in the repo to write by hand, and every one of those three refusals would
have become an excuse. The dependency count is the argument; the argument is worth more
than the lines.

**So `ex-flow` is the SPECIFICATION, not the dependency.** Both `workplan.py` and
`workplan.ts` were written by hand against its semantics — batch k holds every node whose
dependencies all appear in batches below k; order inside a batch is priority descending,
then declaration order; empty input is an answer, not a refusal — and the two are held to
each other by the `workplan` conformance suite rather than to a package on npm.

**And this is deliberately NOT a row in the divergence table.** Nothing here differs.
`workplan.py` and `workplan.ts` were compared over the whole `.shiftwork/` corpus and every
differential case passed on the suite's first run; a `ruling:` case would assert a
difference that does not exist, which is the one thing a ruling must never do. Route B — two
independent hand-written implementations — is the argument, and since the `workplan` suite
landed it is an argument with a gate behind it instead of a claim.

**One honestly unmeasured edge, named rather than hidden.** `planNodes` in
`runtime-ts/src/mcp/server.ts` documents two places where JS's dynamic typing and CPython's
part company on input the tool's schema does not admit: a `nodes` array mixing `5` and
`"5"`, and a non-numeric `priority`. They are **not** ruled and **not** gated — pinning them
would need a refusal corpus and a decision about whether the two runtimes are even required
to agree there. Until someone takes that decision they are a gap named in a comment, not a
divergence, and they are not a row here.

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

**#120 (job65): hand-edited YAML is read as PyYAML reads it, or refused by name — never
guessed.** Block scalars (`|`, `>`, every chomping and indentation indicator, PyYAML's own
folding rule) and one-line flow sequences of scalars (`links: [a, b]`) are now READ, and the
bytes a recall stamps back are PyYAML's. Before, `description: |` was read as the text
`| hand edited block` and stamped back to disk that way, and `[a, b]` refused the whole store.
Every other indicator at the start of a value (`` & * ! % @ ` { } ] , ``, `? `, `- `), a nested or
multi-line flow sequence, and a tab in a plain scalar RAISE a named `FactParseError`. Where
PyYAML reads one of those (an anchor, `!!str`, a flow mapping, `[a, [b]]`, `[a: b]`, a flow
sequence over two lines) the port refusing is the deliberate difference in the row below.
**Corrected J89-1F:** the tab is refused by PyYAML's PURE-PYTHON scanner (`yaml.SafeLoader`),
which is what "PyYAML rejects it too" in the codec's sentence means; **libyaml does not refuse
it** (`CSafeLoader` reads `a\tb` as `'a\tb'` and a trailing tab as nothing, PyYAML 6.0.3), and
runtime-py's fact read falls back to libyaml when it is installed (`factcodec._pyyaml_load`), so
there a fact holding one is READ by the reference and refused by the port. Measured J89-1F on
this machine (libyaml present). **J89-2 (the orchestrator's ruling): the refusal is the owner-ruled
`node-refuses` class and stays; only the false clause of its sentence changed**, to `… PyYAML's
pure-Python scanner rejects it too: <line>` (`factfile.ts`, `_generated/factfile.py` regenerated;
no case pinned the old words).

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
- One UTF-8 decoder in the package, with `ignoreBOM: true`, in `pyDecodeUtf8`. A leading BOM is kept as U+FEFF, as CPython keeps it, so a BOM'd JSON file is refused where Python refuses it (the #207 sidecar and term cache since J72-31). The fatal `TextDecoder` answers first and the CPython-message validator runs only on a refusal: the two accept the same bytes, checked over 64,028,929 inputs.

## Where the two runtimes deliberately differ

| | reason |
|---|---|
| `build_id` | hashes the executing tree; two runtimes, two trees. `assets_digest` **is** identical (read it off `build_identity` on either server, or `_assets_fingerprint()`; this row no longer quotes a digest, because each of the three it carried — `sha256:b03141bf…` at #75, `d47dcf4b…` over 87 files, `9e66e89a…` over 93 — went stale by the same route: the pack changed and the row did not; job67 J67-9) and that is the one that matters — but only because both walks now EXCLUDE `__pycache__`. That is a precondition, not a given: the pack ships eleven `.py` fixtures, `pip install` byte-compiles them, and on the published 0.27.0 artifacts the wheel answered `sha256:fa8372f6…` over 98 files against npm's `sha256:d47dcf4b…` over 87 while this row already claimed they were identical. Gated per side by `build_identity: a __pycache__ does not move assets_digest` in `tools/conformance/suites/wire.mjs` — per side, because pointed at one polluted pack both runtimes moved together and the cross-runtime comparison stayed green. |
| `build_identity`'s `compiled` (#316 G4, J90-P8) | **one field, each runtime's own answer, in one shape.** The Python release ships a mypyc platform wheel and a pure wheel built from the same `.py` files, so `code_digest` and `build_id` are one value for both and `compiled` is what tells them apart: `mypyc (23 compiled, 1 interpreted)` or `none (0 compiled, 24 interpreted)`, counted from where each `bantamkit._generated` module was loaded. The Node runtime has no compiled build and answers `not applicable (the Node runtime runs JavaScript; it has no compiled build)` — a string, not `{unavailable}`, because nothing failed to be derived. The values sit inside the `identity` session `wire` already rules un-comparable as a whole; what both must agree on, the `<kind> (<detail>)` string shape and its absence from `unavailable`, is compared unruled (`build_identity: both answer compiled as one ...`), and each side is held to its own allowed values by a per-side case. |
| the event log's build identity | **not a difference — an omission, for this reason.** A `build_id` hashes the executing tree and the two runtimes are two trees (row above), so no build identity is a field in an event-log record at all; the `build_identity` record carries the COUNT of underivable fields instead. Same for `sessionId` (the server cannot observe it), pids and absolute paths. See [eventlog.md](eventlog.md). |
| the YAML scanner cases | the codec has no scanner; 5 shapes ruled, `!` filed alone. **#120 adds 8:** an anchor, `!!str`, a flow mapping, an empty flow mapping, a nested flow sequence, a flow-sequence pair, a flow sequence over two lines and an anchored sequence item are READ by PyYAML and REFUSED by the port with a named `FactParseError` — reading them means porting the scanner, anchors and the composer. A refusal names the file and writes nothing, which is the point: the plain-text guess it replaced was stamped back to disk. Ruled in `tools/conformance/suites/codec.mjs` as `ruling: #120 node refuses where python reads: …`, with the refusal-bit companions as per-side literals (`#120 per side: the ruled inputs — python reads every one` / `— node refuses every one, with a named FactParseError`), because the two bits DIFFER and a side-to-side bit could never be green. Teeth: forcing the ruled answers equal reddened all 8 as `STALE RULING`; dropping `&` from the refused set left every ruling green and reddened the node literal (1 failure). **job67 (J67-3), user ruling 2026-10-15 on #120's remainder: these eight are the FINAL answer** — the PyYAML scanner is not ported, and the refusal is by name. What the ruling changed is what a refusal COSTS: a `memory_save` on Node no longer refuses the whole store because one fact file is one of these shapes. Both runtimes' `save` now skip any fact file they cannot read, name it (`SaveResult.skipped`, and a closing paragraph on the reply: `N fact file(s) could not be read and was/were skipped; the duplicate check read every other fact:` + `[project] <the store's sentence>`), and land; the one file a save never skips is the one it would WRITE (`<sentence>; saving '<name>' would overwrite that file, so nothing was saved -- repair it or move it out of facts/ first`). So over a store holding an anchored fact the save lands on both sides, Python reads the fact and Node names it skipped, and the `index.md` each rebuilds differs by that one line — ruled in `tools/conformance/suites/store.mjs` as `ruling: #120 save past a file only python reads — the answers`, with the refusal bit (`— the save lands on both sides`) and the written fact's bytes compared unruled and each side's skip pinned as a literal. Blank lines, lines of spaces and comment lines inside a block sequence — and `links: ` / `links: # c` before one — were NOT a ruled shape to keep: they are READ now, as PyYAML reads them, compared in `codec.mjs` as read-alike cases and a second 1500-frontmatter seeded corpus where node must neither guess nor refuse. **Since #315 (J86-3) runtime-py's store reads through the code compiled from the port's own `factfile.ts` first** (*Generated modules*), and that code refuses these eight shapes by the same names; `memory/factcodec.py` then reads the file with `yaml.safe_load`, exactly as before, so python still reads every one and this row's answers are unchanged (`ts2py-codec`'s `node-refuses` class: runtime-py reads each, `py=before` holds it equal to the pre-#315 read). |
| the grants config (`config.yaml`) over a document outside the port reader's language (J89-5b) | **Python reads it with PyYAML; Node with its own reduced reader, and the two may grant and refuse differently.** The orchestrator's ruling on J89-5's stop (option b), after the owner's #315 ruling for fact files: `memory/layers` is generated, and the config read stays on `yaml.safe_load` on the Python side (the `firstTokenTab` / `parseConfigDocument` adapters; Node's reader is `runtime-ts/src/memory/grantconfig.ts`). That reader implements no tag, anchor, alias, merge key, directive, second document, document end, flow mapping, escape, block scalar or flow sequence over lines, and refuses (or reads literally) what it does not implement; matching would mean porting PyYAML's scanner and composer. J89-5 found the first: `extra_stores: &a [g]` is a grant on Python and `extra_stores must be a list of paths` on Node. J89-5b's scan found 41 in the family (28 where Python grants and Node refuses, 13 where both refuse in different sentences). Each: a `RULED: config outside the reader's language — <document>` case in `tools/conformance/suites/recall-strings.mjs`, a non-ruled `J89-5b outcome bit per side: <document>` companion (the grant/refuse bit of each side against a literal, since a ruling only proves the two still differ) and the per-side literals `LITERAL: J89-5b python|node: load_grants over the config family, every answer`. The older `RULED: a config outside the reader's language, and PyYAML's scanner diagnostics` (the wording after the identical prefix) stands. **J89-5d added seven** (the orchestrator: a crash is a bug), documents where CPython raised out of `load_grants` what it never caught: an impossible implicit timestamp as a value, a key or a grant (`2001-02-30`, `25:00:00`), a 5,000-digit int, a decoded NUL in a grant and a flow sequence 1,000 deep. Python now refuses each with `invalid memory config <path>: <reason>`: CPython's own `str(e)` for a scalar PyYAML resolves but cannot construct, `the document is nested too deeply to read` past CPython's limit, and `extra_stores must be a list of paths` for a NUL (it names no path). Where Node grants (four) the outcome differs; where Node also refuses (the timestamp grant, the NUL, the deep sequence) the outcome bit agrees and the sentence differs. All seven carry the family's three pins (48 documents); see *The layers* and *J89-5d* under *Generated modules*. |
| the queries sidecar nested between Python's fixed limit of 512 and Node's stack (J89-5d, J89-5e) | **Node reads its well-formed entries; Python reads it as malformed.** `readSidecar` / `read_sidecar` (the `memory_queries` coverage, its missing list and write, `bantamkit_status`, recall's term rows) read through `parseJson`, the port of `json.loads`. Node's is a recursive descent whose limit is its stack: measured on macOS arm64, Node v26.13.0, past 1,562 nested lists cold and past 6,902 once V8 has optimised `parseJson` (binary searches over 40 warm-up rounds; it moves with tiering). CPython's `json.loads` has no one limit either (J89-5e, measured in Docker, `python:3.1x-slim`, default recursion limit 1,000): 3.11's C scanner is bounded by `sys.getrecursionlimit()` less the caller's frames (991 at the top level, 978-979 inside `parse_json` on the real MCP path, `memory_queries` / `memory_recall` / `bantamkit_status` in the AnyIO worker thread, 981 on the hook path), 3.12 reads to 9,997 (9,993 on the MCP path), 3.13 to 9,998 (9,994), and 3.14 has no fixed limit (20,000, the probe's ceiling). So J89-5d's answer, ruled at 8,500 on 3.12, was `[]` on 3.11 (the ruling went stale) and the band ran the other way between ~980 and 1,562. The orchestrator's rulings: Node's limit is an implementation limit, not a contract (J89-5d); a crash is a bug (J89-5d); Python's answer must not depend on the CPython version or its recursion limit (J89-5e). So the `parse_json` adapter reads at most **512** deep, a depth of its own below every supported CPython's on every user path, counted as `JSON.parse` nests (each array or object one level, the outermost included), and past it throws the RangeError `Maximum call stack size exceeded` Node throws past its stack, which the compiled `catch` sees (the depth is found by a non-recursive scan, `_json_too_deep`: the 513th opener counts only when the text before it is a well-formed prefix wanting a value there, so a text malformed earlier keeps `json.loads`'s own refusal; `RecursionError` stays mapped the same way as the backstop; the recursion limit is not raised). Between 512 and Node's cold limit the sides differ by ruling: Node reads and Python does not. From Node's stack on, both answer as no sidecar. Pinned in `--suite recall-queries`: `ruling: sidecar/nested — read of a sidecar nested 513 deep (between python's limit of 512 and node's stack)` (lists and objects) with a per-side literal each; the agreeing `sidecar/nested: J89-5e … nested 512 deep in lists|objects (python's limit)` cases, both reading, with per-side literals; and the agreeing `sidecar/nested: J89-5d …` cases at 8,500, 20,000 and 100,000 deep (read; coverage, the missing list and a write over a project sidecar 20,000 deep), each with per-side literals. The suite passes with a 3.11, a 3.12 and a 3.13 reference interpreter (`--python`). |
| a relative date counted in a Unicode 15.0 digit, on CPython 3.11 (J89-7, #316 G3) | **the interpreter's table, not the code.** CPython 3.11 reads UCD 14.0, so the 20 digits Unicode 15.0 added (Kawi U+11F50..U+11F59, Nag Mundari U+1E4F0..U+1E4F9) are not `\d` to its `re` and not digits to its `int()`; node's `pyRelativeScan` / `pyIntDigits` reproduce CPython 3.12's 15.0 table. `It landed 𑽓 days ago.` is unresolved on 3.11 and dated 2026-09-03 on node and on CPython 3.12-3.14, as main's hand-written dream did. Not lifted: matching would mean carrying a 15.0 table for `\d`, `\b` and `\w` in the adapter. Ruled in `--suite dream` as `J89-7 absolutise: a count in a Unicode 15.0 digit, python against node (UCD 14.0.0)` (an agreeing case from UCD 15.0), with a literal per side; the digit-count literal is keyed on the reported UCD version. See *Lowercase and digits on every supported CPython (#316 G3, J89-7)*. |
| the native memory mirror over a frontmatter only PyYAML reads (#228) | **the reference mirrors the file; the port skips it as `frontmatter`.** The mirror (job74) parses a native fact file with each runtime's own frontmatter reader: `yaml.safe_load` on the reference, `parseFrontmatter` on the port. The port reads the language the store emits plus the hand-written shapes #120 and #219 added, and refuses everything else by name — the eight #120 shapes (a flow mapping such as `metadata: {type: user}`, an anchor, …), a block sequence indented under its key (`links:\n  - a`), and any list or mapping two levels down (the memory-keeper shape `metadata:\n  links:\n    - a`, measured in 2 of 460 real native files on this machine, 2026-10-22). PyYAML reads all of them, so the reference saves a fact the port logs as `mirror-skipped` / `frontmatter`. Agreeing would mean porting the scanner, which the user's #120 ruling of 2026-10-15 declines, or making the reference drop a fact it can read. Nothing is written into the native directory on either side and both exit 0 with nothing printed. Ruled in `tools/conformance/suites/hooks.mjs` as `native-mirror-ruled: a frontmatter only PyYAML reads — the outcomes` over three files (flow mapping, indented list, keeper shape); each side's answer is pinned as a literal (`— the reference mirrors every ruled shape` / `— the port skips every ruled shape as frontmatter`), because the two bits DIFFER and a side-to-side bit could never be green; and the half the ruling does not license — exit 0, nothing printed, the native directory untouched — is compared side to side and pinned per side. Every other mirror outcome J74-4 found different by running both hooks (CRLF, a `{}` frontmatter, a falsy or non-scalar description, realpath of a missing tail or another-case spelling) was FIXED to agree, not ruled. **#315 (J86-3) leaves the mirror on `yaml.safe_load`:** the store now reads generated-first with a PyYAML fallback (*Generated modules*), and over these shapes the fallback answers, so the store and the mirror on the reference both read them as before; the mirror itself was not routed through the generated codec, because generated-first would also move the two classes #315's ruling licenses for the store (`yaml11-breaks`, `pyyaml-refuses`) into the mirror's outcomes, which this row pins. |
| the hot index over a native fact only PyYAML reads (#228, J90-1F) | **the reference indexes the file; the port skips it** (`HotIndex.skipped`, keyed by the file). The hot index's `"native"` kind reads a Claude Code auto-memory file with each runtime's own reader: `divergence.parse_fact` (`yaml.safe_load`) on the reference, `parseNative` (the codec's `parseFrontmatter`) on the port. Over the shapes #120 and the native-mirror row above leave to PyYAML (J90-1 pinned a flow mapping, `metadata: {type: user}`), the reference indexes the fact and the port names it skipped. This row extends the mirror row's licence to the index, for the reason the mirror row gives and one of its own: each side's hot index then holds exactly what that side's native mirror and recall read for the same file, so a user finds the fact on the runtime whose mirror read it and on neither runtime meets a fact the index promises and the reader cannot open. Agreeing would mean porting PyYAML's scanner (declined by #120's ruling of 2026-10-15) or making the reference index less than its own mirror reads. Ruled in `tools/conformance/suites/storage-index.mjs` (`lib/storage_j90.mjs`) as `ruling: #228 the hot index over a native fact only PyYAML reads (flow mapping) — docs and skips`; each side's outcome is pinned as a literal (`LITERAL: J90-1F #228 per side: … — python indexes it` / `— node skips it by file`), because the two bits DIFFER and a side-to-side bit could never be green; the half the ruling does not license — the block-mapping native fact beside it, indexed on both sides — is compared. Teeth: forcing node's answer to python's reddened the ruling (STALE) and the node literal; the reverse reddened the ruling and the python literal. Recall over native files on the reference already reads this way: the G3-generated native layer (`_generated/native.py`) reads each file through the `parse_native` adapter onto `divergence.parse_fact` and indexes through the hand-written `HotIndex`. **For #316 G4:** a generated `hotindex` must keep `parseNative` that same adapter, not the generated codec, or this row's python answer flips to the port's and the reference's index stops holding what its own mirror and recall read. |
| `MemoryStore.snapshot()` (Python only; J89-4b, #316 G3 U2) | **a Python-only API, kept by the shim, not a difference in any answer.** The pinned read set exists for ONE caller, `component.Memory.batch`, which `agent.py`'s loop (the Python eval agent, an unported module: no Node counterpart) enters around each assistant turn (RB-P1: a speculative save between two reads of one turn). `store.ts` deliberately omits it: the Node MCP server has no turn to pin. Since store.ts is generated it is hand-written in the shim (`bantamkit.memory.store`), built on the generated store: the pin is the generated `facts()` at entry, and while it holds the generated `candidates` answers it and `indexed` answers `null` (so `recall`, `lookup` and `pool` read the pin and `save` stays live), the same three moments `test_memory.py`'s snapshot cases pin. No `ruling:` case: no MCP tool, CLI or hook reaches it, so there is no Node answer to compare. |
| `storage.hotindex.no_gc()` (Python only; J90-2, #316 G4) | **a Python-only API, kept by the shim, not a difference in any answer.** A context manager that turns CPython's cyclic collector off for a block that only allocates (J68-5: a 5,000-fact head parsed, a scoring pass); `memory.store`, `memory.native` and the hot index's own reads used it. It tunes CPython's collector, which Node does not have, so `hotindex.ts` has no counterpart; since hotindex.ts is generated it is hand-written in the shim (`bantamkit.storage.hotindex`), and its callers (the store and native shims' `pool`) are unchanged. The generated index does not call it (the TypeScript cannot), so the parses it wrapped on main run with the collector on. No `ruling:` case: nothing it changes is an answer. |
| `Memory.setup()` and `Memory.batch()` (Python only; J89-6, #316 G3 U4) | **a Python-only API, kept by the shim, not a difference in any answer.** They are the only two consumers of `agent.py` (Layer 1, a Python-only library by the owner's ruling "keep it as Python"): `setup` registers `memory_save` / `memory_recall` / `memory_compact` on an `Agent`, adds `batch` as its batch scope and the `memory` skill as a system block; `batch` pins every WRITABLE layer's store with `snapshot()` (row above) for one assistant turn. `component.ts` deliberately omits both (its header says so: no MCP tool, CLI or hook reaches them), so since component.ts is generated they are hand-written in the shim (`bantamkit.memory.component`), on the generated facade: `batch` walks `_layers`, which are the shims of the very cores the generated component reads, so a pinned store pins what `recall` reads. Their callers (`agent.py`, `test_memory_component.py`'s agent cases, `tools/eval`) are unchanged. No `ruling:` case: there is no Node answer to compare. |
| `checkSchema` wording | 50 cases; both sides refuse, the sentences differ |
| accounting via `fromJs` | an integral float; the `parseJson` route is byte-identical |
| on Windows, CRLF | **no longer a difference.** N11 reversed it: the emitter builds LF text, the WRITER translates, and the budget still counts the LF text — which is what CPython does. See [conformance.md](conformance.md). |
| the memory CLI's `prog` | `python -m bantamkit.memory` against `bantamkit-memory`. There is no third spelling: the reference's prog is a Python `-m` invocation and a pure-npm install has no Python in it, while `bantamkit-memory` names a console script CPython does not install. It moves the usage line, every `…: error:` prefix, and the two remediation sentences that name a command the reader must type — `lint`'s `try: … compact …` and `compact`'s `restore one with: …`. It also moves the WRAP, because argparse's hanging indent is `len(prefix) + len(prog) + 1`: 10 columns apart at COLUMNS=80, and at COLUMNS=40 the two runtimes take different `_format_usage` branches outright. 24 ruled cases in `tools/conformance/suites/memorycli.mjs`, **all 24 PAIRED with an unruled case over the same bytes after the substitution** since 2026-08-25 — 19 against an unruled case over exactly the same region (13 `…/stderr-raw` against `…/stderr`, 2 `…/remediation-line-raw` against `…/remediation-line`, and each of the 4 `w80/usage-block` rulings against its `usage-block-compensated`, which re-runs the reference 10 columns wider and requires the wrapped blocks to match exactly), and 4 `w200/prog-line-raw` against the unruled `w200/usage-block` that covers that same line 1 with the substitution applied. **The 24th, `help-top/w40/usage-block`, got its companion on 2026-08-25** and this row previously said it could never have one. The reason given was that no compensation exists at 40, because the reference sits in argparse's FLAT branch there and widening it over-corrects an indent that no longer depends on `prog`. That overlooks what widening actually does: the branch test is `len(prefix) + len(prog) <= 0.75 * (COLUMNS - 2)`, and COLUMNS is the term the compensation changes — at 40 the reference needs 33 against an allowance of 28.5 and goes flat, at 40+10 it needs 33 against 36 and hangs. So at the compensated width BOTH sides are in the hanging branch, where the compensation is exact, and the blocks match byte for byte. The emission condition in the suite is now `ruling` rather than `width === 80`, which is the property that was wanted all along: a companion belongs wherever a ruling is. `BRANCH_SPLIT_RULING`'s SIBLING argument — at COLUMNS=40 the three sub-parser forms are unruled and byte-identical, their longer progs putting both runtimes in the flat branch, so the split is a BAND the top parser alone falls out of rather than a second rendering algorithm — still holds and is still worth keeping, but it now stands beside a gate instead of in place of one. |
| `tools/list` key order | **key order only; the content is compared with keys sorted and is identical.** `mcp` 2.0.0's outbound serializer reorders the tool entry and its `inputSchema` on the way out: `memory_compact`'s manifest says `type, properties` and the reference emits `properties, type`; `memory_save` and `memory_recall` say `type, required, properties` and arrive as `properties, required, type`; the other six already read `properties, [required,] type[, title]` and arrive unchanged. `Tool.input_schema` is a plain dict and `model_dump_json` was measured to preserve manifest order, so the reordering has no seam this package can reach; the port serves the manifest bytes as written. Ruled in `tools/conformance/suites/wire.mjs`: `tools/list: the reference reorders keys the port emits in manifest order` is the ruling over the raw frame, and beside it the unruled `advertisement: id 2` compares the same frame with keys sorted, so a port that changed a VALUE rather than an order still fails. |
| the `index-budget-low` remedy | **the same substitution, one surface further out.** The degraded status report ends `archive or shorten facts with `…``, and `mcpserver.py` names `python -m bantamkit.memory compact` where `runtime-ts/src/mcp/status.ts` names `bantamkit-memory compact` — for the reason in the row above, and with no third spelling for the same reason. Printing the reference's command to someone holding an npx install is an instruction that cannot be followed. It is a LITERAL on both sides and not an import: neither MCP server imports its CLI module, so the coupling is held from OUTSIDE, by `runtime-py/tests/test_status_surface.py::test_the_index_remedy_names_the_command_this_install_actually_provides` and by `runtime-ts/test/server.test.mjs`'s degraded-report test, which reads `package.json`'s `bin` rather than spelling the name. Ruled in `tools/conformance/suites/wire.mjs`: `status-degraded: the remedy lines, raw` is the ruling, and it is a LIST, so a runtime that moved the report's copy and left the footer's alone fails it; beside it `…, after the one substitution` is unruled over the same sentences, and `…: the command each side tells the operator to type` pins the two literals. Changing either sentence alone reddens the run; making them equal fails as a stale ruling. |
| pdf, doc and rtf on Node | **the port identifies the three kinds and refuses them by name; the reference reads them.** `docread.py` reads PDF through `bantamkit.pdfread` (stdlib, written for this program) and real OLE2 `.doc` and `.rtf` through `/usr/bin/textutil`, a macOS built-in it probes at every call and refuses by name where absent. `docread.ts` has neither: `sniff` still names the container, the size on disk and the suffix disagreement exactly as `_refuse` does, and the remedy clause says which server can read it — `pdf is not readable by the Node server yet (the Python server reads it); see docs/porting.md` and `<doc|rtf> is read through /usr/bin/textutil by the Python server and not by the Node server; see docs/porting.md`. No runtime dependency is allowed into `runtime-ts` (one runtime dep, `package.json`), so the pdf side is a PORT and not an install: **job44 ports `pdfread`** and closes the pdf half of this row; doc/rtf stay refused on Node until a reader that is not a macOS binary exists. Ruled in `tools/conformance/suites/docread.mjs` — `extract: <fixture>: <kind> is RULED` over eight fixtures (`tiny.pdf`, which the reference READS to one row; `doc.pdf`, `sheet.xlsx.pdf`, `named.xlsx`, header-only PDFs both refuse; `real.doc` and `sheet.xls`, OLE2 signatures both refuse; `bad.rtf`, both refuse; `note.rtf`, read by the reference exactly where textutil is) — and, until job50 I5 (2026-09-12) retired `bantamkit_read` from the MCP roster and deleted the six wire sessions built to exercise it, also in `tools/conformance/suites/wire.mjs` as `read-ruled: id 2..7` over the same shapes on the wire plus `read-ruled: the outcome sequence` for the event log — that wire-level pointer has no live case left today; `docread.mjs` above is the only pointer still gating this row. **Every ruling has two companions**: `…: the refusal bit each side is required to carry`, a literal `{python, node}` pair that says which side must refuse (the reference's bit is a function of `textutil_path()`, reported by the reference itself, never assumed), and where both refuse `…: both refuse (the refusal bit, side to side)`, the unruled comparison CLAUDE.md requires. On a host without textutil nothing is skipped: the rulings still differ and the companions still both refuse, and the suite's note prints which host it measured. Teeth demonstrated 2026-08-28: making the ruled cases match reddened all eight as `STALE RULING`. **AMENDED 2026-09-11 (J46-24). THE PROMISE IN THIS ROW WAS NOT KEPT, AND THE COST OF KEEPING IT IS NOW MEASURED.** The sentence above says "**job44 ports `pdfread`**". Job44 (`fix/job44-register-drain`) was the register-drain job; `NODE_REFUSED` in `runtime-ts/src/docread.ts` still contains `'pdf'` and the port still refuses it. The port is still owed — J46-2's AS-6 audit rules `pdfread` **product-and-must-port**, the only one of thirteen unported Python modules that is product. What J46-24 adds is the price, and it is NOT the module's 1402 lines. **Measured with stdlib `trace` over `runtime-py/src/bantamkit/pdfread.py` (1097 executable lines, 184 of them import-time defs and tables, so 913 BODY lines):** the whole two-runtime gate — `tiny.pdf` plus the three header-only PDFs, which is every PDF any suite compares — reaches **398 of 913 body lines (43.6 %)**. `runtime-py/tests/test_pdfread.py` reaches **695 (76.1 %)**. **Twenty-one functions are reached by the differential gate not at all**, and they are not the edges: `parse_cmap` (38 body lines — the `/ToUnicode` reader that IS this module's whole provenance argument), `_do_xobject` (37), `_png_predictor` (33), `_lzw` (30), `_cid_widths` (24), `_runlength` (15), `_flate`'s truncated/raw/leading-junk tolerance cascade (14 of which the gate reaches 0 and pytest 3), `glyph_to_unicode` and the AGL (12), `_parse_hex_string` (10), `_ascii85` (10), `_unvouched_rows` (8), `_tiff_predictor` (8), `_asciihex` (6), and the `PdfText`/`PdfPage` count properties. **`_lzw`'s 30 body lines are reached by NEITHER gate — not the conformance suite and not pytest.** So a port that turns this gate green ports 43.6 % of the module and ships the other 56.4 % as code no differential case can see, which this job has measured nine separate times to be the exact blind spot of a two-runtime suite. `pdfread.py`'s own docstring sets the standard the port would be breaking: "any decryption code here would be unmeasured code, which this program does not ship". **The extractor is not the hard part, and that is measured too.** Every CPython facility `pdfread` leans on has a Node equivalent, probed on this machine 2026-09-11 rather than assumed: `zlib.decompressobj().decompress` on a truncated stream ↔ `zlib.inflateSync(buf, {finishFlush: Z_SYNC_FLUSH})` (both recover `hello world hello world` from a 4-byte-short deflate; plain `inflateSync` throws `Z_BUF_ERROR`, which is why the option is load-bearing); `unicodedata.category` ∈ {Cc, Cf, Cn, Co, Cs} ↔ the single regex `/\p{C}/u` (verified true for U+0081/U+200D/U+E000/U+0378/lone surrogate and false for `A`); `cp1252`/`mac_roman` ↔ `TextDecoder('windows-1252')`/`TextDecoder('macintosh')`, which CONVERGE with CPython despite disagreeing — CPython raises `UnicodeDecodeError` on the five unmapped cp1252 bytes (0x81, 0x8D, 0x8F, 0x90, 0x9D) and skips them, WHATWG decodes them to the matching C1 control and `_vouchable` then drops them as `Cc`, so both sides omit the same five codes; `utf-16-be` ↔ `TextDecoder('utf-16be')`; `base64.a85decode` and bytes-mode `re` have no builtin, and are a hand-rolled decoder and the latin-1 1-byte-1-char string idiom respectively. **The one divergence no conformance case can pin is UCD SKEW.** `_vouchable` drops `Cn` (unassigned), and `Cn` is a function of the Unicode version each runtime ships: this machine measures CPython 3.12.13 at `unicodedata.unidata_version` **15.0.0** and Node v25.2.1 at `process.versions.unicode` **16.0**. A codepoint assigned in Unicode 16 but not 15 is dropped-and-counted by the reference and emitted by the port, and that difference moves with the installed interpreter and runtime rather than with either codebase — so it is a divergence a ruling would have to describe rather than pin. **Therefore the port is its own job, registered in `.shiftwork/backlog.md` (2026-09-11), and its cost is dominated by FIXTURES, not by arithmetic:** the ~25-line `tinyPdf` generator in `tools/conformance/suites/docread.mjs` is what the SIMPLEST possible PDF costs, and byte-exact fixtures reaching CMaps, CID fonts, LZW, both predictors, XObjects, ASCII85 and the flate tolerance cascade do not exist and cannot be borrowed. **What J46-24 DID land here is a hole in this row's own evidence.** The row says every ruling has two companions; `tiny.pdf` — the sharpest ruling in the file, the one PDF the reference READS — had the ruling and the refusal-bit literal `{python: false, node: true}`, and NOTHING pinning what the reference read. MEASURED by mutation 2026-09-11: truncating every row by one character in `pdfread._rows_from_runs` moved `tiny.pdf` to `Hello conformanc` and `node tools/conformance/run.mjs --suite docread` still answered **1169 cases, 0 failures** — the only thing that moved was a printed note, and a note is not a case. A ruling proves the two sides still DIFFER; it never proves the READING side still reads what it read. Closed by giving `tiny.pdf` the `reads`/`sentence` pair the bzip2/lzma entries already had, which the existing companion branch then emits unchanged: ``extract: tiny.pdf: the reference reads the row as measured (`Hello conformance`)`` and `extract: tiny.pdf: the port refuses in the sentence the ruling quotes`. **Suite 1169 → 1171 cases, 16 ruled-different, 0 failures. Teeth demonstrated BOTH ways 2026-09-11:** the row-truncating mutation now reddens the first case by name, and dropping `'pdf'` from `NODE_REFUSED` in the built `runtime-ts/dist/docread.js` reddens the second; both probes were reverted and the suite is green. |
| utf-7 on Node | **the two runtimes decode a MIME text part through two different codec registries, and only one of them has utf-7.** `docread.py` decodes a `text/*` part by its declared `charset` through CPython's codec registry, which has `utf-7`, so a part declaring `charset=utf-7` with `caf+AOk- done` in it reads as `café done`. `docread.ts` decodes through the WHATWG Encoding Standard's `TextDecoder`, whose label table deliberately has no utf-7 (the standard dropped it as a security hazard), so the label is unrecognised, the fallback is UTF-8, and the same bytes read as `caf+AOk- done` — one row on both sides, one token apart. Both sides READ the file; neither refuses. The port DOES now carry CPython's single-byte codec tables — `runtime-ts/src/charsets.ts`, generated by `runtime-ts/scripts/charsets-table.py` from the interpreter's own `encodings` package (79 single-byte codecs, 326 aliases, 121 modules at CPython 3.12.13 — **AMENDED 2026-09-04: 72 single-byte codecs.** Review round 4's H1 (`666f14f`) found the generator judging statelessness with a six-lead-byte probe containing neither ESC (`0x1b`) nor `~` (`0x7e`), so SEVEN stateful modules — `hz` and the six `iso2022_jp*` — had been written out with a 256-character byte table they cannot have. The generator now sweeps all 65,536 ordered pairs and refuses all seven; 326 aliases and 121 modules are unchanged) and pinned against the live registry by the `charsets` conformance suite (`src/charsets.ts is what scripts/charsets-table.py writes for the live registry`, plus all 256 bytes of every codec decoded by the reference and compared to the table) — so the earlier reasoning here, that a second registry would be a maintenance burden, no longer applies to byte tables. It still applies to utf-7: utf-7 is a stateful modified-base64 transform, not a byte table, the generator cannot write it out, and no decoder for it is written, so the label still falls to UTF-8 on the port. Ruled in `tools/conformance/suites/docread.mjs`: `extract: utf7.eml: utf7 is RULED` over the whole answer, with `…: the refusal bit each side is required to carry` pinning `{python: false, node: false}`, `…: both read (the refusal bit, side to side)` as the unruled companion, and `…: the same shape around the ruled row` comparing kind, part names, row counts and omissions unruled so the ruling cannot hide a second difference. Teeth demonstrated 2026-08-28: forcing the ruled case to match reddened it as `STALE RULING` (`node tools/conformance/run.mjs --suite docread`: 774 cases, 1 failure), then the probe was removed. |
| `hz` and `iso-2022-kr` on Node | **the same divergence as the row above, under two more names — two stateful escape codecs CPython has and the WHATWG Encoding Standard does not.** `docread.py` decodes a `text/*` part by its declared `charset` through CPython's codec registry, which has `hz` and `iso2022_kr`; `docread.ts` decodes through `TextDecoder`, whose label table has neither, so the label is unrecognised, the fallback is UTF-8, and the escape machinery comes back as literal text. MEASURED 2026-09-04 on the two fixtures built in `tools/conformance/suites/docread.mjs`: `hz.eml`'s `~{:O::~}` reads `合汉` on the reference and `~{:O::~}` here; `iso2022kr.eml`'s `ESC $ ) C SO = " SI` reads `숱` there and `\x1b$)C\x0e="\x0f` here. Both sides READ the file to one row; neither refuses. THIS IS NOT NEW BEHAVIOUR and it is not a regression: `decodeCharset`'s own docstring already said these labels fall to UTF-8. What was missing was the PRICE — review round 4 found it with no divergence row, no `ruling:` case and no companion, which is a CLAUDE.md violation whatever the behaviour is. The cause is the same as `utf-7 on Node`: each is a stateful escape transform, not a byte table, so `runtime-ts/src/charsets.ts` cannot carry it. H1 (`666f14f`) is what made this visible — the generator's statelessness probe used to be six hand-picked lead bytes containing neither ESC (`0x1b`) nor `~` (`0x7e`), so seven stateful modules were written out with a 256-character byte table they cannot have; the full 65,536-pair sweep refuses all seven (79 -> 72 tables) and the labels now reach the decoder chosen by measurement over 8,829 inputs against CPython (ICU 5,664 correct, byte table 5,021, utf-8 4,339). `hz`, `iso2022_kr` and `utf_7` score 0 % through WHATWG, which is why six labels route to ICU and not nine. Not ported, because lifting it means three modified-escape decoders written by hand under the no-dependency rule, for shapes nothing in the measured corpora (`docs/eval-data/`) uses. Ruled in `tools/conformance/suites/docread.mjs`: `extract: hz.eml: statefulCjk is RULED` and `extract: iso2022kr.eml: statefulCjk is RULED` over the whole answer, each with `…: the refusal bit each side is required to carry` pinning `{python: false, node: false}`, `…: both read (the refusal bit, side to side)` as the unruled companion — which is the case that catches one side starting to REFUSE, something a ruling can never do — and `…: the same shape around the ruled row` comparing kind, part names, row counts and omissions unruled. Teeth demonstrated 2026-09-04: before the rulings existed the same two fixtures gave `FAIL: 1050 cases, 4 failures`; with them, `PASS: 1048 cases, 15 ruled-different, 0 failures`. |
| bzip2 and lzma zip members on Node | **the reference reads a zip member stored with compression method 12 (bzip2) or 14 (lzma); the port refuses it by member, method number and name.** CPython's `zipfile` links the `bz2` and `lzma` modules and decompresses both methods transparently, so a `.docx` whose `word/document.xml` was written with `ZIP_BZIP2` or `ZIP_LZMA` reads to its row (`hello` in the fixture). `docread.ts` decompresses through `node:zlib`, which has deflate and nothing else the zip format names, and `runtime-ts` may carry no runtime dependency beyond the one in `package.json` — so the port refuses with `<name> is a zip but its <member> uses compression method 12 (bzip2), which the Node server cannot decompress (the Python server reads it); see docs/porting.md` (14 (lzma) for the other). **AMENDED 2026-09-04 (review round 4, M1): this row rules the REQUIRED member only.** An OPTIONAL member stored with the same method is now PARITY, not a ruling: `isUnreadableOptional` omitted `DocumentReadError`, so a `.xlsx` whose `xl/styles.xml` was written with `ZIP_BZIP2` made the port refuse the whole document the reference reads. Fixed in `aa49760` with the fixture `bzip2-optional-styles.xlsx` (built in `runtime-ts/test/docread-fixtures.mjs`), compared UNRULED in the `docread` suite: a member this port cannot decompress costs that MEMBER and never the document, and both sides answer the same bytes. **Residual, unfixed — MEASURED AND FIXTURED 2026-09-06 (job44 U17), and it now has a row of its own:** a bzip2 `xl/styles.xml` that carries DATE FORMATS still diverges — the reference decompresses it and emits the `number-format` omission, and this port cannot produce it. Same cause as this row, and still unfixed for the same reason; what changed is that it is no longer a prediction. The fixture the residual said did not exist is `bzip2-date-styles.xlsx`, with the control `deflate-date-styles.xlsx` beside it, and the ruling is the row below, "a bzip2 `xl/styles.xml` that carries date formats". Was roadmap row 8 (t). Method 9 (deflate64), the encrypted flag and a damaged member are NOT rows here — since round 3 (H1/H2) each has its own sentence and BOTH sides print it, pinned unruled in `docread` (the checked-in `compression-method-9.docx`, `encrypted-member.docx`, `encrypted-mimetype.odt`, `bad-crc.docx`, `corrupt-deflate.docx`) and, until job50 I5 (2026-09-12) deleted the session, in `wire`'s `read-round3` session as literals — that wire-level pointer is dead today; `docread`'s checked-in fixtures are the only pointer left: `<name> is a zip but its <member> uses compression method 9, which this reader cannot decompress` (method 9 used to print the encrypted sentence, because `zipfile` raises `NotImplementedError` for both; the reference now reads the method off the member's header first); `<name> is a zip but its <member> is encrypted, so this reader cannot read it without a password`; and `<name> is a zip but its <member> is damaged (<cause>), so this reader cannot read it`, where the parenthesised cause is CPython's own words — `Bad CRC-32 for file 'word/document.xml'` from `zipfile`, `Error -3 while decompressing data: invalid block type` from `zlib` — which the port reproduces byte for byte **for every cause zlib names** (`docread.ts` `isDamagedMember`, the `BadZipFile` and `zlib.error` sentences). **AMENDED 2026-09-04 (review round 4, L3): the unqualified "byte for byte" was wider than what is measured.** The port rebuilds the sentence by hand as `` `Error ${e.errno} while decompressing data: ${e.message}` ``, which is exact for the shape a fixture exercises (`corrupt-deflate.docx`, zlib return code -3 with `msg = "invalid block type"`). CPython's `zlib_error` formats `"Error %d %s"` with NO cause clause when `zst.msg` is `NULL`, and substitutes its own fixed strings (`incomplete or truncated stream`, `inconsistent stream state`, `invalid input data`) before that; `node:zlib`'s message in those cases is its own and the two sentences would differ. No input that makes zlib return an error with a null `msg` has been constructed, so this is a GAP, honestly unmeasured, and not a measured divergence — which is exactly why the claim is narrowed to the class a fixture holds rather than left standing over a class nobody has reached. Registered as roadmap row 8 (s). Ruled in `tools/conformance/suites/docread.mjs` (`extract: bzip2.docx: bzip2 is RULED`, `extract: lzma.docx: lzma is RULED`, each with `…: the refusal bit each side is required to carry` as the literal `{python: false, node: true}`, `…: the reference reads the row as measured` pinning `hello` — generated from the reference's own run, not typed — and `…: the port refuses in the sentence the ruling quotes` pinning the port's sentence with its method number) and, until job50 I5 (2026-09-12) deleted it, in `tools/conformance/suites/wire.mjs`'s `read-round2` session (ids 7 and 8 ruled, the same three companions on the wire, and `…: the reference's manifest names one part of one row`) — that wire-level pointer has no live case left; `docread.mjs` is the only one that still gates this row. Neither side refuses on BOTH, so there is no side-to-side refusal-bit companion; the literal pair is what says which side must read. Teeth demonstrated 2026-08-29: forcing the ruled case to match reddened it as `STALE RULING` (`node tools/conformance/run.mjs --suite docread`), then the probe was removed. Lifting it means a bzip2 and an lzma decoder written for this program under the no-dependency rule; nothing in the measured corpora (`docs/eval-data/`) uses either method, so it waits. |
| a bzip2 `xl/styles.xml` that carries date formats | **neither runtime refuses and both read the same row; only the reference can say what the number IS.** The row above rules the REQUIRED member and records, since round 4 (M1), that an OPTIONAL member stored with method 12 costs that member and not the document — `bzip2-optional-styles.xlsx` pins that as parity. What M1 left standing, and named as a residual with no fixture, is that the two runtimes do not lose the same AMOUNT when the member carries something. `bzip2-date-styles.xlsx` (built in `runtime-ts/test/docread-fixtures.mjs`) is that fixture: an `.xlsx` whose `xl/styles.xml` declares `yyyy-mm-dd` at the `cellXfs` index cell A1 uses, and whose A1 is the bare number `46235`. `docread.py` decompresses the member through `bz2`, resolves the style and emits `Omission(subject='number-format', count=1, where=('A',), what='yyyy-mm-dd')`; `docread.ts`'s `dateFormats` catches the method-12 refusal as an unreadable OPTIONAL member (`isUnreadableOptional`, which is what M1 made it do) and answers no formats, so the part's omission list is empty. Everything else matches: kind `xlsx`, one part `Sales`, one row `46235\tok`, `text_bytes` 8, no document-level omission, no refusal on either side. In an `.xlsx` the number format is the ONLY thing separating a serial date from a plain number, so the port hands back a workbook whose `46235` it cannot explain. Same cause and same remedy as the row above — `node:zlib` has deflate and nothing else the zip format names, and runtime-ts may carry no new runtime dependency, so lifting this means the same bzip2 decoder that row waits on. Was roadmap row 8 (t); MEASURED 2026-09-06 (job44 U17), which is what turned the register's prediction into a fixture. Ruled in `tools/conformance/suites/docread.mjs` as `extract: bzip2-date-styles.xlsx: bzip2Styles is RULED`, with four companions, three of them NON-ruled: `…: the refusal bit each side is required to carry` pinning the literal `{python: false, node: false}`, `…: both read (the refusal bit, side to side)`, `…: the same shape around the ruled row (kind, parts, row counts, omissions)`, and — because the divergence here is a missing OMISSION rather than a differing row, which the shape case does not reach — `…: the reference discloses what the unreachable member carries, as measured` and `…: the port discloses nothing, because the member holding it is method 12`, each pinning one side's omission list as a literal. **The ruling comes with a CONTROL, which no other row here has**, and it is the reason this row can be believed: `deflate-date-styles.xlsx` is the same workbook with the same `xl/styles.xml` CONTENT — same CRC `0x7e197e5f`, same 225 uncompressed bytes, one header field apart — behind method 8, and `the bzip2-styles ruling has a control: the same styles behind method 8 make BOTH sides disclose` pins that both runtimes emit the omission on it. Without that case a reader that stopped resolving date styles ENTIRELY would leave both sides silent, the ruled comparison would start matching and be reported as a stale ruling, and the two disclosure companions would both read `[]` — a green suite over an input that had lost its teeth, which is the exact shape three parity bugs already survived in this repo. **Teeth demonstrated 2026-09-06**, by making that very regression: the styled cell's `s="1"` was changed to `s="0"` in `runtime-ts/test/docread-fixtures.mjs` — the M1 blind spot, deliberately re-created — and `node tools/conformance/run.mjs --suite docread` reddened three cases by name, `extract: bzip2-date-styles.xlsx: bzip2Styles is RULED — STALE RULING: the case no longer differs`, `…: the reference discloses what the unreachable member carries, as measured`, and the control, then the probe was reverted and the suite is green (1,078 cases, 16 ruled-different, 0 failures at the time of the run; the case count moves with the repo). The unit layer has the same teeth: treating `bzip2-date-styles.xlsx` as parity in `runtime-ts/test/docread.test.mjs`'s `DIVERGENT` map fails 2 of its 50 tests on the missing omission. |
| RFC 2231 charset continuations on Node | **the two runtimes reassemble a `Content-Type` parameter differently, and only one of them reassembles it at all.** RFC 2231 lets a parameter arrive in numbered pieces (`charset*0=utf-8; charset*1=…`) or as an encoded value (`charset*=utf-8''…`). `docread.py` reads a MIME part's charset through `email.policy.default`'s header parser, which joins the pieces with semantics that are its own: `charset*1=x; charset*0=y` joins to `yx`, and a plain duplicate `charset=utf-8` on the same header LOSES to the continuation. So `rfc2231-charset.eml` (checked in under `runtime-py/tests/data/docread/`) decodes as UTF-8 and reads `café au lait`. `docread.ts` reads the plain `charset=` parameter only, finds no usable label, and decodes the same bytes through UTF-8 with replacement: `caf� au lait`. Both sides READ the file to one row of one part; the row differs by two bytes' worth of replacement characters (the reference's row is 12 UTF-8 bytes, the port's 14), and the `text_bytes` figure moves with it. Not ported, because porting it means carrying `email`'s parameter reassembly — its piece ordering, its duplicate rule, its language tag and its percent-decoding — for one row on one shape, far over the port budget. Ruled in `tools/conformance/suites/docread.mjs`: `extract: rfc2231-charset.eml: rfc2231 is RULED` over the whole answer, with `…: the refusal bit each side is required to carry` pinning `{python: false, node: false}`, `…: both read (the refusal bit, side to side)` as the unruled companion, and `…: the same shape around the ruled row` comparing kind, part names, row counts and omissions unruled. On the wire, until job50 I5 (2026-09-12) deleted the session, `read-round2: id 10` in `tools/conformance/suites/wire.mjs` was the ruling, with the same two companions and `…: the same manifest around the ruled row`, which blanked the row and its byte count and compared the rest of the manifest byte for byte — that wire-level pointer has no live case left today; `docread.mjs` above is the only one still gating this row. Teeth demonstrated 2026-08-29: forcing the ruled case to match reddened it as `STALE RULING`, then the probe was removed. |
| `<!ATTLIST>` defaults on Node | **the reference's `expat` applies an internal DTD's `<!ATTLIST>` default attribute values; the port's internal-subset walk skips the declaration.** `attlist.xlsx` (built in `tools/conformance/suites/docread.mjs`) is a sheet whose XML opens `<!DOCTYPE worksheet [<!ATTLIST c t CDATA "s">]>` and holds a `<c r="A1"><v>0</v></c>` written WITHOUT a `t` attribute. `docread.py` reads it through `xml.etree`'s expat, which supplies the default `t="s"`, so the cell is a shared-string index and reads `SHARED`; `docread.ts`'s `parseDoctype` reads `<!ENTITY>` declarations (pinned unruled by `internal-dtd-entity.docx`) and skips `<!ATTLIST>` over its quoted strings, so the cell is a number and reads `0`. Both sides READ the file to one row of one part; the row differs by that one cell (`SHARED\tplain` against `0\tplain`, measured 2026-08-29 on both). Not ported, because applying defaults means carrying expat's attribute-declaration model (per-element, per-attribute, `#IMPLIED`/`#REQUIRED`/`#FIXED`, the CDATA/NMTOKEN normalisation) into a walk that exists to read four element names, and no OOXML writer emits an internal DTD at all — this was a "gap the differential cannot see" until H3 built the fixture that shows it. Ruled in `tools/conformance/suites/docread.mjs`: `extract: attlist.xlsx: attlist is RULED` over the whole answer, with `…: the refusal bit each side is required to carry` pinning `{python: false, node: false}`, `…: both read (the refusal bit, side to side)` as the unruled companion, and `…: the same shape around the ruled row` comparing kind, part names, row counts and omissions unruled. Teeth demonstrated 2026-08-29: removing the `<!DOCTYPE>` from the fixture made the two rows match and reddened the case as `STALE RULING` (`node tools/conformance/run.mjs --suite docread`: 983 cases, 1 failure), then the fixture was restored. |
| `str.isalpha()` against `\p{L}` in `skillaudit` | **the two runtimes read two different Unicode databases, and they are compiled against two different revisions of the standard.** `skillaudit.py` asks CPython's own tables through `str.isalpha()` and `str.isalnum()`; `skillaudit.ts` asks V8/ICU through `/\p{L}/u` and `/[\p{L}\p{N}]/u`. MEASURED 2026-09-05 by brute force over all 1,112,064 code points (`0x0000`-`0x10FFFF` less the surrogate range) on this machine: CPython 3.12.13 carries `unicodedata.unidata_version` 15.0.0 and Node 25.2.1 carries `process.versions.unicode` 16.0 (ICU 77.1); **4,924 code points disagree for alpha and 5,004 for alnum, and every disagreement is ONE-DIRECTIONAL** — the port answers letter where the reference does not, never the reverse, because 16.0 only added characters to the letter categories. The first is U+1C89 (CYRILLIC CAPITAL LETTER TJE), which is `Cn`, unassigned, in 15.0.0. It reaches TWO sites and it moves them in OPPOSITE directions. In `_is_letter` / `isLetter` it is the apostrophe guard, so `\u1C89'race condition'\u1C89` is `['race condition']` on the reference (the flank is not a letter, so the quote delimits) and `[]` on the port — **the reference emits a `shared-trigger-phrase` the port does not**. In `_has_content` / `hasContent` it is the punctuation filter, so `"\u1C89"` is `[]` on the reference (no alnum in the phrase) and `['\u1C89']` here — the PORT keeps a phrase the reference drops. NEITHER SIDE IS WRONG: each is telling the truth about the Unicode revision it was built against, and the same reference on a CPython built against 16.0 would answer what the port answers today. Not lifted, because the fix is one of two things this program will not do: vendor a 136,104-entry category table into `runtime-ts` and re-vendor it on every CPython upgrade (the shape `runtime-ts/src/charsets.ts` takes for single-byte codecs, which is 79 tables of 256 entries, three orders of magnitude smaller and PINNED against the live registry by a suite — nothing pins a Unicode category table against a CPython that has not shipped yet), or make the reference stop asking CPython, which would make it disagree with the host it is auditing. No `SKILL.md` in either measured corpus contains a code point from the disagreeing set. Ruled in `tools/conformance/suites/skillaudit.mjs`: `phrases: the apostrophe guard over U+1C89: the Unicode version is RULED` and `phrases: the punctuation filter over U+1C89: the Unicode version is RULED`, each with `…: the answer each side is required to carry` as a LITERAL companion pinning `{python: ['race condition'], node: []}` and `{python: [], node: ['\u1C89']}` — the case that fails on its own line if CPython upgrades or ICU downgrades, rather than behind "they still differ". **There is no refusal-bit companion, and this is the judgement CLAUDE.md asks for: the difference is not refusal-shaped.** Neither runtime refuses this input; both return a list of phrases, and they differ in the CONTENT of that list. A refusal bit compared side to side would be `{python: false, node: false}` on every input this module has ever been given, ruled or not, which is a case that can never go red and is exactly the vacuous gate the rule exists to prevent. What the rule is protecting against — a ruling staying green while the port quietly stops answering at all — is instead covered by FOUR non-ruled ascii twins, two per ruled site: the same constructions with `A` in place of U+1C89, in both polarities. One of each pair is where the shared rule SUPPRESSES the phrase (both sides answer `[]`, which says the rule is still there) and one is where it KEEPS it (both answer a non-empty list, which is the case a reader that finds nothing fails). Each also carries a both-sides literal, so a twin cannot pass because both runtimes broke the same way. The second of each pair is not decoration: MEASURED 2026-09-05 by making `phrases` return `[]` for every input, the punctuation-filter ruling self-detects — it goes `STALE RULING`, because both sides then answer `[]` — and the apostrophe-guard ruling does NOT, because the reference's answer there is the non-empty one; the guard's `guard does not fire` twin is the only case in the suite that catches it, and the first draft of this row had only the vacuous half of the pair. Teeth demonstrated the same day: replacing U+1C89 with `A` in the two ruled texts reddened both as `STALE RULING` (4 differed), and killing `phrases` reddened 36 cases including two twins while one ruling stayed green; both probes were removed. |
| `--install`'s recorded command | **each runtime registers ITSELF by absolute path, and that is the point.** `--install <host>` writes an MCP entry into a host's configuration. Since J51-4 BOTH runtimes record an absolute command: `runtime-ts` records `<absolute node> <absolute dist/cli.js>` — `process.execPath` and the `cli.js` of the install a host should launch — and `runtime-py` records its own console script by absolute path (falling back to `<absolute python> -m bantamkit.mcpserver` when invoked that way). What still differs is the interpreter and the entry point, and it always will: making them agree would mean one distribution sending a host to look for the other's runtime — a pure-npm install has no Python, and a `pip install` has no npm. **Why the port stopped recording `npx -y bantamkit-mcp`, which this row used to say it did: a measurement.** The job51 prep probe (2026-09-14/15, macOS, node v25.2.1, npm 11.6.2, the published `bantamkit-mcp@0.33.0`, the network cut by pointing `npm_config_proxy`/`npm_config_https_proxy` at a closed port so the cache key is unchanged, host PATH `/usr/bin:/bin:/usr/sbin:/sbin`): with a WARM cache, `npx -y bantamkit-mcp@0.33.0`, `npx -y bantamkit-mcp` and `npx -y bantamkit-mcp@latest` each hung silently past 45 s with 0 bytes on stdout — a host reports that as a handshake timeout. The same package kept by `npm i --prefix <dir>` and launched as `<abs node> <dir>/node_modules/bantamkit-mcp/dist/cli.js` answered `tools/list` with 12 tools in 0.11 s; that prefix's own `.bin/bantamkit-mcp` shim exited 127 (`env: node: No such file or directory`), which is why the recorded command names node itself and not a shim or a bare `node`. The user ruled (2026-09-15) that `--install` makes a one-time kept install and records an absolute command. Everything else about the report and the written file is IDENTICAL: the file, the key (`servers` for VS Code, `mcpServers` for the other three), the entry shape, the backup name, the refusal sentences, and the exit codes. Ruled in `tools/conformance/suites/cli.mjs` as `install-<host>/stdout-command-line`, over three hosts, and **each ruling has a companion**, `…/stdout-everything-else`, comparing every byte of the report the ruling does not cover — so a runtime that changed the file it writes, the key it writes under, or the backup it takes fails while the ruling still "differs". **And since J51-6 a literal**, `install-cursor/PINNED PER SIDE: each runtime records itself by absolute path, against this file`, pins what each line IS (`<PYTHON> -m bantamkit.mcpserver` against `<NODE> <checkout>/runtime-ts/dist/cli.js`), because a port that went back to `npx` would still differ from the reference and leave every ruling green. The idempotent arm (`install-cursor-again`) is deliberately NOT ruled: a second run prints no `command:` line at all, so its whole report is compared as bytes. Attaching a ruling there was tried and the harness reported `STALE RULING: the case no longer differs`, which was right. **AMENDED 2026-09-20 (job62, J62-4/J62-5/J62-8; row written by J62-9): this row now covers `--install-hooks` as well, EXTENDED rather than duplicated, because it is the same genuinely-different-object one surface further out.** `--install-hooks` writes a command a HOST will launch — seven `~/.claude/settings.json` hook entries, ONE command for all seven, because the event arrives on stdin and never in argv — so each runtime again records ITSELF by absolute path. Measured 2026-09-20 in a throwaway `HOME` (both `HOME` and `USERPROFILE` redirected, and the redirect asserted from inside each runtime before a byte was written), `--install-hooks --yes`: the reference records `/Users/…/mise/installs/python/3.12.13/bin/python3.12 -m bantamkit.mcpserver --hook` and the port `/Users/…/mise/installs/node/25.2.1/bin/node /Users/…/runtime-ts/dist/cli.js --hook`. A pure-npm install has no Python in it and CPython installs no `cli.js`, which is the same reason as above. It is a SPELLING and not a refusal — both sides write, both write the same seven events in the same order, with the same matchers and the same `timeout: 10` — so it owes no refusal-bit companion; what it gets instead is the WHOLE written document compared unruled, which measured differs in exactly the seven `command` strings and nothing else. Ruled in `tools/conformance/suites/hooks.mjs` as `install-hooks: the recorded command — each runtime registers ITSELF, by absolute path`; beside it unruled, `install-hooks: PINNED PER SIDE: each runtime names its own interpreter and entry point` pins `{python: "<PYTHON> -m bantamkit.mcpserver --hook", node: "<NODE> <CLI> --hook"}`, because a port that went back to `npx -y bantamkit-mcp` would still DIFFER from the reference and leave the ruling green; `install-hooks: the written settings.json, byte for byte, with the ruled command masked` compares every other byte of the document; and `install-hooks-no-tty` pins the one state in which neither side writes at all — the same three-line refusal, on stderr, exit 2, nothing written, per side as well as side to side. |
| `--install` from an `npx` cache: the kept install (J51-4) | **the port records a KEPT install it makes itself, and the reference has no such branch because it never derives `ephemeral`.** When the port's `currentInstall()` says `ephemeral` — it is running out of an `npx` cache, a directory npm may discard and whose launch command hangs offline (row above) — `--install` does not record the cache. It records `<absolute node> <homedir>/.bantamkit/mcp/node_modules/bantamkit-mcp/dist/cli.js`, and if that kept install does not already report this version or a newer one it first runs `npm install --prefix <homedir>/.bantamkit/mcp bantamkit-mcp@<this version>` once; an npm failure, or no `cli.js` afterwards, is a refusal raised before any host file is read, so no backup is taken. A second `--install` for another host finds the kept install current and runs nothing, offline. **Since J51-9a a NEWER kept install is left as it is too** (review F1): the operator ran `--update`, then `--install` from a stale `npx` cache, and installing the cache's older version over the kept install would move every host that launches it backwards. The versions are ordered by `compareVersions` in `runtime-ts/src/selfupdate.ts` — the `--update` comparator, numeric per dotted component, so `0.10.0` is newer than `0.9.0` — and a component that is not all digits sorts after every number, so a kept version that cannot be read as numbers counts as newer and is never overwritten; a blank version is no version, and npm runs as it does when the manifest is missing. The reference cannot reach this: `pipx run` and `uvx` leave no record of an ephemeral environment, so `runtime-py` never answers `ephemeral` (the AS-7a row below) and records its console script as it does anywhere — making the reference guess an ephemeral environment from cache directory names so it could mirror this branch would be the guess AS-7a refuses. Ruled in `tools/conformance/suites/cli.mjs` as `install-cursor-from-an-npx-cache-with-a-kept-install/stdout-command-line` (and, with the kept install seeded NEWER than this build — a version the harness searches for so that it sorts OLDER as a string — `install-cursor-from-an-npx-cache-with-a-newer-kept-install/stdout-command-line`, carrying the same unruled companions plus `…/PINNED PER SIDE: the kept install is newer by number, older as a string, and still at that version`), driven as a REAL PROCESS: the suite lays a copy of this build out as an `npx` cache (`_npx` marker, npm's hidden lockfile with an https `resolved`) and seeds BOTH sides' HOME with a kept install at this version, so npm never runs (the port side also runs with `npm_config_offline=true`). Beside it, unruled: `…/stdout-everything-else` (every other byte of the report), `…/stderr` and `…/exit`; `…/PINNED PER SIDE: the port records the KEPT install, the reference itself, against this file`; and `…/PINNED PER SIDE: the kept install was used as it was — npm never ran — and the host file was written`, which reads back a marker a reinstall would overwrite. **AMENDED J54-3 (2026-09-18): the branch that RUNS npm IS driven by the gate now, and it carries one more port-only behaviour — the kept install's `~/.bantamkit` gets the self-ignoring `.gitignore` every other `.bantamkit` bantamkit creates gets.** npm makes a missing `--prefix` itself, so that `npm install --prefix <homedir>/.bantamkit/mcp` is what brings `<homedir>/.bantamkit` into existence: measured on the machine this was found on, 28 MB of install tree plus the whole memory store, untracked, in a `$HOME` that is a git repository. So the port calls `ensureBantamkitGitignore` on it with `created` answered BEFORE npm runs and AFTER the two `InstallError` refusals, under the same user ruling #2 as the other creators — a `~/.bantamkit` that was already there (an older kept install, a memory store, an ignore file the operator deleted on purpose) is left exactly as it is. The reference has no counterpart because it has no kept install: it never derives `ephemeral` (the AS-7a row) and never creates a `~/.bantamkit` at all, which is the asymmetry and not a gap. Driven as a REAL PROCESS by `install-cursor-from-an-npx-cache-with-no-kept-install` in `tools/conformance/suites/cli.mjs`, from the same npx-cache copy with NEITHER side's HOME seeded and `npm` STUBBED on the port's PATH (a shell script that makes the tree npm would make and asks no network; it probes itself and the arm is omitted with a note where a bare `npm` cannot resolve to it, e.g. Windows). Ruled there by the same command-line ruling as the row above, and — **because a ruling only proves the two sides still DIFFER** — beside it unruled: `…/precondition: the stubbed npm ran and left the kept install it makes`, and `…/PINNED PER SIDE: a ~/.bantamkit the installer made is ignored, and the reference makes none`, which pins `{python: {bantamkitDir: false, gitignore: <ABSENT>}, node: {bantamkitDir: true, gitignore: <the literal>}}` — red if the port stops writing the file, and red if the reference starts scattering a `.bantamkit` into HOME. The in-process seam version of the same question stays in `runtime-ts/test/hostinstall.test.mjs` through its injectable installer. |
| `--install` on an install shape it cannot derive (J51-4) | **the port REFUSES and the reference writes — a refusal on one side, with the refusal bit pinned per side.** Which copy a host should launch depends on the port's install shape (an `npx` cache means the kept install), so where `currentInstall()` throws `Undetermined` — a `git+https` origin in the lockfile, which is neither a package index nor a path — the port prints `error: --install could not tell how this install was made, so it will not guess which copy a host should launch: <reason>`, exits 1, and has not read the host file. The reference's `--install` never consults its shape: its console script is where it is running whatever its origin, so there is nothing to guess and it writes the entry. Forcing the port to fall back to its own `cli.js` would record a path inside an install it cannot identify — possibly a cache — which is the guess; forcing the reference to refuse would take a working registration away from a `pip install git+https://…` user for a question the reference does not have. Ruled in `tools/conformance/suites/cli.mjs` as `install-cursor-from-an-install-of-undeterminable-shape/stderr`, driven as a real process from the same npx-cache copy with a `git+https` `resolved`. **Because a ruling only proves the two still DIFFER**, `…/PINNED PER SIDE: the refusal bit, and whether the host file was written` pins `{python: {refused: false, wroteConfig: true}, node: {refused: true, wroteConfig: false}}` unruled, and `…/PINNED PER SIDE: what each process printed, against this file` pins the port's sentence prefix, its one line naming the origin, empty stdout and exit 1, and the reference's exit 0 and recorded command. A side-to-side refusal-bit case is not possible here: the bits differ by the ruling, so it would be red forever. |
| `--install`'s JSON parse error | **RETIRED (job65 / J65-18, #118) — the sentence is byte-identical now.** The row used to read: both refuse; the reason after the colon is each parser's own — CPython's `Expecting value (line 1, column 1)` against V8's `Unexpected token …` — because `JSON.parse` exposes no line and column. That premise ended when `--install` on the port stopped reading the host file through `JSON.parse` at all: it parses with `pyjson.parseJson`, the CPython-decoder port the `validate` suite pins message by message, which it needed for #118 (big integers, `1.0`, key order and `1e400` survive the parse as the reference sees them). The refusal reads `<path> is not valid JSON, so this refuses to touch it: <msg> (line L, column C)` on both sides, `install-broken-json/stderr` in `tools/conformance/suites/cli.mjs` is compared as BYTES, and the refusal bit is pinned per side against a literal in `tools/conformance/suites/install.mjs` (`install-broken-json: CPython's message, line and column, from both, against a literal`). The file is still never overwritten. |
| the ten CJK codecs on Node | **the reference decodes them through CPython's own multi-byte tables and the port through ICU's, and (as measured 2026-09-06) four of the ten labels are not even the same codec on the WHATWG side** (AMENDED 2026-11-06, #270: now five — `gb2312`, `gbk`, `big5`, `euc-kr`, `shift_jis` — and on Node 20 malformed gbk/gb2312 input now decodes as it already did on Node ≥ 22; see the note at the end of this row). `charsets.ts` carries CPython's SINGLE-byte tables and is pinned against the live registry (the row's whole point, above); `euc_jp`, `euc_kr`, `cp932`, `gb18030`, `gbk`, `shift_jis`, `big5`, `big5hkscs`, `cp949` and `gb2312` are not in that file at all — `docread.ts`'s `MULTI_BYTE_LABELS` sends each to a `TextDecoder`, with CPython's replacement policy layered on top by `decodeMultiByte`. The WHATWG label's table is not the codec's in every cell: `gb2312` is decoded by ICU's **gbk** (SUPERSEDED, #270: gbk and gb2312 are now both decoded as the `gb18030` label), `big5` carries **HKSCS**, `euc-kr` is **cp949**, `shift_jis` is **cp932**. MEASURED 2026-09-06 over 300 seeded byte strings of 2–8 random bytes (the recipe is `tools/conformance/ref/cjk_ref.py`, re-seeded per codec so all ten answer about the SAME inputs), CPython 3.12.13 against Node v25.2.1 / ICU 77.1 — how many of the 300 the two sides answer alike: `euc_kr` 298, `gb18030` 293, `euc_jp` 295, `cp932` 285, `gbk` 277, `shift_jis` 247, `big5hkscs` 211, `big5` 210, `cp949` 205, `gb2312` 141. The port collapses three of the pairs outright: `big5`/`big5hkscs` produce **byte-identical** answers here (one ICU decoder) where the reference's two differ, and so do `euc_kr`/`cp949` and `gbk`/`gb2312` (SUPERSEDED, #270: `gbk`, `gb2312` and `gb18030` now all collapse onto one decoder) — pinned as data, the two `port` digests equal and the two `reference` digests not. **THE COUNTS ARE NOT THE ONES `docs/roadmap-toolbox.md` ROW 8 (o) QUOTES, AND THAT ROW'S NUMBERS DO NOT REPRODUCE.** (o) says "300 random byte strings per codec … (seed 7)" and gives euc_jp 297 / euc_kr 296 / cp932 295 / gb18030 292 / gbk 278 / shift_jis 268 / big5 208 / big5hkscs 205 / cp949 192 / gb2312 141, and the script that produced them was never checked in. Ninety-odd reconstructions of that sentence were run on 2026-09-06 — `randbytes` and `randrange` byte streams, fixed lengths 1 through 32, `randrange`/`randint` length ranges, a corpus shared across codecs and one re-seeded per codec — and not one reproduces the ten together; the row's own profile rules a single corpus out, because it pairs `euc_jp` 297 (a rate only very short inputs reach) with `gb2312` 141 (a rate only longer ones fall to). The recipe now lives in code so the next reader is not in that position. Not lifted, because lifting it means writing CPython's CJK tables into TypeScript the way `charsets.ts` does for single-byte codecs — 79 tables of 256 entries there against tens of thousands of multi-byte mappings here — for a difference that lands on MALFORMED input: every one of the 300 is random bytes, and where the bytes are valid text in the codec both sides agree. Ruled in `tools/conformance/suites/charsets.mjs` as `ruling: cjk <codec>: ICU's table against CPython's over 300 seeded byte strings`, ten of them, **and every one carries FOUR non-ruled companions that are LITERALS in the suite** — `…: how many of the 300 the two sides answer alike` (the count, so `gb2312` moving from 141 to 150 is a failure and not a re-measurement), `…: the reference's own 300 answers, anchored`, `…: the port's own 300 answers, anchored` (two digests, which are what catch a SYMMETRIC regression a ruling structurally cannot see), and `…: the first input the two sides answer differently, both answers spelled out`. A `cjk: the seeded corpus is the same 300 inputs …` case pins the corpus digest, so a CPython whose RNG stream moved is a named failure rather than a silent re-measurement of a different corpus. **Teeth demonstrated 2026-09-06, all four in the run and then removed:** (1) forcing `gb2312`'s port answers to equal the reference's reddened it as `STALE RULING` plus 3 companions (148 cases, 4 failures); (2) editing the pinned `gb2312` count to 150 reddened exactly one case; (3) **the symmetric-regression probe, which is why the digests exist** — appending the same string to BOTH sides' answers for all ten codecs left all 12 rulings GREEN and all ten `matched` counts GREEN, and reddened 30 cases, every one of them an anchor (148 cases, 30 failures). A ruling-only pin would have passed that run. **AMENDED 2026-11-06 (#270):** `runtime-ts/src/docread.ts` `MULTI_BYTE_LABELS` now maps `gbk`, `gb2312` and `gb18030` all to the `gb18030` TextDecoder label, because WHATWG makes `gbk`/`gb2312` labels of the gb18030 decoder and Node 20's own `gbk`/`gb2312` decoders disagreed with Node >= 22. The `gbk` and `gb2312` port digests now equal `gb18030`'s (`3782257c09f83754`, was `7d0fc728ce734f23`); the matched counts above are unchanged (`gbk` 277, `gb2312` 141, `gb18030` 293); five of the ten labels are still not the same codec on the WHATWG side: `gb2312` and `gbk` are decoded as gb18030 (a superset, still not CPython's gb2312/gbk codec), `big5` carries HKSCS, `euc-kr` is cp949, `shift_jis` is cp932. |
| ISO-2022-JP's eight characters on Node | **the same cause under a stateful codec, and unlike the row above this one bites on VALID text.** `docread.ts`'s `ESCAPE_LABELS` sends the six `iso2022_jp*` modules to ICU's `iso-2022-jp` decoder whole (a plain `TextDecoder`, never `decodeMultiByte`, because that walk assumes a byte under 0x80 is its own ASCII character, which is exactly what an escape sequence is not). ICU maps six JIS X 0208 code points the way Windows-31J does where CPython maps them the way JIS X 0208 does, and rejects two controls CPython passes through. MEASURED 2026-09-06 as a **census, not a sample**: every one of the 7,008 characters CPython's `iso2022_jp` round-trips, encoded by the reference and decoded one at a time by both sides. Eight differ, and they are `U+00A2 -> U+FFE0` (CENT SIGN -> FULLWIDTH CENT SIGN), `U+00A3 -> U+FFE1` (POUND SIGN), `U+00AC -> U+FFE2` (NOT SIGN), `U+2016 -> U+2225` (DOUBLE VERTICAL LINE -> PARALLEL TO), `U+2212 -> U+FF0D` (MINUS SIGN -> FULLWIDTH HYPHEN-MINUS), `U+301C -> U+FF5E` (WAVE DASH -> FULLWIDTH TILDE), and `U+000E`/`U+000F` (SHIFT OUT / SHIFT IN) which CPython passes through and ICU answers `U+FFFD` for — a refusal rather than a remapping. **THIS REFUTES THE "EVERY ONE" HALF OF `docs/roadmap-toolbox.md` ROW 8 (o)'s AMENDMENT**, which says the residual is "12 of 900 valid-text inputs, and every one of the 12 is the WAVE DASH". The wave dash is ONE of eight, and it is simply the most-cited member of a well-known family; the register generalised from a sample that happened to contain only it. The sample shape was re-run too (900 seeded strings of 1–8 of those characters, same seed): **7 of 900 differ here, not 12, over five of the eight characters** — the same point from the other side, that a sample cannot settle a claim about WHICH characters. Not lifted, for the reason the row above gives. Ruled in `tools/conformance/suites/charsets.mjs` as `ruling: cjk iso2022_jp: ICU's JIS X 0208 mapping against CPython's, over every character CPython round-trips` and `ruling: cjk iso2022_jp: the same difference in the shape roadmap row 8 (o) sampled`, **with the companion that matters pinning the CHARACTERS and not the count** — `cjk iso2022_jp: WHICH characters the port answers differently, by code point — the case a count cannot be` is the literal map above, beside `…: how many characters the reference round-trips at all` (7,008) and four anchored digests, two per side per corpus. **Teeth demonstrated 2026-09-06:** swapping the pinned `U+301C -> U+FF5E` key for a different character while leaving the NUMBER of differing characters at eight reddened that one case — which is the property the brief asked for, that a count staying 12 while the differing characters change is a gate that missed something. |
| `install_shape: ephemeral` (AS-7a) | **the port answers the word and the reference never does, because only one ecosystem writes the fact down.** npm puts an `_npx` marker into an `npx` cache project's own `package.json`, so an ephemeral environment is a RECORD the port reads; `pipx run` and `uvx` leave no equivalent, and telling one of their environments from an ordinary venv would mean pattern-matching cache directory names — a guess, and this surface does not guess. The word is declared in BOTH vocabularies (`INSTALL_SHAPES`) so a consumer of either runtime handles one set of five rather than two it has to reconcile. **What this row does NOT license:** the shape is the ENVIRONMENT and `install_source` is the ORIGIN, two axes, and the measured incident is both at once — an `npx` cache filled from a tarball that is gone. So the origin survives the environment word: `install_source`, `install_source_exists` and the whole `install-source-missing` sentence are compared UNRULED over the same fixture. Driven both sides 2026-09-11 over one matched install: reference `local-file`, port `ephemeral`, identical origin path, identical condition. `install: an npx cache filled from a tarball is `ephemeral` on the port and `local-file` on the reference` in `tools/conformance/suites/install.mjs`, with `install: the npx cache keeps the origin the environment word did not replace` beside it. |
| an `http(s)` install origin (AS-7a) | **the reference REFUSES it and the port calls it `registry` — a difference in the refusal, not in a sentence.** PEP 610 records an http archive as a direct URL that is not a path, and the reference will not round it to one of five words. On the port the npm registry IS an https URL, and telling a published tarball URL from the configured index would mean knowing which index was configured. Either way the origin is REMOTE, so it can never be the dangling-local-path defect AS-7 exists for, and the route out is a reinstall from a name or from that same URL. Ruled by `install: an http(s) origin is refused by the reference and is `registry` on the port`; **and because a ruling only proves the two still DIFFER, never that either still refuses,** the refusal BIT is pinned per side, unruled, by `install: the three refusal bits against a literal`. The underivable origin the two sides still SHARE is `git+…`, compared unruled over its own fixture. |
| a running file no `package.json` owns (AS-7a) | **the reference answers `checkout` and the port REFUSES — the second refusal difference, and the same companion.** The reference identifies the package from the distributions on `sys.path` and needs no manifest beside the running file, so the absence of any installer record is positive evidence of a checkout. The port has no equivalent index: without a `package.json` above the running file it cannot name the package at all, and `checkout` answered there would be a guess about which package this even is. Ruled by `install: a running file no package.json owns is `checkout` on the reference and refused by the port`, with the refusal bit pinned per side by the same literal case as the row above. |
| the `registry` reason's middle clause (AS-7a) | **one clause, and it names the MECHANISM rather than rewording the finding.** Both sides explain why an ABSENCE is positive evidence of an index install, and the two absences are different files: the reference cites PEP 610 and `direct_url.json`, the port cites npm and `node_modules/.package-lock.json`. Copying the reference sentence verbatim would have a Node server citing PEP 610, which is how `git_commit` diverged on a noun. **What this row does NOT license:** the first clause and the closing sentence are byte-identical and are compared UNRULED by `install: the registry reason opens and closes identically on both sides`. Ruled by `install: the registry reason names PEP 610 on the reference and npm on the port`. |
| `--update`'s upgrade command (AS-7b) | **two registries, two package managers, and the one line that NAMES the command cannot be the same sentence.** `pip install --upgrade bantamkit` on the reference — through `sys.executable -m pip`, never a bare `pip`, because the server may run from a venv whose `pip` is not first on `PATH` and upgrading the wrong environment is a failure that reports success. On the port, `npm install --global bantamkit-mcp@latest` in the global tree and `npm install --prefix <root> bantamkit-mcp@latest` where npm itself wrote the `package.json`, which is a RECORD and not a preference: measured 2026-09-11 with npm 11.6.2, `npm install --prefix <dir> <pkg>` into a directory with no `package.json` beside `node_modules` PRUNES every sibling package (a two-package fixture came back with one), and that is exactly the global tree's shape. A naive `--prefix` port would have deleted the user's other global CLIs. The TEMPLATES around the command — `updating from the package index: {command}` and `the update command exited {code}: {command}` — are byte-identical. Ruled by `update: the upgrade command is pip on the reference and npm on the port` in `tools/conformance/suites/cli.mjs`; beside it, per arm, every line that does NOT name the command is compared as bytes, the report is asserted to still carry exactly one line that does, the refusal bit is compared for all 25 arms, and the two npm commands are pinned PER SIDE because the `--prefix`/`--global` fork exists on one runtime only and no differential can see it. **AMENDED 2026-10-14 (job65, J65-19, #128): both commands now name the version they COMPARED — `pip install --upgrade bantamkit==<latest>` and `npm install --prefix <root> bantamkit-mcp@<latest>` (with `--save-exact` where the prefix manifest pinned exactly, a fork the reference has no counterpart to and which is pinned per side) — never a bare name or `latest` resolved a second time, and both read the install back before printing `updated`: a manifest that does not report the compared version, or none readable, is the byte-identical `NOT_INSTALLED` refusal (`the update command exited 0 but did not install {latest}: {command}` …), exit 1. Measured against 0.35.7: the index stubbed to 9.9.9 and an npm that changed nothing printed `updated bantamkit-mcp from 0.35.7 to 9.9.9.` at exit 0. Driven in-process by the three `behind-but-…` arms (refusal bit, every non-command line, and `update/PINNED PER SIDE: the exit-0-but-not-installed refusal`), and as REAL PROCESSES by `update-registry` / `update-registry-lying-installer` in `cli.mjs`, both runtimes from a registry-shaped copy of this build with the package manager stubbed where each resolves it (`npm` on PATH, a `pip` package on PYTHONPATH): the stub log pins per side what was asked and the exact spec installed, the tree's version afterwards is read back per side, and the command line keeps this row's ruling. The same shape has the article fixed: `an ephemeral install`, never `a ephemeral` (#177), on both. |
| `--update`'s per-shape route sentences (AS-7b) | **the answer to "then how DO I update this?" names a package manager and the thing it updates, so three of the four differ.** `local-file`, `linked` and `checkout`: the reference names pip and a Python tree, the port names npm and a BUILT one — both of its tree rows end *"and rebuild it — dist/ is build output, so a pull alone changes nothing"*, because an editable Python install serves the `.py` files a `git pull` just changed and a Node install serves `dist/`. Copying the reference verbatim would hand a Node operator a remedy that exits 0 having changed nothing (the J46-4 defect). `registry` is absent from the table on BOTH sides on purpose: it is the one shape that has a route through this flag, so a sentence telling its operator to go do it by hand would be unreachable. Everything OUTSIDE the route clause — the program, both version numbers, the shape word and the handover sentence — is byte-identical, and the fifth arm (a shape word the table has never heard of) is identical end to end. Ruled by `update: the local-file, linked and checkout routes name pip and a Python tree on the reference, npm and a BUILT one on the port`; the non-ruled companions beside it compare the NO_ROUTE frame as bytes on all four route arms and the refusal bit on every arm, because a ruling proves the two sides still DIFFER and never that both still refuse. |
| `--update`'s `ephemeral` route (AS-7b) | **a CORRECTION, not a translation, and the one row in this table where the reference is wrong and the port is right.** The reference says an ephemeral environment is discarded and *"the next run fetches {latest} by itself"*, which is true of `pipx run` and `uvx`. It is FALSE of an npx cache: `runtime-ts/README.md#silent-version-float` measured that `npx -y bantamkit-mcp` resolves `latest` ONCE and caches it, so two people with byte-identical config can be running builds resolved weeks apart. The port therefore says the next run serves the same cached version unless the host command line asks for `bantamkit-mcp@latest`. Making the port's row a translation of the reference's would make it false; correcting the reference's row instead would make IT false, because a `pipx run` environment really is discarded. So the two sentences are true of two different caches and the difference is registered rather than resolved. Filed separately from the row above so that a future PEP-440-shaped fix to the other three routes cannot quietly carry this one along with it. Ruled by `update: the ephemeral route is a correction — the reference promises a fresh resolve an npx cache does not do`; the NO_ROUTE frame around it is compared as bytes and the refusal bit unruled, beside it. **EXTENDED J51-5 (`01cee52`): from an `npx` cache WITH a kept install, the port does not refuse at all — it updates the kept install.** Since J51-4 a host does not launch the cache: `--install` recorded the kept install at `<homedir>/.bantamkit/mcp` (row above). So the port's `runUpdate` checks for it before refusing, and when its manifest reports a non-blank version AND npm's `package.json` sits at the prefix (without that file `installEnvironment` reads the global tree and would render `npm install --global`, which updates a different install — so the refusal stands), it takes the registry route: the kept version is the one compared and printed, `npm install --prefix <kept> bantamkit-mcp@latest` runs, exit 0. The refusal and its correction sentence above are what an `npx` cache WITHOUT a kept install still gets, unchanged. The reference never derives `ephemeral` and keeps no install, so handed that shape it refuses whether or not a kept install sits in HOME. The job51 prep probe measured the target route for real: a prefix install aged to 0.32.1 took `--update` to `updated bantamkit-mcp from 0.32.1 to 0.33.0.`, exit 0, with a 12-tool handshake after. Ruled in `tools/conformance/suites/cli.mjs` by `update-dispatch/ephemeral-with-a-kept-install: the reference refuses an npx shape, the port updates the install --install kept`, over the exit code and stdout, with the shape, the index and the installer handed in on both sides and each side's HOME seeded with the same kept install. Unruled beside it: `…: the port's report is the registry route's report — every line not naming the command, against the reference's `behind``; `…: the reference's answer is its no-kept-install answer, byte for byte`; `…: PINNED — the port's report names the kept version and prefix, never the running one, against this file`; and, because this is a refusal on one side, `update-dispatch/PINNED PER SIDE: the exit code of every arm, and the kept-install arm is the one that differs`. |
| `prepack` compiles on Node and hatchling has nothing to compile (job56) | **not a behaviour difference — a packaging one, and it is the reason the two published 0.35.0 artifacts disagreed.** `runtime-py` ships `src/` into the wheel verbatim: there is no compile step, so there is no COMPILED artifact that can go stale, and `hatch_build.py`'s whole packaging job is vendoring the repository-root asset pack — which it does by SEARCH, not by a static path, and that search is the one place the Python half can go stale at all (attacked and measured in the J56-4 clause below; read that before treating this sentence as absolute). `runtime-ts` compiles, and `dist/` is gitignored, so it survives a checkout — compile at one commit, check `src/` back to another, and the tree is silently inconsistent with itself. MEASURED 2026-09-19: `bantamkit-mcp@0.35.0` on npm serves **12** tools over real stdio and `bantamkit[mcp]==0.35.0` on PyPI serves **14**, the same first twelve names in the same order, missing `work_plan` and `shiftwork_plan` — which are present in the npm tarball's `assets/tools/*.json` and in none of its 37 `.js` files, the fingerprint of current assets vendored over an older build. Closed on the Node side by `runtime-ts/scripts/build-for-pack.mjs`, which `prepack` runs before `sync-assets`; the Python side gets NO counterpart, and that is the divergence this row records. There is no `ruling:` case, because a ruling pins a sentence two runtimes print and neither runtime prints anything here: the gate is `tools/conformance/npx-cold-start.mjs`, which packs for real and drives the tarball over stdio, and it was demonstrated RED (2 failed checks, naming both missing tools) on a worktree whose `dist/` predates `work_plan` and GREEN (0 failed checks) on the same worktree once `prepack` builds. See `.shiftwork/notes-job56/`. **EXTENDED J56-3: the publish-time gate is Node-only too, and for a second reason — npm has a hook and the Python toolchain has none.** `runtime-ts/package.json`'s `prepublishOnly` runs `scripts/gate-before-publish.mjs`, which runs the install gate and refuses the publish on a non-zero exit; measured with npm 11.6.2, a failing `prepublishOnly` stops `npm publish` before `prepack`, before any tarball is cut and before the registry is contacted. There is no counterpart on the Python side because there is nowhere to put one: `twine upload --help` (twine in this repo's venv) offers no hook of any kind, and `hatchling`'s hooks — `runtime-py/hatch_build.py` is one — run at BUILD time, where the artifact under test does not exist yet. The Python half is covered by the release pipeline running its gates before it calls `twine`, which is a procedure rather than a hook — and that asymmetry, not a difference in behaviour, is what this clause records. **EXTENDED J56-4: the row was attacked rather than restated, and it survives with one clause corrected.** Seven attacks, each run by BUILDING a wheel from a deliberately inconsistent tree, installing it into a throwaway venv with the `[mcp]` extra and driving `initialize` + `tools/list` over real stdio; full commands in `.shiftwork/notes-job56/J56-4-python.md`. What HELD: every input to the wheel is tracked (93 of 93 asset files, nothing untracked under `runtime-py/src` but `__pycache__`), so a checkout moves `src/` and the pack together — the control is the exact mirror of J56-1's rig, where building at HEAD and then checking back to `ff23b25` in the same tree produced a COHERENT 12-tool wheel (old code AND an 18-file pack with no `work_plan.json`), not Node's old code under a current pack; `__pycache__` ships in neither artifact (0 members); a leftover `build/` cannot reach the wheel (`packages = ["src/bantamkit"]` bounds it) though it DOES ride along inside the sdist, being neither tracked nor gitignored; `*.egg-info/` reaches neither. What FELL, and is the reason the opening sentence above is now hedged: `hatch_build.py:locate_asset_pack` prefers `runtime-py/_assets/` over `../assets`, so a pack planted there wins over the commit's. Planted SHORT, the build still succeeds and the wheel pairs HEAD's `src/` with a pack missing `work_plan.json` — but the server then REFUSES TO START, naming the file (`tool asset not found: …/bantamkit/assets/tools/work_plan.json`), and `runtime-py/tests/test_packaging.py` goes red (2 failed). Planted CONTENT-stale — the same filenames, one manifest's bytes from elsewhere — the build is green, the packaging gate is green (it compares `shipped >= expected` over NAMES), and the installed server advertises the stale description and input schema over stdio with 14 tools and no error. That is the Node defect wearing Python clothes, and it is registered as debt rather than fixed here: `test_packaging.py` comparing per-file sha256 would close it, and changing a gate is the orchestrator's call, not this unit's. It stays LATENT because nothing in this repo creates `runtime-py/_assets/` — measured over four `python -m build` runs, the only thing a build leaves behind is `__pycache__/` — and because `_assets/` is not gitignored, so a stray one shows as `?? runtime-py/_assets/`, where `runtime-ts/dist/` is ignored and invisible. Separately, the PyPI publish path accumulates: `python -m build` does not clean `dist/`, `dist/` and `dist-*/` are gitignored, `twine check` reports `PASSED` on a 0.34.2 wheel sitting beside the 0.35.0 one (it validates metadata, never currency), and `docs/install.md` step 4 says only "`twine upload` the wheel and sdist" — so a release script must build into a clean directory and upload by exact filename, never a `dist*/` glob. The live `runtime-py/dist/bantamkit-0.35.0-py3-none-any.whl` was compared member by member against the working tree and matches it byte for byte (0 differing `.py`, 0 differing assets), so nothing stale is sitting there today. |
| the update record's registry key, read AND written (J57) | **two registries, one file, and each runtime reads its own half — the same genuinely-different-object as `--update`'s index URL, not a new kind of one.** `<homedir>/.bantamkit/update-check.json` carries BOTH indexes — `{"npm": {"package": "bantamkit-mcp", "latest": …}, "pypi": {"distribution": "bantamkit", "latest": …}}` — because npm and PyPI can disagree at one version number, and job56 shipped a day where they did. `updatecheck.KEY` is `pypi` on the reference and `npm` on the port, so each runtime compares the version it is RUNNING against the index its own install came from; a single shared key would have one of the two reporting the other ecosystem's version as its own. The WRITER half diverges with it and for the same reason: `selfupdate.record_update` fills `pypi` and names a DISTRIBUTION, `selfupdate.recordUpdate` fills `npm` and names a PACKAGE, and each leaves the other's entry exactly as found — neither name is a translation of the other. Pinned by three `ruling:` cases in `tools/conformance/suites/updatecheck.mjs`: the key constant, the default-key answer on the three arms where the two registries disagree, and the `{key, field}` each writer produces. **What does NOT differ is the larger half and is compared unruled, under BOTH keys:** every one of 42 arms — all five states, every malformed shape, the loader's three outcomes, the five sentences byte for byte, the rendered lines, the record path's suffix, and that a read creates nothing — is asked of both runtimes under `pypi` AND under `npm`, and the two answers must be equal field for field. There is NO refusal bit to compare here, and that is not an omission: neither runtime refuses anything on this surface — every malformed shape is a state with its own sentence — so the companion the rule asks for takes the form above instead, plus a per-side pin that not one shape RAISES on either side. J57-5, 2026-09-19. **AMENDED 2026-09-21 (job62, J62-13): the WRITER half's “leaves the other's entry exactly as found” was true of the entry's BYTES and false of the fact about it.** Each writer also stamped the record's own `checked_at`, which is the fallback dating every entry WITHOUT a stamp of its own — so `--update` on one side re-dated the OTHER registry's untouched number by a check that never asked that registry. Measured on this branch, one file, two readers, after a Node `--update` took `npm` from 0.30.0 to 0.36.0 and left `pypi` at 0.30.0 from three weeks earlier: the reference said `update: bantamkit-mcp 0.30.0 is current as of 2026-09-20.` while the port correctly said an update was available. **The record now carries two stamps and this row's divergence is UNCHANGED by it:** an ENTRY's `checked_at` is when that registry answered, the RECORD's is when a writer refreshed the record as a whole, and each runtime still writes only its own key and still names its own registry's noun. What changed is that `record_update`/`recordUpdate` stamp their OWN ENTRY and never the record's — the same change on both sides, so it is not a new divergence and gets no ruling. The unruled table grew with it: 50 arms over 38 records (was 42 over 32), including the partial-probe record where one key is stamped and the other is not, and where the DATE in the sentence is key-sensitive although the state is not. The merge literal now pins that the record's stamp does NOT move, and the fresh-record bytes pin that a `--update` record has no record-level stamp at all; both were seen red against the defect restored on one side and on both. `docs/hooks.md`, *Two stamps, and which one dates which number*. |
| the update command `bantamkit_status` prints (job66, #171) | **each runtime names its own interpreter and entry point, because the command must run the install that answered.** The `available` sentence is byte-identical on both sides and carries `` `{command}` ``; the reference fills it with `"<sys.executable>" -m bantamkit.mcpserver --update` and the port with `"<process.execPath>" "<dist/cli.js>" --update`. WAS: the bare `bantamkit-mcp --update` on both sides, which a pip venv or an npm kept install puts on nobody's PATH, so it answered `command not found` from a GUI-launched host's shell (`PATH=/usr/bin:/bin`). Not a refusal, so no refusal-bit companion: the companions are the command PINNED PER SIDE to a literal built from the interpreter each side runs under, a per-side literal that it starts with a quoted absolute path, and the command RUN per side from `/bin/sh` with only `/usr/bin:/bin` on PATH (`-h` swapped for `--update`). Ruled in `tools/conformance/suites/updatecheck.mjs` — `updatecheck: the update command — each runtime names its own interpreter and entry`; every rendered line is compared with each side's own command masked to `<command>`. The hook's stale-install line (row below) prints `process.execPath` the same way. |
| the hook's `nativeError` (job62) | **both refuse, and the sentence after the refusal is each standard library's own.** When `SessionStart` exports bantamkit's project fact descriptions into Claude Code's own auto-memory (see `docs/hooks.md`, *Exporting into the host's own auto-memory*), branch 1 of the resolver — `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE` — is taken UNVERIFIED, because it is the host's own top-precedence branch and bantamkit does not get to second-guess it. So an override naming a directory that is not there is the one shape in which the export's write fails. Both runtimes then export nothing, create nothing, record the failure in the `SessionStart` log line's `nativeError`, emit their one JSON object and exit 0. The sentence is the one each language spells for a single failed `open()`: CPython's `[Errno 2] No such file or directory: '<p>'` on the reference, libuv's `ENOENT: no such file or directory, open '<p>'` on the port. Neither can produce the other's without hand-rolling the other's `strerror` table, which is the same class as the three `open()` rows already in this table, and inventing a third wording would throw away the errno the reference gives a reader. The field is LOG-ONLY: it never reaches stdout, so nothing the model sees moves with it. Ruled in `tools/conformance/suites/hooks.mjs` as `native-missing-dir: nativeError carries each runtime’s own OS sentence`. **Because a ruling only proves the two sides still DIFFER and never that either still refuses**, beside it unruled: `native-missing-dir: the refusal BIT — both log an error, export nothing, exit 0, emit one object`; the same bit against a literal, per side (`{errorPresent: true, exported: 0, files: 0, indexLines: 0, bytes: 0, exit: 0, stdoutObjects: 1}`), because a differential over a bit is blind to both sides losing it at once; `native-missing-dir: every other native* field agrees, with the ruled sentence masked`; and `native-missing-dir: A created no directory`, per side, read before the bed is restored — `mkdir` is precisely what the export must never do, and a runtime that made the directory would turn this scenario into a successful export next session. That last pair is not decoration: J62-8 mutated the port to `mkdir` the missing directory and the refusal bit, its literal and the no-directory case went red while the RULING went MALFORMED rather than red. The ruling could not have caught it alone. |
| the compact report's cut, at 600 and at 400 (job62 row 7) | **A DEFECT RECORDED SO IT CANNOT BE LOST — NOT a permitted difference, and the only row in this table that is asking to be deleted.** `out.slice(0, 600)` counts UTF-16 code units where `out[:600]` counts code points. It is the cut the `PostToolUse[memory_save]` hook arm puts on the compact child's report before embedding it in `additionalContext`, and again at 400 on the same text in the hook log's `out`. **The first draft of this row said “astral characters only, and the compact report has none”, so the divergence was latent. That half was wrong, and J62-8 measured it wrong**: the report prints the STORE PATH twice, and a project directory is a name the operator chose. MEASURED 2026-09-20, driven over a project directory holding eight emoji with `--index-budget 300` pinned in `.mcp.json`: `additionalContext` is **667 code points on the reference and 659 on the port**, the log record's `out` **400 against 392**, and the port's text is a strict PREFIX of the reference's — the two differ only in where they stop. Eight astral characters in the path, eight code points of the model's context silently dropped on the port, on stdout, today. The repair is one line per runtime (`[...out].slice(0, 600).join('')` on the port, or the mirror on the reference) and under CLAUDE.md it lands in BOTH or in NEITHER; when it lands, the two rulings below go STALE and redden and the four per-side literals redden with them, and **that pair of failures is the design, not a regression**. Ruled twice in `tools/conformance/suites/hooks.mjs`: `row7: the compact report cut into additionalContext — 600 code points against 600 UTF-16 units` and ``row7: the same cut in the log record’s `out`, at 400``. Unruled beside them: `row7: the divergence is a cut point and nothing else — the port’s text is a prefix of the reference’s` (`{prefix: true, shorterByCodePoints: 8}`); four per-side literals over what survived each cut (600 against 592, 400 against 392); a per-side precondition asserting eight astral characters in front of both cuts and both cuts fired; and ``row7: every other field of the auto-compact record agrees, with the ruled `out` masked``. The bed is built so the cut lands INSIDE the archived-names block, before the `restore one with:` line, which keeps the memory CLI's already-ruled `prog` divergence (the row above, *the memory CLI's `prog`*) out of the compared bytes entirely; a later unit that widens the bed inherits that substitution. One trap recorded with it, because it cost a wrong conclusion: `String.prototype.length` counts UTF-16 code units, so a draft of these literals measured the reference's 400-code-point cut as 408 and concluded the REFERENCE was wrong. The suite now counts with `[...s].length` through a named helper carrying that incident in its docstring — a suite about a code-unit/code-point divergence must not itself count in code units. |
| the `.shiftwork` scan's filename tie-break (job62 row 8) | **A DEFECT RECORDED, NOT a permitted difference — and this one steers the two runtimes at two different jobs.** `candidates.sort(… \|\| a.file.localeCompare(b.file))` on the port is ICU collation; the reference sorts the same filenames by code point. It is reached only when two OPEN checkpoints in one `.shiftwork` directory share an mtime to the millisecond. MEASURED 2026-09-20 over exactly that bed: the reference steers the summariser at **`checkpoint-Banana.json`** (`'B'` is 0x42, below `'a'` at 0x61) and the port at **`checkpoint-apple.json`** (ICU: apple sorts before Banana). It is not a log field — it surfaces on STDOUT, in `PreCompact`'s steering line `Open shiftwork checkpoint: <file>, cursor …`, and in the hook log's `checkpoint`. Two runtimes handing one summariser two different jobs, with nothing saying so. The repair is one line per runtime and lands in both or in neither; when it lands the ruling goes STALE and reddens with its per-side literal, by design. Ruled in `tools/conformance/suites/hooks.mjs` as `row8: which checkpoint wins a tie — ICU collation against a code-point sort`, with three unruled cases beside it: `row8: precondition — two checkpoints, one mtime, in one directory both runtimes read`, `row8: PINNED PER SIDE: which file each runtime actually chose, against this file`, and `row8: the scan itself agrees — same cursor, same files read, same files skipped`. **And a CONTROL**, `row8-control`, for the `tests-that-pick-the-input-that-cannot-fail` shape: the ruled case alone would be satisfied by two runtimes that disagree about the scan for ANY reason, so the control gives the same two filenames two DIFFERENT mtimes, never reaches the tie-break, and demands byte-identical stdout. J62-8 proved the split by mutating the port to scan oldest-first: the control went red and the ruling stayed green. A measured trap beside it: **a case-only pair cannot be built on this machine.** The first bed used `checkpoint-Alpha.json` and `checkpoint-alpha.json`, APFS is case-insensitive, the second write replaced the first, and the directory held ONE file and a tie-break that was never reached. The bed now differs in more than case, and the precondition asserts two files and one mtime so it cannot silently collapse again. |
| the hook's stale-install line, and the probe that feeds it (job62) | **the port emits one line at `SessionStart` that the reference cannot, and the reference does not pretend to.** `docs/hooks.md`, *The stale-install signal*: when the kept npm install under `~/.bantamkit/mcp` is behind the package index, the port appends one line to `additionalContext` naming that install and `"<process.execPath>" "<kept cli.js>" --update` (job66/#171; it named the bare `bantamkit-mcp --update` until 2026-09-26 and the bare `node` until job66). The reference appends nothing, because the line is decided through `updatecheck`'s reading of the kept install that `npminstall.ts` makes, and there is no Python counterpart to that under the pure-node-install ruling (`public-install-is-pure-node-by-ruling`); the detached writer, `tools/hooks/update-probe.mjs`, ships in neither artifact. MEASURED 2026-09-20 in a throwaway `HOME` seeded with a kept install at 0.35.1 and an `~/.bantamkit/update-check.json` naming 0.36.0: the port's `additionalContext` carries the toolbox line plus the stale-install line and logs `{updateState: "available", updateProbe: "fresh", updateBytes: 262}`; the reference's carries the toolbox line alone and logs `{updateState: null, updateProbe: "node-only", updateBytes: 0}`. This is a REFUSAL and not a spelling, and it is a difference the model can see, so under CLAUDE.md it owes a `ruling:` case AND a second non-ruled case comparing the “did it emit an update line at all” bit. **NEITHER EXISTS. That is stated here rather than hidden: this row is currently held by a sentence, not by a rerunnable gate, and the numbers above are a hand probe rather than a case.** It is the one row job62 added that `node tools/conformance/run.mjs --all` does not hold; the two cases belong to whichever unit next touches `hooks.mjs`. **AMENDED 2026-09-20 (job62, J62-10, review): the debt above is DISCHARGED — this unit was the unit that next touched `hooks.mjs`, so it wrote the cases rather than passing the row on again.** `tools/conformance/suites/hooks.mjs` now carries a `stale-install` scenario: a bed seeding, into each side's own throwaway `HOME`, a kept install at 0.35.1 and an `~/.bantamkit/update-check.json` naming 0.36.0 with `checked_at` stamped NOW — inside the 24 h TTL on purpose, so the probe reports `fresh` and the adapter spawns no detached child on the machine running the gate. Four cases: the injected `SessionStart` block, **ruled**; the same block with the update line removed, compared **unruled**, which is the half the ruling does not license; and the bit PINNED PER SIDE, `{updateState: null, updateProbe: "node-only", emitsUpdateLine: false, updateBytes: 0}` on the reference against `{updateState: "available", updateProbe: "fresh", emitsUpdateLine: true, spawnedNothing: true}` on the port. **The companion shape is NOT `nativeError`'s, and the row is the reason why:** there both sides refuse, so the refusal bit is the SAME on both and a differential over it is the companion; here exactly ONE side emits, so a differential over the bit could only ever be red and the honest companion is the bit pinned per side. `updateBytes` is pinned only on the reference, where it is 0; on the port it counts a line carrying an absolute path and is therefore a function of where the scratch directory landed. A precondition case stops the suite with *"stale-install bed did not arm"* if the port ever emits nothing, so the bed cannot silently become one where the two agree for the wrong reason. Red shapes run before committing: the port stopping emitting fires the precondition; a port that rewords the toolbox line reddens the unruled companion while the ruling stays green; the reference renaming `node-only` reddens its own per-side literal. |
| a prerelease version's spelling (job68 J68-12) | **one version, two registry spellings, and each runtime reports its own registry's.** PyPI requires PEP 440 and npm requires semver, so a prerelease cannot be one string on both: `runtime-py/src/bantamkit/__init__.py` declares `0.37.0b1` and `runtime-ts/package.json` declares `0.37.0-beta.1`. Each runtime reports the spelling of the registry it was published to — in `serverInfo.version` and in `build_identity`'s `version` — because a client that compares that number with its own registry (`pip index versions`, `npm view`) must find it there. Rewriting either side to the other's spelling would make one runtime report a version its own registry cannot carry. The two are ONE version after `tools/release/publish.sh`'s `map_pep440_to_semver` (`aN` → `-alpha.N`, `bN` → `-beta.N`, `rcN` → `-rc.N`), and a STABLE version is still byte-identical. User ruling 2026-10-15. Gated by `tools/conformance/suites/version.mjs` over fixture trees (no manifest is bumped): the prerelease `ruling:` cases pin that the two spellings DIFFER, a non-ruled case beside each pins that the reference's answer mapped through `publish.sh`'s mapping is byte-identical to the port's, per-side literals pin each spelling, a stable `0.36.0` is compared byte for byte, and `pep440ToSemver` is checked against the script's own function. `test_version_agreement.py` and `packaging.test.mjs`'s `the two version declarations agree` compare the declarations the same way, `wire`'s `build_identity: version agrees` and `cli`'s four `…/handshake` frame comparisons map the reference's `version` before comparing, and `server.test.mjs`'s status-report line compares against `package.json`'s own version instead of a stable-only `\d+\.\d+\.\d+` shape. |
| a rotated log segment's raw `.gz` bytes (job69 J69-1, #204) | **two zlib builds, one decompressed stream.** `LogSegment.rotate` gzips the live file on both runtimes with a zero header mtime, but CPython's `gzip.compress` writes XFL 2 / OS 255 at level 9 and Node's `zlib.gzipSync` XFL 0 / OS 3 at level 6, so the deflate streams and two header bytes differ. Either runtime reads the other's segment, because both read through a full gunzip. `storage-log` carries one `ruling:` case on the raw bytes and compares every segment's DECOMPRESSED bytes as non-ruled cases beside it; a per-side literal pins `1f 8b 08 00` and the zero mtime, so neither side can satisfy the ruling by writing something that is not gzip. Pinning the bytes would mean shipping a deflate implementation in one runtime. |
| a caller's float or integer-like key on a `LogSegment` line (job69 J69-4, #204) | **CLOSED BY G2 (J88-2).** The reason below ("Python would have to emulate `JSON.stringify` in a third serialiser") is gone: `bantamkit.storage.logsegment` now runs the generated `dumpsLine`, which IS `JSON.stringify`, so both runtimes write `{"1":2,"b":1,"f":1,"e":1e-7,"ts":"n"}` for the caller object below and `storage-log`'s case agrees, its bytes pinned by one literal per side (`LITERAL: both spell the caller numbers as JSON.stringify`). The moved Python answers are in *Generated modules*, G2. Was: **the object a caller hands `LogSegment.append` is serialised as given, by each runtime's own serialiser.** `json.dumps` keeps `1.0` and writes `1e-07` and keeps insertion order; `JSON.stringify` writes `1` and `1e-7` and moves an integer-like key (`"1"`) ahead of every other key. A line both runtimes append to the same file can therefore differ in spelling while reading back to the same values. Normalising was considered and refused: the Node side cannot recover `1.0` once JavaScript has parsed it, so the only possible normal form is Python emulating `Number.prototype.toString` and V8's key order inside `dumps_line`, a third serialiser to keep true, for inputs none of the three logs on `LogSegment` produces from its own code. The usage ledger writes strings only and spells its folded weight itself with nine fixed decimals; the hook log writes ints, strings, bools and lists; the event log writes a closed set of tokens, ints and bools. The one route in is a host-echoed hook field (`session`, `source`), which diverged the same way before #204, because each runtime parses the host's JSON its own way. `storage-log` carries one `ruling:` case on the bytes of `{"b":1,"1":2,"f":1.0,"e":1e-7}` built in code on each side, a non-ruled `read` beside it (the values agree), and a per-side literal for each spelling, so a change to either side's serialiser reddens. |
| `client` — Node's OpenAI-compatible client (job73 C2, #206) | **a subset, and one library's words.** `runtime-ts/src/client.ts` ports only what the #206 drafter calls: `OpenAICompatible(baseUrl, model, {apiKey, timeoutMs, maxRetries, seed})` and `chat(messages, {responseFormat})`. Not ported, because no #206 surface reaches them on either runtime: tool definitions and `tool_calls` parsing, the declared `context_window` and its `VOID` verdict (with no window Python answers `UNREPORTED`/`UNCHECKED`, and so does the port), and `close()`/the context manager. Everything else is shared and compared unruled by `tools/conformance/suites/llm-client.mjs`: the request bytes, the retry count and waits, the `response_format` drop, and every sentence, including the four Python lets escape `chat` (`JSONDecodeError`, `TypeError`, `AttributeError`, `UnicodeEncodeError`) and a read timeout's `timed out`. **The one ruling:** the text after `chat failed after N attempts: ` when the failure is the HTTP library's own — refused (`[Errno 61] Connection refused` vs `connect ECONNREFUSED <addr>`; httpx's errno is the platform's) and a peer hanging up (`Server disconnected without sending a response.` vs `socket hang up`). Two `ruling:` cases pin that they differ; two unruled companions compare that both refuse with `TransportError`, the same prefix and the same number of requests. |
| `skillfile` — a `SKILL.md` metadata value nested below one level (job73 C1, #206) | **the same reader boundary as `hooks/native-mirror-ruled`, met by a new file.** `skillfile.parse_skill` reads a skill's frontmatter with the memory store's reader on each side (`yaml.safe_load` + `well_formed_frontmatter`; the port's `parseFrontmatter`). A `metadata:` value that is itself a block mapping or an indented block sequence is read by PyYAML, so `validate` answers `metadata <key> must be a string`; the port's reader refuses every shape it does not implement (#120's standing ruling, the same one that skips such a native file in the mirror), so `parseSkill` refuses the file with `SKILL.md frontmatter is not a readable mapping`. Both sides REFUSE the skill; only the sentence differs. Every shape bantamkit itself writes (`render`: one level of double-quoted strings) and every one-level non-string value (int, bool, null, date, flow list) is compared unruled. Extending the port's reader was tried in C1 and reverted: it changed `hooks/native-mirror-ruled`, which the user ruled. Gated by `tools/conformance/suites/skill-file.mjs`: two `ruling:` cases, a refusal-bit twin for each (`not a valid skill` on both sides) and a per-side literal for each answer. **Not part of this ruling (job73 C8): the shapes the port's reader refuses wherever they stand** — a flow mapping (`metadata: {}`, `{k: 1}`, one under a key or inside a flow sequence), an anchor, an alias, a tag, a directive. PyYAML read them, so a draft holding `metadata: {}` passed the gate in Python and failed it in Node. `parse_skill` now refuses each from the scanner's own tokens with the port's sentence, so both sides give the same verdict and the `skill-file` cases compare it unruled. **Inherited, not re-ruled (job73 C14):** the `[skill]` recall layer reads every `SKILL.md` through `parse_skill`, so a skill holding a nested `metadata` value is skipped on BOTH sides and named in `skipped` with each side's own sentence above; the `skill-layer` fixture leaves that shape out, and the drafter's gate refuses such a draft on both sides before anything installs it. |
| fact-file frontmatter: a nested value in a hand-written key (#315, J86-4) | **WAS a difference — node threw where python wrote; now byte-identical, with two edges node refuses by name.** A hand-written key rides in `Fact.extra` and is written back on every rewrite (#199 Task 6). runtime-py's `_fact_text` (`yaml.safe_dump(sort_keys=False, allow_unicode=True)`) writes a nested `metadata:` mapping; node's `formatFact` threw `cannot emit object for key metadata`, so a recall stamp failed on 478 of the 495 Claude Code native memory files J86-2 measured (`nested-map-rewrite` in `tools/conformance/suites/ts2py-codec.mjs`, no row here). NOW `safeDumpMapping` (`runtime-ts/src/memory/pyyaml.ts`) walks PyYAML 6.0.3's own emitter states for lists and plain-object mappings at any depth: indentation, `- ` items at a nested key's column (`indentless`), `{}` and `[]`, scalar quoting and the 80-column wrap at depth, key order, and — at the root too — a key PyYAML cannot write simple (123 codepoints or more, empty, or multi-line) as `? key` / `: value`, where node used to write such a ROOT key as a simple key PyYAML never writes. **Still refused on node, by name (`cannot emit ...`), where PyYAML writes:** a list or mapping that appears twice in one document (PyYAML writes an `&id001` anchor and a `*id001` alias) and an array-index key in a nested mapping (JS's `Object.entries` lists it first, so the object no longer holds the order PyYAML writes). Reason: neither can be reproduced from a JS value, and node's own reader yields neither (no alias, no key starting with a digit), so no file the node store reads reaches them; python reaches them only through a PyYAML read, which is the fallback J86-3 owns. **A round-trip asymmetry, registered, not widened:** node now WRITES shapes its reader still refuses under #120's standing ruling — a mapping or a block sequence below one level of nesting, a mapping inside a list, a flow `{}`, a `? ` key (each refused by name, none misread) — so a file carrying one is written alike by both and read back only by python. Gated by `tools/conformance/suites/codec.mjs` (`emit nested/*`: 12 shapes byte for byte; for each refused edge a `ruling:` case, a per-side node-refuses case and a per-side python literal) and by `ts2py-codec`'s `nested-map/py=node` on the fuzz and the real stores. |
| `jobbudget` — a token figure or limit beyond 2^53, or spelled `1e20` (J87-1F, #316) | **WAS RULED AS NODE (a figure is a double) — CLOSED by #316 G1 (J87-3); now agreeing, so no ruling.** Before: the hand-written Python kept the exact integer (`9007199254740993`; `int(1e20)` prints `100000000000000000000`), Node held the nearest double (`9007199254740992`, spelled `9007199254740992.0` by `fromJs`; `1e+20`), so `spent`/`remaining`/`affordable` and the refusal's count differed by the rounding. After: Python runs `_generated/jobbudget.py`, compiled from `jobbudget.ts`, and `bantamkit.jobbudget` lifts its answer as `fromJs` does (`_js_py_value`: a safe integer is an `int`, any other number a `float`), so both answer the double, byte for byte. Pinned by the four `double:` cases of `node tools/conformance/run.mjs --suite jobbudget` and their per-side `literal: double:` views; until J87-3 they were `ruled:` cases, which went stale (10 failures) the moment Python switched. |
| `jobbudget` / `shiftwork_plan` — a `job.budget` limit spelled `5.0` (J87-1G, #316) | **WAS RULED AS NODE (a figure is a double) — CLOSED by #316 G1 (J87-3); now agreeing, so no ruling.** Before: the checkpoint schema types each dimension `integer`, which accepts an integral float on both sides, so `5.0` reached the view; the hand-written Python kept the float it decoded (`"limit": {"tokens": 5.0}`, `"remaining": {"tokens": 4.0}`, `"affordable": 4.0`), while Node's `toJs` held the number `5` and `fromJs` gave it back as the int `5`. After: the generated module's view, lifted as `fromJs` lifts Node's, answers `5` / `4` / `4` too. Pinned by `double: a token limit written 5.0` and `checkpoint limit 5.0: job.budget.<dim> = 5.0` (tokens, units, wallclock_ms) in `--suite jobbudget`, plus per-side `checkpoint limit 5.0 spelled:` literals holding each side to `5` and to accepting the limit. |
| `pricing` — a model named `toString`, `constructor`, `__proto__`, `hasOwnProperty`, `valueOf` (any `Object.prototype` name), and a price table naming a model `__proto__` (J87-3F, #316) | **WAS a difference — fixed in both runtimes; now agreeing, so no ruling.** Before (J87-3 measured): Node's `table.rates?.[model]` read the inherited member, so such a model that the table does not hold was priced at $0.00 with `rate: {}` for an all-zero usage, and refused with `rate for model 'toString' does not price 'input_tokens' ...` otherwise, against property 3 (a missing rate is never a zero); the Python shim kept the hand-written `no rate recorded for model '<name>'` by special-casing the lookup (`_inherited_lookup`). A table whose `rates` names a model `__proto__`: Node's `built[model] =` set the prototype, so the model vanished from the loaded table (it was still priced, through the prototype); the generated Python raised a ts2py `TypeError` (assigning `__proto__` is outside the subset) out of `validate_price_table` and `load_price_table`. After: `pricing.ts` looks a model up by own key (`Object.hasOwn`) and builds `rates` with `Object.fromEntries` (an own data property per model, `__proto__` included); the regenerated `_generated/pricing.py` lowers both through `_js_object_has_own` / `_js_object_from_entries`, and the shim's workaround is deleted. Both runtimes: an `Object.prototype` name is an unknown model (`no rate recorded ...`), and a `__proto__` model is listed and priced like any other. Why fixed rather than ruled: Node's answer broke the module's own property 3, and no earlier ruling covered it (the orchestrator's J87-3 decision). Pinned by `--suite pricing` (`full rate: <name> is no model`, zero usage and tokens spent, for the five names; `table: a __proto__ model` and `... beside another`; four `__proto__ table:` priced cases; `load: proto.json`; per-side literals `an Object.prototype name answers "no rate recorded"` and `a __proto__ model is listed and priced`), 16 of them red against 25a7880f's Node. |
| `jobbudget` — a hand-edited ledger: non-finite figures, `-0`, strict unit identity, `__proto__` (J87-1F, #316) | **WAS a difference — fixed in both runtimes; now agreeing, so no ruling.** Before (J87-1 measured): a `tokens`/`duration_ms` of `Infinity`, `-Infinity`, `NaN` or `1e400` made Python raise `OverflowError`/`ValueError` out of every tool that reads the ledger, while Node booked `Infinity`, answered `NaN` in `remaining`/`affordable`, or refused with `budget wallclock_ms spent: Infinity of …`; `-0.0` made Node answer `per_unit -0.0`; Python matched an `uncommitted` event to its unit with `==`, so `null` matched a missing unit, `true` matched `1` and two equal object units matched, where Node's `===` did not; and a `__proto__` key set the prototype in Node's `pyjson.toJs`, so `'tokens' in line` read through it. After: a non-finite figure is one more value that is not a non-negative number and counts 0 (`_number` / `figure`, the rule a string or a boolean already had); `-0` is `0` in every view field; **Python changed to strict matching** (J87-1F's `jobbudget._same_unit`: a missing unit is not `None`, `bool` is not `int`, `str` is not `int`, a dict or list unit never matches, `1 == 1.0` still does; since #316 G1 (J87-3) the generated module's `===` is that rule); `toJs` makes `__proto__` an own key. A non-finite LIMIT needed no change: the checkpoint schema types each `job.budget` dimension `integer`, and both runtimes refuse `Infinity`/`NaN`/`1e400` there with the sentence a string limit gets (`checkpoint invalid: … inf is not of type 'integer'`), pinned per side. Pinned by `--suite jobbudget` (`hand-edited:`, `checkpoint limit:` and their per-side literals) and, for `toJs`, `--suite wire` (`pyjson-proto-key`). |
| `eventlog` — a `__proto__` key in a record's `detail` (J88-1 #5, #20; J88-1F, #316 G2) | **WAS a difference — fixed in Node; now agreeing, so no ruling.** Before: `recordObject` built the sorted detail with `sorted[key] = detail[key]`, a [[Set]] that on `__proto__` set the prototype, so Node wrote `{"a":2}` where Python wrote `{"__proto__":1,"a":2}` — a caller's key silently lost (the J87-1F/J87-3F class). After: the copy is `Object.fromEntries` over the code-point-sorted keys (own data properties, which ts2py lowers as `_js_object_from_entries`), so both write the key. Pinned by `--suite eventlog`: `encode_record(0, memory_save, saved, proto_key)`, `bed: a detail holding a __proto__ key keeps it` and the per-side `LITERAL: a __proto__ detail key is written as a key, sorted like any other`; red against the old `eventlog.ts` (3 cases). `logsegment.ts` and `tokenledger.ts` copy no caller key by key (`tokenledger` copies only its four fixed token classes). |
| `LogSegment` — the permission bits of a folded log, a `.gz` segment and a `write_over` target (J88-1 #30; J88-1F, #316 G2) | **WAS a difference — fixed in Python; now agreeing, so no ruling.** Before: `write_over`, `_replace` and `_mark` called `os.open(..., O_CREAT\|O_EXCL\|O_WRONLY)` with `os.open`'s default mode 0o777, so under umask 022 each rewritten file was 0o755 on Python where Node's `fs.openSync(tmp, 'wx')` (mode 0o666) left 0o644; an appended-only log was 0o644 on both. After: the three pass `_FILE_MODE = 0o666`, so every file is `0o666 & ~umask` on both. Pinned by `--suite storage-log`: the ops of `J88-1 the permission bits of a rewritten log, a segment and a write_over target` compared side to side and `LITERAL: J88-1F every file, appended or rewritten, is 0o666 & ~umask` per side; red against the old `logsegment.py` (4 cases). `storage/lock.py`'s lock file kept `os.open`'s default mode until J90-1F (#316 G4 prep), which opens it 0o666 too: `--suite storage-lock` compares the held lock's bits and pins `[true, '0o644']` per side under umask 022, red against the old `lock.py`. |
| G2 as Node: timestamps outside the ISO range (J88-1 #1–4; J88-1F, #316 G2) | **CLOSED BY G2 (J88-2): Python is generated from the TypeScript and answers Node's; the suite case is an ordinary agreeing case with a per-side literal.** Was RULED AS NODE until J88-2. `format_timestamp` over a millisecond count outside years 1–9999 or a negative fractional count. Python before: `datetime` + `timedelta` raise `OverflowError` for year 10000 (`253402300800000`), year 0 (`-62135596800001`) and the last `Date` (`8.64e15`), and round `-1.5` toward −∞ (`1969-12-31T23:59:59.998Z`). Node (and Python after): `new Date(ms).toISOString()`: `+010000-01-01T00:00:00.000Z`, `0000-12-31T23:59:59.999Z`, `+275760-09-13T00:00:00.000Z`, and truncation toward zero (`…59.999Z`). Why Node: the generated module IS `eventlog.ts`, and a clock outside those years is not one a host reports; no earlier ruling covers it. Cases: `eventlog`'s four `ruling: G2 as Node — format_timestamp(<ms>)` and `LITERAL: G2 ruled as Node — node's format_timestamp outside the ISO range`. **J88-2 makes it agree**: Python is then compiled from the TypeScript and inherits Node's answer, the `ruling:` case goes STALE by design and J88-2 turns it into an ordinary case and closes this row. |
| G2 as Node: record numbers and key order (J88-1 #6–9, #11, #12; J88-1F, #316 G2) | **CLOSED BY G2 (J88-2): Python is generated from the TypeScript and answers Node's; the suite case is an ordinary agreeing case with a per-side literal.** Was RULED AS NODE until J88-2. `encode_record` over a `detail` the event log's own callers never build (they write a closed set of tokens, ints and bools; see the J69-4 row above). Python before (`json.dumps`): integer-like keys in code-point order `{"10":1,"9":2,"a":3}`, `1.0`, `1e-07`, the bare word `NaN`, `18446744073709551616`, `-0.0`. Node (and Python after, `JSON.stringify`): `{"9":2,"10":1,"a":3}` (a JS object moves integer-like keys first after the sort), `1`, `1e-7`, `null`, `18446744073709552000`, `0`. `NaN` is a refusal on BOTH sides at `record()` (a lost record), compared unruled by `bed: a non-finite detail value is refused on both sides as a lost record`. Cases: six `ruling: G2 as Node — encode_record detail <name>` and `LITERAL: G2 ruled as Node — node's encode_record over the ruled details`. **For J88-2, not changed here:** generating `logsegment.ts` moves `LogSegment.append`'s caller-object spelling to `JSON.stringify` too, so the J69-4 row's `ruling: a caller's float and integer-like key are spelled by each serialiser` and its `LITERAL: the reference spells the caller numbers` go red there and that row needs closing in the same unit. **J88-2 makes it agree**: Python is then compiled from the TypeScript and inherits Node's answer, the `ruling:` case goes STALE by design and J88-2 turns it into an ordinary case and closes this row. |
| G2 as Node: lone surrogates (J88-1 #10, #19, #24; J88-1F, #316 G2) | **CLOSED BY G2 (J88-2): Python is generated from the TypeScript and answers Node's; the suite case is an ordinary agreeing case with a per-side literal.** Was RULED AS NODE until J88-2. A lone UTF-16 surrogate in a value. Python before: `encode_record` and `record()` raise `UnicodeEncodeError` (the payload is encoded before the `OSError` guard, so `record()` writes nothing and the exception escapes); `tokenledger.as_json` (`json.dumps(ensure_ascii=False)`) holds the lone surrogate RAW in a `str` no UTF-8 encoder accepts. Node (and Python after): the well-formed `JSON.stringify` escapes it as the six characters `\ud800`, so the line is written and the document is valid UTF-8. Why Node: it is the only answer that leaves a valid file and a valid reply. Cases: `eventlog`'s `ruling: G2 as Node — encode_record detail lone_surrogate` and `ruling: G2 as Node — bed: a detail holding a lone surrogate`, `tokenledger`'s `ruling: G2 as Node — read: a lone surrogate in a session id and a cwd` with its unruled companion `J88-1 read: a lone surrogate session id — both count one request in one session`, and Node's bytes pinned in the two `LITERAL: G2 ruled as Node — …` cases. **J88-2 makes it agree**: Python is then compiled from the TypeScript and inherits Node's answer, the `ruling:` case goes STALE by design and J88-2 turns it into an ordinary case and closes this row. |
| G2 as Node: the switch spelling (J88-1 #13–17; J88-1F, #316 G2) | **CLOSED BY G2 (J88-2): Python is generated from the TypeScript and answers Node's; the suite case is an ordinary agreeing case with a per-side literal.** Was RULED AS NODE until J88-2. `BANTAMKIT_EVENT_LOG`'s value is trimmed before it is read as OFF/ON or a path. Python before: `str.strip`, which strips U+0085 and U+001C–U+001F but not U+FEFF; and a literal path answered as `Path(raw)` (`./events.jsonl` → `events.jsonl`, `a//b.jsonl` → `a/b.jsonl`). Node (and Python after): `String.prototype.trim`, the reverse set (`\ufeffon` is ON; `on\u0085` and `\u001con` are literal paths), and the path as spelled (the same file either way). Cases: five `ruling: G2 as Node — resolve_path(<raw>)` and `LITERAL: G2 ruled as Node — node's resolve_path over the ruled spellings`. **J88-2 makes it agree**: Python is then compiled from the TypeScript and inherits Node's answer, the `ruling:` case goes STALE by design and J88-2 turns it into an ordinary case and closes this row. |
| G2 as Node: a literal path ending in `/` (J88-1 #18; J88-1F, #316 G2) | **CLOSED BY G2 (J88-2): Python is generated from the TypeScript and answers Node's; the suite case is an ordinary agreeing case with a per-side literal.** Was RULED AS NODE until J88-2. `BANTAMKIT_EVENT_LOG=<dir>/`. Python before: `Path('<dir>/')` drops the slash, so the record lands in a FILE named `<dir>`. Node (and Python after): the open of `<dir>/` fails, the record is lost and `write_failed` is true, nothing created — the documented answer for a literal path that cannot be written. Cases: `eventlog`'s `ruling: G2 as Node — bed: a literal path ending in / (BANTAMKIT_EVENT_LOG=<dir>/)`, its unruled companion `bed: a literal path ending in / — both stay enabled and neither raises`, and Node's `{write_failed: true, names: []}` in `LITERAL: G2 ruled as Node — node's beds: …`. **J88-2 makes it agree**: Python is then compiled from the TypeScript and inherits Node's answer, the `ruling:` case goes STALE by design and J88-2 turns it into an ordinary case and closes this row. |
| G2 as Node: CR and CRLF line ends in a transcript (J88-1 #21, #22; J88-1F, #316 G2) | **CLOSED BY G2 (J88-2): Python is generated from the TypeScript and answers Node's; the suite case is an ordinary agreeing case with a per-side literal.** Was RULED AS NODE until J88-2. Python before: `tokenledger` reads with `read_text()`, universal-newline text mode, so a CRLF file is 2 lines and a lone CR between two records is a line break (2 requests). Node (and Python after): split on `\n` alone, so the blank `\r` of a CRLF file is one `unparsed-line` (3 lines, still 2 requests, since a trailing `\r` is JSON whitespace) and a lone CR leaves one unparsed line (0 requests). Why Node: the host writes LF, and `LogSegment` already splits on `\n` alone on both sides; no earlier row rules this reader's newlines (#150 is the leading-BOM ruling, unaffected). Cases: two `ruling: G2 as Node — read: …`, the unruled `J88-1 read: CRLF line endings — both count the two requests`, and Node's counts in `LITERAL: G2 ruled as Node — node's counts over the ruled inputs`. **J88-2 makes it agree**: Python is then compiled from the TypeScript and inherits Node's answer, the `ruling:` case goes STALE by design and J88-2 turns it into an ordinary case and closes this row. |
| G2 as Node: a line nested 100000 deep (J88-1 #23, #27; J88-1F, #316 G2) | **CLOSED BY G2 (J88-2): Python is generated from the TypeScript and answers Node's; the suite case is an ordinary agreeing case with a per-side literal.** Was RULED AS NODE until J88-2. Python before: `json.loads` raises `RecursionError`, which neither `tokenledger.read` nor `LogSegment._load` catches, so `token_ledger` fails past its handler (which catches `TokenLedgerError`, `PriceTableError`, `OSError`) and `LogSegment.read`/`fold` raise where the module promises not to. Node (and Python after): `JSON.parse` reads the array, so `tokenledger` counts one `not-an-object` and `LogSegment` skips it in `read` (`skipped` 1) and drops it in `fold`. **J88-2's `JSON.parse` lowering must parse this depth without recursing**, or the generated Python still raises and this row cannot close. Cases: `tokenledger`'s `ruling: G2 as Node — read: a line nested 100000 deep`, `storage-log`'s `ruling: G2 as Node — J88-1 a line nested 100000 deep — every op`, and Node's answers in both suites' `LITERAL: G2 ruled as Node — …`. **J88-2 makes it agree**: Python is then compiled from the TypeScript and inherits Node's answer, the `ruling:` case goes STALE by design and J88-2 turns it into an ordinary case and closes this row. |
| G2 as Node: a ledger root past NAME_MAX (J88-1 #25; J88-1F, #316 G2) | **CLOSED BY G2 (J88-2): both now refuse with the `TokenLedgerError` sentence; the refusal-bit companion stays.** Was RULED AS NODE until J88-2 — a refusal on both sides, with different words. Python before: `Path.exists()` raises `OSError(ENAMETOOLONG)` out of `read`. Node (and Python after): `existsSync` answers false and `read` refuses with the `TokenLedgerError` sentence `no such directory: <root>`, which the MCP handler already answers. Cases: `ruling: G2 as Node — read: a root whose name is longer than NAME_MAX`; the refusal bit compared unruled by `J88-1 read: a root longer than NAME_MAX — both refuse`; Node's `{refuses: 'TokenLedgerError'}` in `LITERAL: G2 ruled as Node — node's counts over the ruled inputs`. **J88-2 makes it agree**: Python is then compiled from the TypeScript and inherits Node's answer, the `ruling:` case goes STALE by design and J88-2 turns it into an ordinary case and closes this row. |
| G2 as Node: a transcript subdirectory that lists but does not search (J88-1 #26; J88-1F, #316 G2) | **CLOSED BY G2 (J88-2): Python is generated from the TypeScript and answers Node's; the suite case is an ordinary agreeing case with a per-side literal.** Was RULED AS NODE until J88-2. A directory under `root` with read but no execute permission. Python before: `Path.is_dir()` raises `PermissionError(EACCES)` out of `_walk`, so `read` raises. Node (and Python after): `statSync`'s throw is caught, the child is taken for a file, and its read fails as one `undecodable-file` omission — the ledger's rule that nothing about the tree's content refuses (`docs/ledger.md`). The two refusal bits DIFFER (one side raises), so no side-to-side bit can be green; Node's answer is pinned per side instead. Built only off Windows and not as root. Cases: `ruling: G2 as Node — read: a subdirectory that can be listed but not searched` and `LITERAL: G2 ruled as Node — node's counts over the ruled inputs`. **J88-2 makes it agree**: Python is then compiled from the TypeScript and inherits Node's answer, the `ruling:` case goes STALE by design and J88-2 turns it into an ordinary case and closes this row. |
| G2 as Node: fold timestamp order (J88-1 #28; J88-1F, #316 G2) | **CLOSED BY G2 (J88-2): Python is generated from the TypeScript and answers Node's; the suite case is an ordinary agreeing case with a per-side literal.** Was RULED AS NODE until J88-2. `LogSegment.fold` keeps a row older than `older_than` by comparing `ts` strings. Python before: `_is_old` is `str <`, code-point order. Node (and Python after): `isOld` is JS `<`, UTF-16 code-unit order. They part only when one `ts` holds a character above U+FFFF and the other one in U+E000–U+FFFF: folding at U+1F600 reduces 2 lines on Python (U+FFFF and `a`) and 1 on Node (`a`). Every `ts` bantamkit writes is an ASCII ISO stamp. No earlier row rules this order (`tokenledger`'s code-point stamp order, `docs/ledger.md`, is another module and is unaffected). Cases: `storage-log`'s `ruling: G2 as Node — J88-1 fold compares ts by code point or by UTF-16 unit — every op`, its three unruled appends, and Node's bytes in `LITERAL: G2 ruled as Node — node's ops over the ruled scenarios`. **J88-2 makes it agree**: Python is then compiled from the TypeScript and inherits Node's answer, the `ruling:` case goes STALE by design and J88-2 turns it into an ordinary case and closes this row. |
| G2 as Node: an integer past 2**53 in a folded row (J88-1 #29; J88-1F, #316 G2) | **CLOSED BY G2 (J88-2): Python is generated from the TypeScript and answers Node's; the suite case is an ordinary agreeing case with a per-side literal.** Was RULED AS NODE until J88-2. A row read off disk and re-serialised by `fold`. Python before: `18446744073709551616`, exact. Node (and Python after): a JS number, `18446744073709552000` (the J87-1F rule: a figure is a double). Not the J69-4 caller-float class: the integer was read off disk, not handed in by a caller. Cases: `storage-log`'s `ruling: G2 as Node — J88-1 a folded row holding an integer past 2**53 — every op`, its unruled ops, and Node's bytes in `LITERAL: G2 ruled as Node — node's ops over the ruled scenarios`. **J88-2 makes it agree**: Python is then compiled from the TypeScript and inherits Node's answer, the `ruling:` case goes STALE by design and J88-2 turns it into an ordinary case and closes this row. |
| G2 target-specific I/O: a Python `str` path holding U+DC80..U+DCFF (J88-RF F4b, #316 G2) | **the Python side hands a path to the OS as Python's own `os` functions encode it; ruled (J88-RR R1): `--suite eventlog` `ruling: bed: a surrogateescape code point in the directory (U+DCFF)` pins the difference on POSIX, and its companion `... — both stay enabled and neither raises` compares what both still agree on. On macOS APFS refuses the byte, so the Python record is lost (write_failed true) where Node writes a U+FFFD directory.** A POSIX Python caller meets these code points in a path as the surrogateescape stand-ins for the undecodable bytes of a real name (`os.getcwd`, `os.listdir`, `os.fsdecode`): `/x/\udcff` IS the directory `b"/x/\xff"`. The generated log segment and event log reach the OS through `_ts2py_adapters._node_path`, which keeps every code point `os.fsencode` accepts and turns only the rest (a lone surrogate no encoding takes: U+D800..U+DC7F, U+DD00..U+DFFF on POSIX) into the U+FFFD Node's UTF-8 encoding writes. So the log, its `.lock` (the `exclusive` adapter maps its target the same way since J88-RF F4a) and the hand-written store all land in the one real directory, as on main; at `eb929048` the data went to a new U+FFFD directory while the lock stayed in the real one. Node has no such string from its own fs (its names decode to U+FFFD), so a Node caller handing `\udcff` writes a `\ufffd` name where a Python caller writes the byte `0xff`. Windows has no surrogateescape names (`os.fsencode` there takes every lone surrogate, UTF-16 `surrogatepass`), so on Windows `_os_char` maps every lone surrogate to Node's U+FFFD and the two sides agree; measured on POSIX only (no Windows run). Pinned by `test_storage_log.py::test_a_surrogateescape_directory_holds_the_log_and_its_lock` (Linux; APFS refuses the name and the test skips) and, for the lone surrogates both sides map to U+FFFD, `--suite eventlog`'s two `a lone surrogate in the ... is written under U+FFFD` beds. **Applied by J89-1F (#316 G3) to two more surfaces, the same policy and not a second one:** a STORE ROOT holding U+DC80 (Python hands the OS byte 0x80 — APFS refuses it, `MemoryValidationError`, ext4 creates it — where Node saves into `s\ufffdx`; `--suite store` `ruling: G2 target-specific — a store root holding U+DC80 (a surrogateescape byte)`, with the unruled companion `… — a store answer, and only the directory each side names` and Node's answer as a per-side literal), and `storeId` of such a path (Python hashes the real byte, `usage.os_realpath` + `surrogateescape`; Node hashes U+FFFD; `--suite recall-usage` `ruling: storeId — a surrogateescape code point (U+DC80) …` with the companion `… both answer, neither raises`). On POSIX Python's `storeId` of `s\ud800x` and `s\udc80x` now differ (two directories, two ledgers; both raised before) — `LITERAL: J89-1F python storeId of U+D800 and U+DC80 — both answer and differ`. |
| G2 adapters: two hand-crafted `.gz` segments (J88-RF F5, #316 G2) | **pre-existing, and neither runtime writes such a file; documented, not changed.** `gunzipSync` and the `gunzip_sync` adapter (`gzip.decompress` with Node's refusals) agree on the nine shapes `RULES.md` lists, but not on two: a member followed by zero bytes and then a non-zero byte (`m + b"\0\x01"`) is read by Node as that one member (Node's gunzip ends the input at a zero byte after a member) and refused by Python (`skipped` 1: `gzip.decompress` skips the zero padding and refuses the byte after it as a header), and a member, a zero byte, a second member (`m + b"\0" + m`) is ONE member to Node and both to Python. The hand-written module at main used `gzip.decompress` too, so this is not a G2 change. Rotation writes one `gzip` member and nothing after it on both sides. Measured by the J88-R reviewer's `gz.py` over 13 shapes, 11 equal. |
| `factfile` — a `__proto__` key in a fact's frontmatter, top-level or nested (J87-R F1, J89-1 D1; J89-1F, #316 G3) | **WAS a difference — fixed in Node; now agreeing, so no ruling.** Before: `parseFrontmatter` assigned `meta[key] = value` and `scanNestedMapping` built its mapping the same way, so on Node a top-level `__proto__: polluted` was a [[Set]] of the prototype (a string is ignored, the key vanished) and a nested `  __proto__: inner` vanished too; CPython's dict keeps both as keys. A save that UPDATES the fact writes `Fact.extra` back, so Node dropped both lines from a hand-edited file — data loss. After: both mappings (and `wellFormedMeta`'s rebuild) are made by `Object.fromEntries` over the entries in file order (own data properties; a repeated key keeps its first place and last value, as assignment did), which ts2py lowers as `_js_object_from_entries`, so the generated Python (`_generated/factfile.py`, regenerated) answers as before. Pinned by `--suite store`: `J89-1F a save over a fact with __proto__ keys — the tree` and the per-side `LITERAL: J89-1F <side>'s updated fact keeps the top-level and the nested __proto__ lines`; red at 64a69df8 (the J89-1 case was ruled-different there). |
| `candidates_done` and dream's `absolutise` — a word next to U+0345 COMBINING GREEK YPOGEGRAMMENI (J89-1 D2; J89-1F, #316 G3) | **WAS a difference — fixed in Node; now agreeing, so no ruling.** Before: Node spelled CPython's `\b` as `(?<![\p{L}\p{N}_])` / `(?![\p{L}\p{N}_])` in regexes compiled with `iu`; under `i` a class matches every code point whose simple case fold is in it, and U+0345 folds to iota, so `doneͅ` and `yesterdayͅ` had no boundary on Node (no done-word, no annotation) where CPython's `\w` (never case-folded; U+0345 is Mn) keeps it. After: both patterns (`store.ts` `DONE_WORD_RE`, `dream.ts` `RELATIVE` and `UNRESOLVED`) are compiled with `u` and WITHOUT `i`; the word class is `pysem.PY_WORD_CLASS` and the words are spelled by `pysem.pyCaseless`, which reproduces exactly what `iu` matched for each letter (swept: U+212A for `k`, U+017F for `s`). Swept over 0..0x10FFFF against CPython 3.12 (UCD 15.0): the class disagrees with `\w` on no code point CPython assigns (it did on one, U+0345); the 9,661 left are code points UCD 15.0 leaves unassigned and Node's ICU assigns. **Found while sweeping, then FIXED IN NODE by J89-2 (the orchestrator's ruling: Python is the reference for its own regex semantics):** CPython's `re.IGNORECASE` also matches U+0130 and U+0131 for `i` (JS `iu` does not), so `shıpped` was a done-word to Python only; `pysem.pyCaseless` now spells `i` as `[iIİı]` (swept: every code point 0..0x10FFFF for all 26 letters against CPython 3.12, no other letter has a partner JS's `iu` lacks). Pinned by `--suite store` `J89-2 candidates_done: "shipped" spelled with U+0131 / U+0130` and their node literals, and `--suite dream` `J89-2 absolutise: …` (`rıght now`, `next tİme`); red at b3e570be. **It exposed one more difference, pinned UNRULED (J89-2):** `tonight` spelled with U+0131 or U+0130 is now matched by both, and the reference then raises `KeyError` from its day table (`'tonıght'` is not a key), where node reports the term unresolved (`--suite dream` `ruling: UNRULED DIVERGENCE absolutise: \`tonight\` spelled with U+0131 (dotless i)` and two per-side literals); python raised there before J89-2 as well. **RULED on J89-5 (node is right) and FIXED BY GENERATION in J89-5c:** the generated dream runs dream.ts's lookup, so python reports the term unresolved too; the case is an agreeing `J89-5c absolutise: …` case with per-side literals, joined by U+0130 and by `yeſterday` (U+017F, the same lookup, never pinned before). Pinned by `--suite store` (`J89-1F candidates_done: "done" followed by U+0345`, its node literal, and `J89-1F the word class over every code point CPython assigns`) and `--suite dream` (three `J89-1F absolutise: …` and six per-side `LITERAL: J89-1F <side> finds the term …`); U+0345 is back in `g3pure.mjs`'s fuzz alphabet. |
| a fact write cut short (EFBIG, ENOSPC) — the sentence raised (J89-1; J89-1F, #316 G3) | **WAS a difference — fixed in Node; now agreeing, so no ruling.** Before: Node wrote the temp with one `writeFileSync`, and `asPyOSError` over its error kept libuv's text (EFBIG was not in the strerror table) and the temp's path: `[Errno 27] EFBIG: EFBIG: file too large, write: '<temp>'`. CPython's buffered `write` raises with no filename: `[Errno 27] File too large`. After: `pyfs.pyWriteTextAtomic` opens (`wx`), writes and closes as three steps, as CPython does; only the open's error names the temp, and EFBIG is in the table (`File too large`, the same on the UCRT). An `index.md` write cut short by ENOSPC said `[Errno 28] No space left on device: '<root>/index.md'` on Node and no filename on Python; it now says the latter on both (tmpfs probe below). Pinned by `--suite store` `J89-1F a fact write cut short by EFBIG — the sentence raised` and `LITERAL: J89-1F node raises a fact write cut short by EFBIG as CPython does`. |
| `index.md` and `save`'s budget rollback rewritten in place (J89-1 shared weakness; J89-1F, #316 G3) | **WAS the same weakness on both sides — fixed in both; agreeing before and after.** Before: `_rebuild_index` / `rebuildIndex` wrote `index.md` with `write_text` / `pyWriteText`, and `save`'s rollback after `MemoryBudgetExceeded` rewrote the fact the same way: truncate, then write. A write cut short left a PREFIX: measured at 64a69df8 under `ulimit -f 4`, `index.md` went from 3,800 bytes to the first 4,096 of the new index and the 6,000-byte fact the rollback was restoring to its first 4,096 bytes, on both sides. After: both go through a per-writer temp and a rename, exactly as the fact write does (`<path>.<pid>.<8 hex>.tmp`, `O_EXCL`, every byte written — Node loops over `writeSync`, G2's `writeAll` lesson; CPython's buffered writer loops itself — unlink on any failure): Python `store._write_text_atomic`, Node `pyfs.pyWriteTextAtomic`, and `_write_fact` / `writeFact` now call the same helper. A failed `index.md` write leaves the old file byte for byte; a failed rollback leaves the whole updated fact (never a prefix) and raises the write's `OSError`. Measured under ENOSPC too, in a 1 MiB tmpfs (Docker, CPython 3.13 and Node 22): at 64a69df8 `index.md` 3,800 -> 4,096 bytes on both; now unchanged on both, no temp left. Pinned by `--suite store`: `J89-1F a save whose index.md write is cut short — answer and tree`, `J89-1F a budget rollback whose fact write is cut short — answer and tree`, and four per-side `LITERAL: J89-1F <side>: …`. **Residual, not measured:** on Windows a rename onto a file another process holds open without `FILE_SHARE_DELETE` fails, so `index.md` now shares the fact write's exposure there (no Windows run). |
| `storeId`, `skills._same`, `component._same_directory` — a dangling symlink, and a path below one (J89-1; J89-1F, #316 G3) | **WAS a difference — fixed in Node; now agreeing, so no ruling.** Before: Node resolved with `fs.realpathSync.native` and, on a throw, the parent resolved plus the name (`usage.ts`, `skills.ts`), or a lexical `path.resolve` (`component.ts`); the native call is strict, so a dangling symlink kept the LINK's own name where `os.path.realpath` follows it to the target text: one store had two usage ledgers, and a project under a dangling link to the home was two skill roots on Node, one on Python. After: all three call `pyfs.pyRealpath`, the port of `os.path.realpath(strict=False)` written once (`posixpath._joinrealpath` + `abspath` on POSIX; the `ntpath` non-strict arm `pyResolve` already used on Windows, unmeasured there), meant to be the `realpathSync.native` adapter's contract when these modules are generated. It also keeps the caller's spelling of a case-folded macOS name, as CPython does, where `realpath(3)` answered the filesystem's. Pinned by `--suite recall-usage` (`J89-1F storeId — a dangling symlink`, `— a path below a dangling symlink`, and per-side literals against each side's own target id) and `--suite skill-layer` (`J89-1F skill_roots: a project under a dangling symlink to the home` and its per-side literals). |
| `storeId`, `skills._same`, `component._same_directory` — a lone surrogate outside U+DC80..U+DCFF (J89-1; J89-1F, #316 G3) | **WAS a difference — fixed in Python; now agreeing, so no ruling.** Before: `os.path.realpath` (or the `.encode("utf-8")` after it) raised `UnicodeEncodeError` for `s\ud800x`, out of `store_id` and out of `skill_roots`; Node answered, hashing and comparing the U+FFFD its fs writes. After: Python hands the path over through `usage.os_realpath`, which applies the G2 path policy (`_ts2py_adapters._os_char`: a code point `os.fsencode` cannot take is U+FFFD) before `os.path.realpath`, and hashes `encode("utf-8", "surrogateescape")`; so both hash U+FFFD. Pinned by `--suite recall-usage` `J89-1F storeId — a lone surrogate` and `--suite skill-layer` `J89-1F skill_roots: a home holding a lone U+D800`. The surrogateescape range is the target-specific row below. |
| ~~G3 as Node~~: a store root holding a lone surrogate outside U+DC80..U+DCFF (J89-1; J89-1F; **closed by J89-4b**, #316 G3 U2) | **WAS RULED AS NODE — now agreeing, so no ruling.** Before generation Python raised `UnicodeEncodeError` (`surrogates not allowed`) from the first `mkdir` and wrote nothing, where Node's fs wrote U+FFFD and saved at `<base>/s�x`. Since J89-4b the generated store reaches the OS through the `pyfs` adapters, which take the G2 path policy (`_store_path` in `tools/ts2py-bantamkit/adapters.py`: a lone surrogate CPython cannot encode is U+FFFD), and the hot index adapter hands the hand-written index the same path, so both save at `s�x` and recall it (`saved`, recall 1). The `ruling:` case went STALE as designed (`--suite store`, 2 stale, 0 other failures) and is now `J89-4b a store root holding a lone U+D800 — both answer as node (was ruled G3 as Node)` with `LITERAL: J89-4b python's / node's answer for a store root holding a lone U+D800`. |
| ~~G3 as Node~~: a store root holding a NUL (J89-1; J89-1F; **closed by J89-4b**, #316 G3 U2) | **WAS RULED AS NODE — now agreeing, so no ruling.** Before generation Python raised `ValueError: mkdir: embedded null character in path`; Node answered `MemoryValidationError: memory store could not be created: <root>; the directory is not there and this filesystem would not make it, so nothing was written`; both wrote nothing. Since J89-4b a `pyfs` adapter handed a NUL raises the `OSError` `asPyOSError` makes of Node's `ERR_INVALID_ARG_VALUE` (errno 0; `g3_store.rs` `j89_4b_store_os_seam_answers_like_node` pins its text to Node's), so the generated `ensureDirs` answers the store's own sentence on both sides. Cases: `J89-4b a store root holding a NUL — both answer as node (was ruled G3 as Node)` (the whole answer and the directory listing, which replaces the old refusal-bit companion) and a `LITERAL: J89-4b <side>'s answer …` per side. |

**#200 (job70, the touch graph) adds no row to the table above.** Every touch surface is
compared by `touch-log`, `touch-refs`, `touch-turn`, `touch-graph`, `touch-context`, `touch-bound`,
`touch-summary`, `wire`'s `memory-recall-file` session and `storage-index`'s v5 rows, with no
`ruling:` case among them. `use_names` matching a body line spelled like a recall header is
SHARED behaviour, pinned on both sides (`touch-log`, `use names … #06`), not a divergence.
Not compared, because no Windows run exists: whether the two runtimes' realpaths, and so the
touch log's `<repo-id>`, agree on a Windows drive letter (`docs/touch.md`, *What was not done*).

### A tool crash answers `Error executing tool <name>: <exc>` in both runtimes (#274, ruled 2026-11-05)

**Policy, not a divergence: the two runtimes answer alike, so this adds no row to the table above.** A handler that raises answers `isError: true` with the text `Error executing tool <name>: <exc>` on the reference and on the port. The user ruled option (b) of #274 on 2026-11-05: the #268 override stays, and the SDK's bare-envelope policy is declined.

- **Where it lives.** Python: `_Tool.run` in `runtime-py/src/bantamkit/mcpserver.py` (added by #268, PR #273, 9f02ff9) catches the SDK's `UnexpectedToolError` and re-raises `ToolError(f"Error executing tool {name}: {cause}")`. Node: the `Error executing tool ${name}: ${message}` envelope in `runtime-ts/src/mcp/server.ts`, which the Node SDK gives every exception.
- **What `mcp` 2.1+ does instead.** It hides a crash from the client: any exception that is not `ToolError`, `ResourceError` or `MCPError` becomes `UnexpectedToolError("Error executing tool <name>")` with no suffix, and the traceback goes to the server log. That was considered and declined on 2026-11-05.
- **Why.** (1) Both runtimes answer alike, and the suffixed text is what 0.37.2 sent, so no client sees a change. (2) Adopting the SDK policy needs a deliberate-versus-crash split: every Python handler that refuses with `ValueError`/`KeyError` (`memory_recall needs a query or a file.`, the #133 `unknown argument '<key>'; known: …` sentence) would have to be converted to `ToolError` so its text still reaches the client, and the port would need the same split, which the Node SDK does not make for us. (3) The conformance cases below would change on both sides in one job.
- **The trade-off, stated plainly.** The suffix can leak an exception message to the client (for a `KeyError` it is the key, `'id'`). The server's own log already carries the traceback, and `eventlog` records the exception type and no argument value (`test_a_raising_handler_names_the_type_and_leaks_no_argument_value` in `runtime-py/tests/test_eventlog.py`), so the client-visible suffix is the only extra exposure.
- **What pins it.** `node tools/conformance/run.mjs --suite workplan`: `tool/no-id` (a node without `id` answers `Error executing tool work_plan: 'id'`, compared as the whole frame). `--suite wire`: the per-tool `unknown argument '<key>'` refusal cases, the lone-surrogate refusals for `memory_recall` and `memory_save`, and `#200 memory_recall file: PINNED PER SIDE …` (the neither-argument refusal `Error executing tool memory_recall: memory_recall needs a query or a file.`). `--suite mcpreport` pins the `validate_json` envelope. `mcpreport.py`/`mcpreport.ts` parse the prefix with `^Error executing tool ([a-z0-9_]{1,64}):`, so dropping the colon would also change the report.
- **Reversing it** means ruling again, then doing (a) of #274 in both runtimes at once, with cases for both the bare crash and the suffixed refusal.

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

**The URL `--update` asks, and the JSON path it reads the version out of.** PyPI answers
`https://pypi.org/pypi/bantamkit/json` with the version at `info.version`; the npm registry
answers `https://registry.npmjs.org/bantamkit-mcp/latest` with it at the top level as
`version` (measured 2026-09-11: that document is the `latest` dist-tag manifest, 26 keys).
This is a real, deliberate difference and it CANNOT carry a `ruling:` case, because a ruling
is a case that is required to DIFFER and these two never meet in one output — the divergence
produces zero opcodes in any report. So it is pinned PER SIDE instead, by
`update/PINNED PER SIDE: the index each runtime asks, and the document shape it reads` in
`tools/conformance/suites/cli.mjs`, which writes down both URLs, both document shapes and
the 10-second default; and every garbage arm beside it hands the SAME BYTES to both sides,
so the two "the index answered and it was not the index" refusals stay comparable. J46-31,
2026-09-11.

**Amended J65-19, 2026-10-14 (#135): neither runtime fetches a URL of its own any more.** The
version check asks the package manager the install goes through — `npm view --prefix <root>
bantamkit-mcp@latest --json --fetch-retries=0` on the port (the dist-tag's manifest, `version`
at the top level, so the parser is unchanged) and `<sys.executable> -m pip install --dry-run
--no-deps --ignore-installed --retries 0 --disable-pip-version-check -q --report - bantamkit`
on the reference (pip's installation report, format 1, the version at
`install[0].metadata.version`) — so `npm_config_registry`, `.npmrc`, `PIP_INDEX_URL`,
`pip.conf`, `HTTPS_PROXY` and a mirror's auth are honoured by the check exactly as the install
after it has always honoured them. Measured against 0.35.7: with `npm_config_registry` and
`~/.npmrc registry=` set, the port's `fetch` still asked `registry.npmjs.org`. The per-side pin
named above now carries the two COMMANDS and the two document shapes (the reference's
interpreter masked as `<sys.executable>`); `update/every arm asked its package manager through
the seam` compares, unruled, that every arm reached the seam on both sides; and the real
package managers are measured against loopback indexes in `runtime-ts/test/selfupdate.test.mjs`
and `runtime-py/tests/test_selfupdate.py`. `tools/hooks/update-probe.mjs` was NOT changed by this
amendment; it fetched both registries by URL until #201 (job67 J67-9), and now asks through the
same two commands — `selfupdate.indexCommand` / `fetchIndex` from the built port for npm, and the
checkout venv running `bantamkit.selfupdate`'s `index_command()` / `fetch_index` for PyPI.

**Amended J57-5, 2026-09-19: that difference now also has a shape a ruling CAN see.** Since
J57-3 the version each index answered is written into one record on disk, under a key per
registry, and both runtimes read that one file — so the divergence finally meets in an
output and is carried as the `update record's registry key` row in the divergence table
above, with three `ruling:` cases. The paragraph here still stands for the part that never
meets: the URL each runtime asks and the JSON path it reads the version out of remain pinned
per side in `cli.mjs`, because no report contains both.

**A UTF-8 BOM on the update record is NOT a divergence, and there is deliberately no row for
it.** It was a real one for the length of J57-5: the reference opened
`<homedir>/.bantamkit/update-check.json` with `encoding="utf-8"` and `json.loads` refused the
leading BOM by name, so the record was `unreadable` on the Python side, while the port's
`new TextDecoder('utf-8', {fatal: true})` strips a BOM at its default `ignoreBOM: false` and
answered a live `available` — one file, two answers, found by writing the gate and left RED on
purpose rather than hidden. **J57-5b closed it in the runtimes, toward ACCEPTING the BOM**:
`updatecheck.py` reads with `utf-8-sig` and `updatecheck.ts` is unchanged. PowerShell's
`Set-Content` and `Out-File` write UTF-8 WITH a BOM by default, bantamkit must work on Windows,
and a record a reader can plainly act on is not "a shape this reader cannot act on" — which is
this reader's own definition of unreadable. *(Amended 2026-09-21, J62-16; the amendment itself
RESTORED 2026-09-21, J62-22a, after `amendguard check` returned `RECORD-EDITED` on the first
attempt. The sentence immediately above had never been run, and it is FALSE of PowerShell 6+:
measured in `mcr.microsoft.com/powershell:latest`, PowerShell 7.4.2 writes NO BOM from
`Set-Content`, `Out-File`, `>` or `Add-Content`, and `-Encoding utf8` is the alias of
`utf8NoBOM`; only `-Encoding utf8BOM` produces one. Windows PowerShell 5.1 is UNMEASURED — it
needs a Windows kernel this machine does not have. What has to be accepted is the three bytes
`EF BB BF`, whoever wrote them, and the four arms below never depended on the writer. J62-16's
first attempt deleted the corrected sentence from the body to make room for this clause; it is
back verbatim and the correction now only ADDS, because an addition destroys no record.)*
It is **not** a `ruling:`, because a ruling asserts a
difference somebody chose and after J57-5b there is no difference left to assert; the four
`available/utf-8-bom`, `current/utf-8-bom`, `ahead/utf-8-bom` and `unreadable/bom-not-json` arms
in `tools/conformance/suites/updatecheck.mjs` are compared in every table like any other shape,
and they are what proves it. Note that this is a DIFFERENT question from the `json.loads` BOM
refusal ported in `pyDecodeUtf8` above: that port reproduces CPython's refusal inside the JSON
codec, and it stands. This reader strips the BOM before either JSON parser sees the text.

**`--update`'s dispatch: which stream each outcome lands on, and the exit code.** The
sentences are compared for all 25 arms of `selfupdate.update` and so is the refusal BIT,
which is the dispatch's only input. Until J51-6 the mapping from that bit to a stream and an
exit status — stdout + exit 0 for an answer already true, `error: <sentence>` on stderr + exit
1 for everything else including the shapes this flag will not touch — was NOT compared across
runtimes, and this paragraph gave the reason: `runUpdate` took its install shape from
`currentInstall()` with no seam, and this harness does not install its two sides alike, so the
comparison would have compared two ENVIRONMENTS rather than two implementations — the trap
`tools/conformance/ref/install_ref.py` names in its own docstring. **That reason expired at
J51-5 (`01cee52`)**, which gave `runUpdate` an `install` option (default `currentInstall`), so
the port's shape can be handed in. The reference's `_run_update` still takes no arguments; it
is reached by replacing `mcpserver.current_install`, `mcpserver._version` and
`selfupdate.update` (bound to a stub `fetch` and `installer`) for one call — the idiom
`runtime-py/tests/test_selfupdate.py` already uses on the same function, and no product
surface: there is still deliberately no environment variable on either runtime that redirects
the lookup. So the `cli` suite's `update-dispatch/…` block now drives both dispatchers over
eight arms with the shape, the index, the installer and HOME handed in on both sides, and
compares, unruled, the stream and the exit code of every arm but one side to side
(`update-dispatch/<arm>: the stream and the exit code, side to side`), both streams byte for
byte on the three arms that carry no ruled sentence (`up-to-date`, `offline-unreachable`,
`undetermined`), and every arm's exit code per side against a literal. The one arm that
differs is J51-5's kept-install arm, ruled in the AS-7b `ephemeral` row above. The ORDER half of
the dispatch is gated too, as before, by `mcp-report-then-update`: an argv naming both flags
prints the report, writes nothing and never reaches the network on either side. J46-31,
2026-09-11; amended J51-6, 2026-09-15.

**`promptFingerprint.chars` counts different units (job62, J62-3 / J62-9).** The
`UserPromptSubmit` hook arm logs `{sha256, chars, bytes}` for the prompt it answered.
`chars` is `String.prototype.length` on the port and `len(str)` on the reference — UTF-16
code units against code points — so the two agree on everything below U+10000 and part
company on astral characters. MEASURED 2026-09-20 with one probe per side over a prompt
carrying three emoji: the `sha256` is identical and `bytes` is 46 on both, and `chars` is
**40 on the port against 37 on the reference**. It is the same code-unit/code-point class as
the 600/400 cut in the divergence table above, and the same repair would close both — but
unlike that one it never leaves the log, so no conformance case compares it and none can
without the suite reading a hook log field nothing else reads. Named here rather than ruled,
because a `ruling:` would assert the difference is PERMITTED and it is not: it is a defect
whose surface happens to be private. A green `--all` says nothing about it.

**AMENDED 2026-09-20 (job62, J62-10, review): the last four sentences above are wrong, and a
green `--all` now DOES say something about it.** Two things were wrong. *"No conformance case
compares it and none can without the suite reading a hook log field nothing else reads"* —
`tools/conformance/suites/hooks.mjs` already reads hook log records for every case it has
(`runHook` returns them), so the obstacle named was not an obstacle. And *"a `ruling:` would
assert the difference is PERMITTED"* is not how this repository's rulings read: rows 7 and 8
of the table above are ruled and both say in their own text that they are bugs recorded
rather than endorsed. Ungated, the paragraph was exactly the thing this job set out to stop —
a parity claim nobody could rerun. The case exists as of this unit:
`hooks/prompt-fingerprint: chars — code points against UTF-16 code units`, ruled, with an
unruled companion over `sha256` and `bytes` and per-side literals at **62 code points on the
reference against 65 UTF-16 units on the port**. RE-MEASURED here over a 62-code-point prompt
carrying three astral characters: `sha256` identical, `bytes` **71** on both. The earlier
figures (40/37, `bytes` 46) were a different probe string and are left as written. Three red
shapes were run before this was committed: the repair on the port alone reddens the ruling as
STALE and the port literal; the repair on BOTH reddens the ruling and the reference literal;
and a port that changes what it hashes reddens the unruled companion while the ruling stays
green.


## Defects registered against `runtime-py`, not fixed here

A row here is a defect the reference has and the port does not get to fix — either because
closing it is out of the porting unit's layer, or because the port's job is to REPRODUCE the
reference and the disagreement is with CPython rather than with Node. Found while porting:

1. Windows index-budget arithmetic — 13537 bytes on disk against 13472 checked. (The port
   now reproduces it rather than avoiding it; the reference's arithmetic is still the one
   that is wrong, and it is still not fixed here.)
2. `validate_json` lets `SchemaError` / `TypeError` escape. (`_WrappedReferencingError` no
   longer reaches it: job65 answers a pointer to nowhere and an unknown anchor as a sentence,
   and refuses a reference outside the one resource before `validate` runs.)
3. `shiftwork._read_valid` does not catch `UnicodeDecodeError`.
4. `_pinned_store`'s docstring states a false reason.
5. A `pattern` regex divergence. (Closed by job65, #131: the port translates `re`'s grammar,
   and the constructs it cannot translate are refused by both runtimes with one sentence.)
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

**Amended job73 C2 (#206):** `runtime-ts/src/client.ts` now exists, so the command above prints fourteen names and `client` drops out of it. The port is a SUBSET (the drafter's chat call only); the `client` row in the divergence table above says what is not ported, and the `client` row in the verdict table below is kept as the record of why the rest stays unported.

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

## Generated modules: `workplan`, the fact-file codec, `pricing`, `jobbudget`, the event log, the token ledger, the log segment, the usage ledger, retrieval, the memory store, the native layer, the queries sidecar, the layers, the dream, the component, the storage lock, the hot index, the cold index, retention and the capability tiers are compiled from TypeScript (#314, #315, #316 G1, G2, G3, G4)

Since #314 (J85-3) the Python work planner is not a port. `runtime-ts/src/workplan.ts` is the
one source; `tools/ts2py` (Rust, `tools/ts2py/SUBSET.md`) compiles it to
`runtime-py/src/bantamkit/_generated/workplan.py`, with its JS-semantics support in
`_generated/_ts2py_runtime.py`. `bantamkit/workplan.py` is a 50-line shim that keeps the public
names (`plan`, `touches_refusal`). The hand-written 311-line planner is gone;
`tools/conformance/ref/workplan_ref.py` still imports `bantamkit.workplan` and so now runs the
generated code.

**Every generated file is committed**, so `pip install`, `python -m build` and the wheel need no
Rust. After any edit to `workplan.ts`, `memory/pyyaml.ts`, `memory/factfile.ts`, `pricing.ts`,
`jobbudget.ts`, a G2/G3/G4 module (`memory/store.ts`, `memory/native.ts`, `memory/queries.ts`, `memory/layers.ts`, `memory/dream.ts`, `memory/component.ts`, `storage/lock.ts`, `storage/hotindex.ts`, `storage/coldindex.ts`, `storage/retention.ts`, `storage/tiers.ts` and `storage/index.ts` among them) or `tools/ts2py`, regenerate from the repository root (all five; each is
deterministic, so an unchanged input rewrites the same bytes):

```
cargo run --release --manifest-path tools/ts2py/Cargo.toml -- --config tools/ts2py-bantamkit/ts2py.toml runtime-ts/src/workplan.ts \
  -o runtime-py/src/bantamkit/_generated/workplan.py --runtime-module ._ts2py_runtime
cargo run --release --manifest-path tools/ts2py/Cargo.toml -- --config tools/ts2py-bantamkit/ts2py.toml \
  runtime-ts/src/memory/pyyaml.ts runtime-ts/src/memory/factfile.ts \
  --out-dir runtime-py/src/bantamkit/_generated --runtime-module ._ts2py_runtime
cargo run --release --manifest-path tools/ts2py/Cargo.toml -- --config tools/ts2py-bantamkit/ts2py.toml \
  runtime-ts/src/pricing.ts runtime-ts/src/jobbudget.ts runtime-ts/src/storage/logsegment.ts \
  runtime-ts/src/eventlog.ts runtime-ts/src/tokenledger.ts runtime-ts/src/memory/usage.ts \
  runtime-ts/src/memory/retrieval.ts runtime-ts/src/memory/store.ts runtime-ts/src/memory/native.ts \
  runtime-ts/src/memory/queries.ts runtime-ts/src/memory/layers.ts runtime-ts/src/memory/dream.ts \
  runtime-ts/src/memory/component.ts runtime-ts/src/storage/lock.ts runtime-ts/src/storage/hotindex.ts \
  runtime-ts/src/storage/coldindex.ts runtime-ts/src/storage/retention.ts \
  runtime-ts/src/storage/tiers.ts runtime-ts/src/storage/index.ts \
  --out-dir runtime-py/src/bantamkit/_generated --runtime-module ._ts2py_runtime
cargo run --release --manifest-path tools/ts2py/Cargo.toml -- --config tools/ts2py-bantamkit/ts2py.toml \
  --emit-runtime runtime-py/src/bantamkit/_generated/_ts2py_runtime.py
cargo run --release --manifest-path tools/ts2py/Cargo.toml -- --config tools/ts2py-bantamkit/ts2py.toml \
  --emit-adapters runtime-py/src/bantamkit/_generated/_ts2py_adapters.py
```

`--config tools/ts2py-bantamkit/ts2py.toml` is bantamkit's host file (#337): the compiler in
`tools/ts2py` is its own package and holds no bantamkit name, so the adapter rows, the adapter
module (`tools/ts2py-bantamkit/adapters.py`) and the names the headers print come from that file.
Without it every import of a module outside the call is refused.

(`~/.cargo/bin/cargo` when cargo is not on PATH.) Output is deterministic, so an unchanged
source regenerates byte-identical files.

**Two gates.** `runtime-py/tests/test_ts2py_fresh.py` fails when line 2 of a committed module,
`# source-sha256: <hex>`, no longer equals sha256 of its TypeScript (`workplan.py` ↔
`workplan.ts`, and since #315 `pyyaml.py` ↔ `memory/pyyaml.ts`, `factfile.py` ↔
`memory/factfile.ts`, and since #316 G1 `pricing.py` ↔ `pricing.ts`, `jobbudget.py` ↔
`jobbudget.ts`), when the committed runtime differs from `tools/ts2py/python/ts2py/runtime.py`, when
the committed adapters differ from `tools/ts2py-bantamkit/adapters.py` with its runtime import filled
in (both in their SHIPPED form since J90-P2: `--emit-runtime` / `--emit-adapters` leave the
full-line comments and the docstrings in the source, statement for statement the same code,
`tools/ts2py/tests/shipped.rs` and `tools/ts2py-bantamkit/tests/shipped_adapters.rs`; the test spells the same rule), or when `_generated/` holds a `.py` the test does not name. Every failure message prints the
commands above. It needs no Rust. (J86-3 proved each red once: one byte appended to `factfile.ts`,
a line appended to the committed adapters, a stray `_generated/stray.py`; 3 failed, 6 passed.) `node tools/conformance/run.mjs --suite ts2py` recompiles the
TypeScript fresh on every run and compares Node, the fresh module and `bantamkit.workplan`
against the 148 expected answers in `tools/conformance/fixtures/workplan-cases.json`, with no
rulings. `runtime-py/tests/test_workplan.py` reads the same file. Since J85-5 the same suite also
compiles with the committed flags (`--runtime-module ._ts2py_runtime`, `--emit-runtime`) and
byte-compares the output with the committed files, so a hand-edited body, or a change to
`tools/ts2py` that was never regenerated, is red with the regenerate command; the sha256 header
alone could not see either. Since #315 (J86-3) that covers EVERY generated file: `workplan.py`,
`pyyaml.py`, `factfile.py`, `_ts2py_runtime.py` and `_ts2py_adapters.py`, each compiled with the
flags above, and `committed/coverage` lists `_generated/` so a committed file without a fresh
compile (or the reverse) is red. Proved red once: a line appended to the committed `pyyaml.py`
and a stray `_generated/stray.py` failed `committed/pyyaml.py` and `committed/coverage` (2 of
452 cases). Since J90-RF (F2) the pytest file makes the same body compare when cargo is present (on PATH
or at `~/.cargo/bin/cargo`): it runs the five commands into a scratch directory and compares every
committed module byte for byte (`test_generated_body_is_what_ts2py_writes[<module>]`), so a
hand-edited body is refused by both gates, as CLAUDE.md says; without cargo those 26 tests skip
with that reason and the header tests still run. Proved red on a hand edit of
`_generated/retention.py` whose header still matched (1 failed, 72 passed).

**Python-side behaviour changes, all toward Node.** The hand-written planner disagreed with the
TypeScript on 8 fixture cases, which J85-2 carried as `ruling:` cases (`KNOWN_LEGACY_FINDINGS`,
now deleted). The switch fixes each one on the Python side. The Node side does not move:

| Case | Python before | Python now = Node |
|---|---|---|
| `ts/shape-no-id` (library `plan`) | raised `KeyError: 'id'` | refusal `nodes[0].id must be a string` |
| `adversarial/touches/1e21` | sentence printed `1000000000000000000000` (Python `repr`) | `1e+21` |
| `adversarial/touches/1e-7` | printed `1e-07` | `1e-7` |
| `adversarial/touches/object-nested-floats-and-keys` | nested `3.0` kept as `3.0`; keys in insertion order | `3`; array-index keys first, as `JSON.stringify` orders them |
| `adversarial/touches/object-array-index-keys` | keys in insertion order | array-index keys first, ascending (`"2"`, `"10"`, then `"b"`) |
| `adversarial/touches/object-in-list` | nested `1.0` printed `1.0` | `1` |
| `adversarial/priority/2^53-plus-one-ties-in-js` | `9007199254740993` outranked `9007199254740992` (exact ints) | they tie as doubles; insertion order decides |
| `adversarial/touches/int-beyond-2^53` | printed the exact `12345678901234567890` | the rounded double `12345678901234567000` |

The `work_plan` MCP tool still raises `KeyError('id')` for a node with no `id`
(`--suite workplan` `tool/no-id`, `test_sdk_wire_text.py`). `mcpserver.py`'s handler maps the
planner's `nodes[<i>].id must be a string` back to that `KeyError` when node `<i>` is a dict
with no `id` key. The planner stops at the first faulty node, which is where the old
`node["id"]` raised, so the tool's answer is unchanged for every input.

**One `work_plan` change on the Node side (J85-5, review finding F5, older than #314).** The
reference read `node["id"]` inside its shape pass, in input order, so a fault in an EARLIER node
was the answer and a later node's missing `id` was never reached. `runtime-ts/src/mcp/server.ts`'s
`planNodes` instead checked every node for an `id` before the planner ran, so the port raised
`Error executing tool work_plan: 'id'` where the reference refused the earlier node. Node was the
wrong side (its own comment says it reproduces the reference) and is fixed: it now maps the
planner's `nodes[<i>].id must be a string` back to the raise only when node `<i>` is a dict with
no `id`, the seam `mcpserver.py` uses. Python does not move. Pinned by four `--suite workplan`
cases, red against the old port on the first three:

| Input (`nodes`) | Node before | Both now |
|---|---|---|
| `[{id:'a', depends_on:5}, {depends_on:[]}]` (`tool/no-id-after-depends_on-fault`) | raised `'id'` | `nodes[0].depends_on must be a list of strings` |
| `[{id:7}, {depends_on:[]}]` (`tool/no-id-after-int-id`) | raised `'id'` | `nodes[0].id must be a string` |
| `[{id:'a', touches:'x'}, {depends_on:[]}]` (`tool/no-id-after-touches-fault`) | raised `'id'` | `node a touches "x", which is not a plain relative path` |
| `[{depends_on:[]}, {id:'b', depends_on:5}]` (`tool/no-id-before-a-fault`) | raised `'id'` | raises `'id'` (unchanged) |

**Inputs only a Python caller can build.** JSON has no tuples, so neither MCP surface nor
`shiftwork` can produce these. A top-level `tuple` of nodes is still accepted: the shim turns
it into a list, because the old planner took any sequence. `plan(nodes=...)` by keyword still
works. Two cases changed and are recorded here instead of patched: a nested `tuple` for
`touches` used to be refused with a sentence and now raises `TypeError: ts2py: JSON.stringify of
tuple is outside the subset`. A top-level `dict` used to be refused `nodes[0] must be an object`,
because the old planner iterated its keys, and now raises `TypeError` (`.entries() on dict`).
`None` raised `TypeError` before and still does. Two more, found by the J85-R review (F6): a
`tuple` used as a **node** (`plan([("a",)])`) used to be refused `nodes[0] must be an object` and
is now refused `nodes[0].id must be a string`, because the generated code reads a property of a
non-object as `undefined`; and a **generator** of nodes used to return an empty plan
(`{"batches": [], "sequence": [], "width": 0}`, wrongly: the old planner exhausted it in its shape
pass and planned nothing) and now raises `TypeError: ts2py: .entries() on generator is outside
the subset`. The shim stays as it is. The reviewer's judgement, which these four changes rest on:
no caller can produce any of them. The three callers, `shiftwork.py:768`, `shiftwork.py:2093` and
the `work_plan` MCP tool (`mcpserver.py:1817`), all pass a `list` of `dict`s that came from JSON
(`json.loads` of a checkpoint or ticket file, or the MCP request), and JSON has no tuples or
generators.

### The fact-file codec (#315)

Since #315 (J86-3) runtime-py reads and writes fact files through code compiled from
`runtime-ts/src/memory/factfile.ts` and `pyyaml.ts`, the codec the Node server uses:
`_generated/factfile.py` (643 lines) and `_generated/pyyaml.py` (750 lines), which import each
other, the shared `_ts2py_runtime.py` and `_ts2py_adapters.py` (60 lines). The seam is one
hand-written module, `runtime-py/src/bantamkit/memory/factcodec.py`:

- `load_frontmatter(text)` (re-exported from `memory/store.py`, where the hot index, the tests and
  the conformance refs import it) is the generated `parse_frontmatter`, its values converted to
  the ones `yaml.safe_load` builds; `MemoryStore._read_fact` and the hot index read through it.
- `fact_text(fact)` is the generated `format_fact`; `MemoryStore._fact_text` is now that call, so
  `_write_fact`, `dream`'s size estimate and `merge` all write through it.
- The hand-written frontmatter assembly and the `yaml.safe_dump` call that were `_fact_text`, and
  the libyaml / pure-loader pair that was `load_frontmatter`, now exist ONLY as the two fallbacks
  `_pyyaml_fact_text` and `_pyyaml_load`, in that file.

**Generated first, PyYAML where it refuses (user ruling 2026-11-15, #315 option A).** Where the
generated codec refuses a frontmatter (the eight #120 shapes, a mapping two levels down, a quoted
key, any other named refusal) or a fact (a collection appearing twice, which PyYAML writes as an
anchor and alias; an array-index key in a nested map), the file is read by `yaml.safe_load` plus
`well_formed_frontmatter`, or written by `yaml.safe_dump`, exactly as before #315. An EMPTY
generated read also goes to PyYAML: `''` and a comment-only frontmatter read as `{}` there and as
`None` in PyYAML, and the store's sentence for that file is `frontmatter is not a mapping`.
Two more triggers since J86-6 (the J86-R review), each a case where the generated answer cannot be
turned into exactly what `safe_load` builds, so it is not guessed: a frontmatter holding any `\r`
(the generated codec reads `name: on\r` as the text `'on\r'`, PyYAML breaks the line and reads
`True`; the store reads with universal newlines, the seam's other callers need not), and a mapping,
at any depth, in which two raw keys become one native key (`k:\n  yes: 1\n  on: 2\n  yes: 3\n` is
`{True: 3}` to PyYAML, which assigns in file order, and the codec's text-keyed answer had already
merged the two `yes` entries, so folding it gave `{True: 2}`). The read cache keeps only generated
answers and is bounded by 4,096 entries AND 4 MiB of key text (`sys.getsizeof`), emptied when
either is reached; a text over 32 KiB is never kept.

**The adapters, and why each is faithful.** The generated code holds a `PyScalar` where PyYAML
holds an `int`, `bool`, `float`, `date` or `datetime`. `factcodec._native` builds the Python value
from the scalar's type and `str()` text (`int(text)`, `float(text)` of a `repr`,
`date.fromisoformat`, `datetime.fromisoformat` of `isoformat(' ')`, `text == "True"`) and CHECKS it:
the value must print as the scalar's `text`, or the read goes to PyYAML. A key the codec keys by
its text but YAML resolves to a non-string (`on:`, `null:`) is keyed by its PyYAML value, so the
mapping `load_frontmatter` returns is the one `safe_load` returned. Writing, `factcodec._scalar`
spells each Python scalar as `SafeRepresenter` does (`true`, `str(int)`, `represent_float`, `isoformat`)
and hands that to the generated `construct_plain`; the scalar must come back with exactly that
spelling as its `yaml`, or the write goes to PyYAML. A set, bytes, a tuple, a non-text key in a
nested map, a shared collection, or a `date`/`datetime` OBJECT met twice (PyYAML anchors those too:
`ignore_aliases` exempts only `None`, `()`, `str`, `bytes`, `bool`, `int`, `float`) is refused
before the codec sees it, so PyYAML writes its `&id001` exactly as before. The four ts2py adapters
(`pyFloatRepr` = `repr(float)`, `pyStrip` = `str.strip()`, `TextDecoder`, `Date`) are J86-1's, in
`tools/ts2py/RULES.md` (*Adapters*); the store does not call `decode_fact_bytes` or `today_local`.

**What moved, and only this (both toward Node; `before` is runtime-py at `c9a21a12`):**

| Class (`--suite ts2py-codec`) | runtime-py before | runtime-py now = Node |
|---|---|---|
| `yaml11-breaks`: U+0085, U+2028 or U+2029 in a quoted or plain scalar | read as a YAML 1.1 line break: the spaces around it folded (`"x \u2028 y"` read `x\u2028y`), a plain scalar holding one refused (`ScannerError`); 75 fuzz inputs | kept, with the spaces around it; all 75 read as Node reads them. One consequence, Node's since #120 and now runtime-py's: PyYAML writes `x\u2028y` in a hand-written key's value, `links` or `keywords` as `'x\u2028  y'` (its continuation indent), which now reads back `x\u2028  y` — two spaces gained on the first rewrite, stable after (pinned in `test_factcodec.py`). A `description` cannot be saved with one (#155), and a hand-edited one is read with the character as one space either way |
| `pyyaml-refuses`: a raw non-printable character (`a: \x07`), a multi-line single-quoted scalar continued at column 0 by a `---` or `...` marker line (PyYAML: `found unexpected document separator`) | `malformed fact file <name>: unacceptable character #x0007 ...` / `ScannerError`; 23 fuzz inputs, all non-printable (the marker shape is pinned by a classifier probe) | read; all 23 as Node reads them |

**Each class is decided by counterfactual (J86-6, the J86-R review's finding 4).** An input is in a
class only when undoing that class's one cause makes `before` and Node read it alike: every
non-printable character replaced (`pyyaml-refuses`), every column-0 marker line inside the
frontmatter indented one space, which Node must read exactly as before (`pyyaml-refuses`), every
U+0085, U+2028 and U+2029 replaced (`yaml11-breaks`). Until J86-6 any PyYAML refusal Node read was
`pyyaml-refuses` and any value difference in a text holding one of the three characters was
`yaml11-breaks`; the counts moved from 71/27 to 75/23 because four plain scalars that PyYAML
refused only because of a U+0085 or U+2028 are now filed under the cause. A difference with any
other cause is outside the ruling and red: with one fuzz input added whose key is past PyYAML's
1,024-character simple-key limit, the J86-5 classifier passed it as `pyyaml-refuses` (`PASS: 227
cases`) and this one fails it (`fuzz/py=before/outside-the-315-ruling`, `FAIL: 228 cases, 1
failures`). The classifier is pinned on six probes (`ruled-class/classifier-probes`), two of them
third shapes that must stay outside. The marker counterfactual also admits a double-quoted
scalar continued by a column-0 marker (`k: "x\n--- y"`: Node reads `x --- y`, PyYAML refuses): the
same scanner cause as the single-quoted shape the ruling names, so it is read under that ruling. An
input refused for two ruled causes at once (say a raw BEL and a U+0085) falls in neither class and
turns the suite red; no current input has that shape, and the red is a false alarm, never a mask.

Every other answer is unchanged, and the suite holds that: `py=before/outside-the-315-ruling`
(every input whose parse or store round trip moved and is in neither class) is `[]` on the fuzz
(2,700 inputs), the 40 previous-release files and the 802 real-store files on this machine, and
`fuzz/format/py=before` (the 1,200 fuzz facts written by both) is `[]`: no write changed. On
scratch copies of the 802 real files, 6 reads and 0 writes took the PyYAML fallback. The two
classes that stay `KNOWN` (ruled) between runtime-py and Node: `node-refuses` (python reads it
through the fallback, unchanged) and `non-text-key` (no observable effect: both stores drop the
key, and `non-text-key/rt-store/py=node` compares the store round trip unruled, `[]`).
`test_storage_recall_index.py` now holds libyaml's sentence property on `_pyyaml_load` and pins
`a: \x07` as read.

**Not routed through the generated codec (J86-3):** `hookadapter._parse_native_fact` (the native
mirror, #228), `skillfile.parse_skill` and `memory/divergence.parse_fact` keep `yaml.safe_load`.
Each is pinned by its own ruling (`--suite hooks`, `--suite skill-file`); generated-first would
move the two `RULED_315` classes for them too, which is not byte-neutral. **PyYAML stays a
dependency** (`pyyaml>=6.0`): the fact codec's fallback, those three readers, and `contract`,
`profile`, `critique`, `evalrun`, `criticreplay` and `memory/layers` (`config.yaml`) all use it.

**Cost, measured (J86-3, macOS arm64, CPython 3.12.13, PyYAML 6.0.3 with libyaml).** Over the
684 frontmatters of the real stores on this machine, best of 3: generated-first
`load_frontmatter` 830 µs each, the generated `parse_frontmatter` alone 741 µs, the pre-#315 path
(libyaml) 21 µs, pure `yaml.safe_load` 181 µs. `MemoryStore._facts()` over a scratch copy of the
repo store (91 facts): 82 ms against 4.6 ms with the fallback forced. The JS-semantics runtime
(`_js_get`, `_js_strict_eq`, UTF-16 helpers) is the cost; ts2py was out of scope for this unit,
and the number is #316's to budget (`docs/roadmap-1.0.0.md`, #315).

**Superseded by J86-5 (f849c664).** Most of that cost was one quadratic: every `s[i]` and
`s.length` on a non-ASCII string rebuilt the string's UTF-16 view. With exact runtime fast paths
(each checks its own operand types and falls back to the general path otherwise) and a text-keyed
read cache in `factcodec`, a first frontmatter parse costs **145 µs** (517 files, against 21 µs on
libyaml). Every hook, the memory CLI, `memory_recall`, and `memory_save` on a long-running server
are within 20% of pre-#315 at the median (n=7). Three first-read-of-a-store paths are still over,
paid once per process: the first `memory_save` in a process (+16 ms), and the hot and cold index
builds from nothing (+17 ms and +10 ms). Accepted for #315. The remedy is type-directed lowering in
ts2py, carried into #316, with the perf gate re-measured at #317. The full table is in
`docs/roadmap-1.0.0.md`, #315.

### Pricing and the job budget (#316 G1, J87-3)

Since J87-3 `bantamkit.pricing` and `bantamkit.jobbudget` run code compiled from
`runtime-ts/src/pricing.ts` and `jobbudget.ts`: `_generated/pricing.py` (340 lines) and
`_generated/jobbudget.py` (179), from one ts2py call. The hand-written `pricing.py` (411 lines)
and `jobbudget.py` (167) are retired; what is left under those names is a shim (pricing 159
lines, most of it the module's rationale docstring, which `pricing.ts` points readers to;
jobbudget 61). `tools/conformance/ref/pricing_ref.py` and `jobbudget_ref.py` import those shims,
so `--suite pricing` (84 cases) and `--suite jobbudget` (1,149) now compare the generated code
with Node.

**What the shims keep (Python-only conveniences).** `TOKEN_CLASSES` and `DIMENSIONS` stay tuples
(the generated modules hold lists, as the TypeScript does). `load_price_table(path=None)` maps
`None` to the default path and anything else to `str(path)`, so a `pathlib.Path` works.
`validate_price_table`, `price_tokens` and `budget` lift what the generated function returns into
the values a Python caller had, the way Node's `fromJs` lifts the TypeScript's for `dumpJson`
(`_js_py_value` in the runtime: a safe integer is an `int`, any other number a `float`), so
`json.dumps` of an answer is the bytes Node writes. A top-level `tuple` handed to
`validate_price_table` or as `price_tokens`'s usage becomes a `list`, as `workplan`'s shim does,
so it is refused with the sentence it was refused with before. `PriceTableError` is the generated
class itself: it extends the `BantamError` adapter, which is `bantamkit.client.BantamError` with
JS's Error face, so `except BantamError` still catches it and `str(exc)` is the sentence. The
hand-written `jobbudget.BRIEF_EVENT` / `UNCOMMITTED_EVENT` are gone (nothing imported them).

**The adapters (`tools/ts2py-bantamkit/ts2py.toml`, measured in `tools/ts2py/RULES.md`, Adapters).**
Four where Python is the reference: `pyRepr` (`repr(str)`), `cmpCodepoint` (code-point order, what
`sorted()` does), `assetsRoot` (`bantamkit.assets.assets_root()`, which `assets.ts` mirrors) and
`BantamError` (`bantamkit.client.BantamError`, imported lazily so a module that does not use it
does not import `bantamkit.client`). Four Node builtins, each measured against Node 26.13:
`fs.existsSync` (`os.path.exists`; 18 path shapes equal), `fs.readFileSync(p, 'utf8')` (the
bytes decoded with one U+FFFD per maximal invalid subpart; 30,000 random byte strings and 2,000
files equal), `path.join` (Node's `lib/path.js` ported statement for statement; 60,000 random
joins equal on posix, 41,055 on win32 with the 18,945 its colon and device-name rules make refused)
and `process.env` (each runtime reads its own environment).

**The error shape across the fs seam (the #315 unknown).** `readFileSync`'s adapter raises the
`OSError` CPython's `open()` raises for the path, class, `errno`, `strerror`, `filename` and text
alike; a generated `catch` sees it as Node's fs Error, and where the TypeScript rethrows it or does
not catch it the Python caller gets that very exception (`tools/ts2py-bantamkit/tests/g1.rs`,
`fs_errors_reach_python_as_cpython_raises_them`, a missing file and a directory). A `catch`
catches only what JS could have thrown (`_js_catch`): a subset refusal (`ts2py: ...`), a
`RecursionError` or any other Python exception propagates.

**Python-side behaviour changes, all toward Node** (`before` is the hand-written module at
`e6655be7`; each is what `pricing.ts` / `jobbudget.ts` answer, and the first three are new
`--suite pricing` cases, red against the hand-written module):

| Input | Python before | Python now = Node |
|---|---|---|
| `load_price_table(<a directory>)` (`load: a-directory.json`) | raised `IsADirectoryError` | `PriceTableError: price table is not valid JSON: <path>` (the read throws inside the `try`) |
| a table holding an invalid UTF-8 byte inside a string (`load: latin1.json`) | `price table is not valid JSON` (`read_text` is strict) | loads; the byte reads as U+FFFD, as `readFileSync(p, 'utf8')` decodes it |
| a table starting with a BOM (`load: bom.json`) | `price table is not valid JSON` | unchanged (both keep the BOM, both parsers refuse it) |
| `load_price_table('')` | raised `IsADirectoryError` (`Path('')` is `.`) | `price table not found: ` (`existsSync('')` is false) |
| `decode_price_json('3000000.0')` / `('9007199254740993')` | `3000000.0` / `9007199254740993` | `3000000` / `9007199254740992`: `JSON.parse`'s numbers; a malformed text is still a `ValueError` with CPython's decoder message, a `bytes` argument is now outside the subset |
| `validate_price_table({..., 5: 1})` (a non-text key) | `unknown key 5` | `unknown key '5'` (a JS key is a string) |
| `format_micros(-1)`, `format_micros('5')`, `format_micros(1.5)` | `-1.999999`, `TypeError`, `ValueError` | `0.0000-1`, `0.000005`, `RangeError` (a `ValueError`): the function is documented for non-negative ints only |
| `budget(...)` with a float limit or `in_flight`, a refusal over a float view | `affordable` `19.0`, `"spent: 4.0 of 5.0"` | `19`, `"spent: 4 of 5"` (a figure is a double; the J87-1F / J87-1G rows above) |
| `refusal(view)` whose `remaining` lacks a declared dimension | raised `KeyError` | `None` (JS reads `undefined`, which is not short) |
| `load_price_table(<an unreadable file>)` (EACCES, found by J87-R) | raised `PermissionError` | `PriceTableError: price table is not valid JSON: <path>` (the read throws inside the `try`, as for a directory); still refused at `mcpserver` either way |
| hand-built tables outside the contract (`price_tokens` with `rates: {'m': None}`, a rate of `2.5`, `rates: None` / `[]`; `validate_price_table` with a tuple `rates`; `decode_price_json('-0')`), found by J87-R | `no rate recorded` / `AttributeError` / `PriceTableError` / `0` | Node's answer: a JS `TypeError` / `RangeError`, `no rate recorded`, a subset refusal, `-0.0`; a decode error is a `ValueError` but no longer a `json.JSONDecodeError`. The only caller (`tokenledger.py`) passes a validated table, so none is reachable from the product surface |

**Model names `Object.prototype` gives every object: fixed in both runtimes by J87-3F** (found
by J87-3; see the divergence-table row for `pricing` and `Object.prototype` model names).
`pricing.ts` now looks a model up with `Object.hasOwn` and builds `rates` with
`Object.fromEntries`, so the generated Python gives the same answer itself and the shim's
`_inherited_lookup` workaround is gone.

**Tests retired (#316: a duplicate goes once a conformance case covers it).** Each of these
`runtime-py/tests/test_pricing.py` tests had exactly the input of a `--suite pricing` case, and
Node's value for it stays pinned by the same-named test in `runtime-ts/test/pricing.test.mjs`:

| Deleted | Covered by |
|---|---|
| `test_the_units_are_what_they_say` | `the constants are what they are — python` (a literal) |
| `test_the_shipped_table_prices_nothing` | `the shipped table prices nothing — python` (a literal), `load: the shipped table` |
| `test_a_rate_without_a_date_is_refused_at_load` | `table: a rate with no recorded` |
| `test_a_rate_without_a_source_is_refused_at_load` | `table: a rate with no source` |
| `test_a_class_with_no_rate_and_no_tokens_is_not_a_refusal` | `partial rate: an unpriced class with zero tokens` |
| `test_a_usage_with_an_extra_key_refuses_rather_than_ignoring_it` | `full rate: an unknown class` |
| `test_a_half_micro_usd_rounds_up_and_not_to_even` | `a half rounds up, not to even — python` (a literal) |
| `test_format_micros_is_built_from_integers` (8 cases) | `format_micros(0)` ... `format_micros(9007199254740991)`, the same 8 values |
| `test_a_sub_cent_cost_survives_which_is_why_this_is_not_cents` | `full rate: a plain input cost` |
| `test_a_cost_above_two_to_the_53_refuses_rather_than_answering_wrong` | `full rate: a cost above 2**53` |
| `test_true_is_not_the_rate_one` | `table: true as a rate` |
| `test_the_offender_named_is_the_code_point_least_one` | `table: two unknown top keys` |
| `test_a_missing_table_names_the_path_it_looked_at` | `load: nope.json` |
| `test_an_undecodable_table_does_not_quote_the_decoder` | `load: broken.json` |
| `test_a_bare_infinity_is_not_valid_json_here_either` | `load: infinity.json` |

Kept: the Python-only inputs (a Python float count or rate, which the suite never sends because
it decodes JSON text; the env-var route; tuples), `TOKEN_CLASSES` as a tuple, and every test whose
input the suite does not spell. `test_jobbudget.py` keeps all its tests: none has exactly a
`--suite jobbudget` input (their limits and ledgers differ), and they are the per-side pins of the
J87-1F fixes. Four shim tests were added (`BantamError`, a `Path`, tuples, the pending names).

**Cost, measured (J87-3, macOS arm64, CPython 3.12.13; n = 9, medians; before = `e6655be7`,
after = this tree).** A first `import bantamkit` is unchanged (88.2 ms → 88.3 ms; it already
loads the runtime for the codec). The modules' own imports (with `bantamkit` loaded): pricing
0.096 → 0.188 ms, jobbudget 0.078 → 0.127 ms. Warm calls: `price_tokens` 1.5 → 22.3 µs,
`validate_price_table(decode_price_json(...))` of an 8-rate table 21.0 → 155.9 µs,
`refusal(budget(...))` over a 42-line ledger 11.1 → 113.4 µs. Every one is over 20% and every one is
the JS-semantics runtime (`_js_get`, `_js_in`, `_js_put`, the generated BigInt arithmetic), as
#315 found for the codec. What a user meets: `shiftwork.plan_batches` with a budget and a 42-line
ledger 12.49 → 12.76 ms (+2.1%), `load_price_table` + `price_tokens` 0.023 → 0.075 ms.

### The event log, the token ledger and the log segment (#316 G2, J88-2)

Since J88-2 `bantamkit.eventlog`, `bantamkit.tokenledger` and `bantamkit.storage.logsegment` run
code compiled from `runtime-ts/src/eventlog.ts`, `tokenledger.ts` and `storage/logsegment.ts`:
`_generated/eventlog.py` (225 lines), `_generated/tokenledger.py` (468) and
`_generated/logsegment.py` (554), from ONE ts2py call with G1's two modules (the token ledger
imports `pricing` and the event log imports the log segment, and an import between compiled
modules resolves only inside one call; G1's output is byte-identical). The hand-written modules
(354, 489 and 401 lines) are retired; what is left under those names is a shim (221,
257 and 177 lines, most of each the rationale docstring the TypeScript
points readers to). `pyjson`, `pyjsonschema` and `pysem` are not compiled: they are Node's
emulation of CPython (J88-1's reading, confirmed), so the three modules reach them only through
adapters onto Python itself.

**What the shims keep (Python-only conveniences).**

- *Paths are `Path`s.* `LogSegment(path)`, `EventLog(path, requires_dir=...)`, `default_path`,
  `resolve_path`, `tokenledger.read(root, prices=...)` and `write_over` / `rewrite_held` take a
  `Path` or a string and hand the generated code `str()`; `LogSegment.path`, `segments()`,
  `EventLog.path` / `requires_dir`, `default_path` and `tokenledger._walk` answer `Path`s. A literal
  `BANTAMKIT_EVENT_LOG` path keeps its exact spelling: `resolve_path` and `EventLog.path` answer a
  `Path` whose `str()` (and `os.fspath`) is the string as given, trailing `/` and `//` included,
  because the TypeScript opens the string as spelled and a plain `Path` would normalise it (such a
  `Path` is equal to, and hashes as, the plain `Path` of its spelling; a path derived from it, `/`
  or `.parent`, answers as an ordinary one). J88-RF F3: it works on every Python `requires-python`
  admits (it raised `TypeError` on 3.11 and 3.10, where `Path.__init__` is `object.__init__`);
  `test_eventlog.py::test_a_literal_path_keeps_its_spelling_on_every_python`, run on 3.11, 3.12,
  3.13 and 3.14.
- *Python names.* `LogSegment(path, *, wait_ms=None, stale_ms=None, poll_ms=None)` (the
  TypeScript's `{waitMs, staleMs, pollMs}`), `fold_lines`, `.skipped` and `.size`;
  `EventLog(path, cap_bytes, clock, requires_dir)`, `.cap_bytes`, `.requires_dir`,
  `.write_failed`, `from_env(store_root, env=None, clock=...)` (`None` is `os.environ`);
  `tokenledger.read(root, model=None, prices=None)`.
- *`rotate(max_bytes=None)` reads `logsegment.ROTATE_BYTES` when it is called*, so a caller or a
  test that sets the module attribute moves the default (the hand-written default was bound at
  definition time).
- *Tuples are lists.* A tuple in an `append`ed object, a `fold` reducer's rows, `dumps_line` or
  an event `detail` is handed over as a list, as `json.dumps` wrote one; `fold_lines` hands its
  reducer `(row, line)` tuples, as before. An object nested past the recursion limit is handed
  over unconverted, and the generated serialiser refuses it (below).
- *Python-only values are what `json.dumps` made of them (J88-RF F6).* A float subclass (an
  `Enum` over `float`) is its float value, never its `repr`; a dict key that is not a string is
  coerced as `json.dumps` coerces it (`7` -> `"7"`, `2.5` -> `"2.5"`, `True` -> `"true"`, `None`
  -> `"null"`), the same in `dumps_line`, `append` and `encode_record` (the event log dropped such
  a key silently at `eb929048`), and any other key is `json.dumps`'s `TypeError`.
- *The token ledger's answer* is the frozen `Ledger` / `Session` / `Omission` dataclasses built
  from the generated document; `Ledger.as_json()` is the generated `asJson` over `as_dict()` (a
  ledger-shaped document itself); `OMISSION_ORDER` and `DEFAULT_RELATIVE_PATH` stay tuples.
- *`TokenLedgerError` is the generated class*, a `bantamkit.client.BantamError` through the
  `BantamError` adapter, so `except BantamError` and `mcpserver`'s handler still catch it.
- *`EventLog.raised(tool, exc)` records `type(exc).__name__`*, the CPython reference the
  TypeScript's `typeNameOf` reproduces for every exception Node can throw. The generated
  `typeNameOf` would answer `OSError` for an OSError subclass a Python handler constructs with no
  errno, or one whose errno `pyfs.ts`'s eleven-row table omits (`TimeoutError`,
  `ConnectionRefusedError`); the shim keeps the Python class name there.
- `_split`, `_load` and `_is_old` stay importable (`touch/log.py`), now the generated functions.

**The adapters** are in `tools/ts2py-bantamkit/ts2py.toml` and measured in `tools/ts2py/RULES.md`
(*Adapters (J88-2)*): 37 new rows. Node builtins (22): the `node:fs` calls the three modules make
(`statSync`, `lstatSync`, `fstatSync` and `Stats`, `readdirSync`, `mkdirSync`, `renameSync`,
`rmSync`, `linkSync`, `openSync`, `closeSync`, `writeSync`, `readSync`, `appendFileSync`),
`path.dirname` / `basename`, `zlib.gzipSync` / `gunzipSync`, `crypto.randomBytes`,
`Buffer.from` / `concat` / `alloc`, `process.pid`, `process.env` read as a value. Python is the
reference (15): `pyfs.ts`'s `cmpCodepoint`, `pyExists`, `pyIsDir`, `pyJoin`, `pyParent`, `pyName`,
`osErrorClassName` and `PyOSError` (it is the CPython OS seam); `store.ts`'s `bantamkitDirFor` and
`ensureBantamkitGitignore` and `lock.ts`'s `exclusive`, `LOCK_STALE_MS`, `LOCK_POLL_MS`, which G3
and G4 have not generated yet (so the hand-written Python each ports is the function, and
`--suite store` / `--suite storage-lock` compare them). Extended: `TextDecoder` (`fatal`,
`ignoreBOM`: 40,000 byte strings equal), `readFileSync` with no encoding (the bytes),
`existsSync` (a NUL answers false, a lone surrogate is looked up as U+FFFD, as Node).

**The error shape and the writes.** Every fs adapter raises the `OSError` CPython raises for the
call; a generated `catch` sees it as Node's fs Error, reads its `code` as libuv's errno name, and
where the TypeScript does not catch it the Python caller gets that very exception
(`tools/ts2py-bantamkit/tests/g2.rs`, `g2_fs_adapters_answer_like_node`: an uncaught `statSync` failure is
`os.stat`'s own `FileNotFoundError`, class, errno, strerror, filename, args and text). A crash-safe
write is the same order it was: `<target>.<pid>.<hex>.tmp` opened `wx` with mode 0o666, written,
closed, renamed over the target, the temp removed when the rename is refused, and no fsync on
either side (`test_storage_log.py::test_write_over_and_rotate_write_temp_then_rename` and its twin
in `runtime-ts/test/storage-log.test.mjs` trace the calls on each side; the hand-written module
opened the temp without `O_TRUNC`, a no-op with `O_EXCL`). J88-RF F1: every write of a whole buffer (`writeOver`,
`LogSegment`'s temp writer, `append`) goes through `writeAll`, which writes the rest after a short
count, so a disk that fills mid-write is the ENOSPC of the next `writeSync` and the temp is removed
with the log byte-unchanged, as main's buffered `write` answered; at `eb929048` both runtimes renamed
the short temp over the log (800 rows folded to 269 on a full tmpfs). A short `append` now answers
`false`, as main's did; the bytes it did write stay on disk as a cut line (as on main), and the next
append starts on a new line. `test_a_short_write_renames_nothing_over_the_log` and its Node twin
inject the short writer; an emptied live file is no bytes and so no `write(2)`, which the trace
tests now record.

**Closed by G2.** Every `G2 as Node` row in *Where the two runtimes deliberately differ* and the
J69-4 caller-object row is CLOSED: the cases agree, and each answer is pinned PER SIDE by a
literal, because both runtimes now run one source and a change to the TypeScript moves both at
once, which no differential can see. `--suite eventlog` 111 cases, `tokenledger` 66, `storage-log`
286 with 1 ruled (the `.gz` raw bytes, below), 0 `ruling: G2 as Node` left.

**Python-side behaviour changes, all toward Node** (`before` is the hand-written module at
`f22d9a8e`; measured by a scratch differential over both trees):

| Input | Python before | Python now = Node |
|---|---|---|
| everything in the eleven `G2 as Node` rows and the J69-4 row | the Python answers those rows record | Node's answers those rows record |
| `LogSegment.read` of `{"f":1.0}` / `{"z":-0}` / `{"b":18446744073709551616}` | `1.0` / `0` / the exact int | `1` / `-0.0` / `1.8446744073709552e+19` (JS numbers, `JSON.parse`'s reading) |
| `LogSegment.read` over an EMPTY `<path>.1.gz` | read as no lines, `skipped` 0 | one unreadable segment, `skipped` 1 (`gunzipSync` throws Z_BUF_ERROR; CPython's `gzip.decompress(b"")` returns `b""`) |
| `dumps_line` / `append` of an object nested past Python's recursion limit (~990 levels) | written (CPython's C encoder) | a `TypeError` refusal out of the call (the generated serialiser recurses; Node writes up to a stack-dependent ~5,100 levels and answers `false` past them, which no Python reproduces) |
| `dumps_line` of NaN / Infinity | `ValueError` | `RangeError`, a `ValueError` subclass |
| `format_timestamp(2**60)` / `(nan)` | `OverflowError` / `ValueError` | `RangeError: Invalid time value` (a `ValueError`) |
| `encode_record(..., None)` | `TypeError` | the generated `TypeError` (a `TypeError` subclass) |

**The switch is lowercased only when it is ASCII (J88-RF F2).** `resolvePath` and `fromEnv` match
`BANTAMKIT_EVENT_LOG` against ASCII tokens; a spelling holding any non-ASCII code point is left as
it is, because the one code point whose lowercase is ASCII is U+212A (to `k`, which no token holds;
`eventlog.test.mjs` re-measures all 1,114,112 on every run). Node's answer is unchanged for every
input, and the generated Python no longer raises the subset's `TypeError` for U+03A3 or U+1C89
(`toLowerCase` of a code point the two Unicode tables map apart), which `EventLog.from_env` did at
`eb929048`; `--suite eventlog` compares eight such spellings.

The gzip ruling stays as it was: a rotated segment's raw `.gz` bytes are `gzip.compress(mtime=0)`
on the Python side and Chromium zlib's stream on Node's (J88-2 measured 300 of 300 inputs apart at
level 6 as well), and only the decompressed bytes are compared.

**Tests retired.** Each had exactly the input of a conformance case, now a literal per side:

| Deleted | Covered by |
|---|---|
| `test_eventlog.py::test_the_cap_is_one_mebibyte_and_keeps_one_generation` | `--suite eventlog` `LITERAL: the constants are what docs/eventlog.md says — python` (`CAP_BYTES: 1048576`) |
| `test_tokenledger.py::test_every_line_is_counted_or_omitted_over_the_committed_corpus` | `--suite tokenledger` `LITERAL: the committed corpus counts what it counts — python` (19 lines, 7 requests, 12 omitted, over the same corpus) |

Changed: `test_storage_log.py::test_an_unlocked_append_writes_under_its_marker` spies on
`os.open` (the generated module opens the log as `fs.openSync` does) instead of `builtins.open`.
Added: the crash-safe write's order, on both sides (above). Every other test is kept: their
inputs are not the suites'.

**Cost, measured (J88-2, macOS arm64, CPython 3.12.13; n = 9, medians; before = the
hand-written modules at `f22d9a8e`, after = this tree).** Over 20% is flagged.

| Path | Before | After | |
|---|---|---|---|
| cold `import bantamkit.eventlog` (fresh process) | 87.2 ms | 86.9 ms | -0.3% |
| cold `import bantamkit.tokenledger` | 87.1 ms | 88.0 ms | +1.1% |
| cold `import bantamkit.storage.logsegment` | 86.5 ms | 86.8 ms | +0.3% |
| `EventLog.record` (warm, one record appended) | 112 µs | 175 µs | **+56% (over)** |
| `encode_record` (warm) | 2.5 µs | 13.0 µs | **+423% (over)** |
| `tokenledger.read(...).as_json()` over 2,000 lines in 20 transcripts | 6.0 ms | 19.4 ms | **+225% (over)** |
| `LogSegment.append` (warm) | 92.9 µs | 107.6 µs | +15.9% |
| `LogSegment.read` of 300 lines | 0.36 ms | 0.46 ms | **+31% (over)** |
| `LogSegment.fold` (warm) | 0.62 ms | 0.70 ms | +13.3% |
| `--hook` PostToolUse, a process | 364 ms | 371 ms | +2.0% |
| `--hook` on an unparsable event (a hook-log line through `LogSegment`) | 360 ms | 365 ms | +1.1% |
| `--hook` SessionStart | 368 ms | 370 ms | +0.5% |
| a process: `EventLog.from_env(..., on)` + 20 records | 97.8 ms | 98.1 ms | +0.3% |

Every one over the bar is the JS-semantics runtime in a warm loop (`_js_get` on every field, the
generated `JSON.stringify` / `JSON.parse`, the UTF-16 split), as #315 and G1 found; what a user meets
(a hook process, a server's event-log write, a module import) is within 2%. `token_ledger` over a
large real corpus is the one surface that pays the multiple (≈3.2x on the read); it is an
on-demand report, not a per-call path.

### The usage ledger (#316 G3 U1, J89-2); retrieval stays hand-written

Since J89-2 `bantamkit.memory.usage` runs code compiled from `runtime-ts/src/memory/usage.ts`:
`_generated/usage.py` (495 lines), from the same ts2py call as G1 and G2 (the ledger imports the
compiled log segment; G1 and G2's output is unchanged but for G3-10's local renames,
`tools/ts2py/RULES.md`). The hand-written module (364 lines) is retired; `memory/usage.py` is a
shim (203 lines). `pyfs.pyRealpath`, `pysem.pyPow` and `node:crypto`'s hash reach Python through
the adapter seam (RULES.md, *Adapters (J89-2)*): `pyRealpath` and `pyPow` onto the CPython function
each ports (`usage.os_realpath`'s `os.path.realpath` under the G2 path policy; `float ** float`),
`createHash('sha256').update(s, 'utf8')` onto `hashlib` over Node's UTF-8 with the G2 path policy
for a surrogateescape code point, so J89-1F's `storeId` cases (dangling symlink, a path below one,
a lone surrogate) and the ruled U+DC80 case are answered by the adapters unchanged.

**What the shim keeps (Python-only conveniences).**

- *Paths are `Path`s*: `UsageLedger(home, store_root, fold_lines=None, rotate_bytes=None)`,
  `store_id`, `os_realpath`, `missed_writes` and `status_line` take a `Path` or a string;
  `UsageLedger.path` is a `Path`.
- *Python shapes*: `weights` and `last_used_map` answer `dict`s (weights as `float`), `census` a
  tuple, `last_used` / `keywords_copy` `None` for nothing; `reduce_usage` takes `(row, line)`
  tuples (`storage/retention.py`).
- *Call-time constants*: `LEDGER_FOLD_LINES`, `LOCK_WAIT_MS` (this module) and
  `logsegment.ROTATE_BYTES` are read each time a ledger is used, as the hand-written ledger read
  them; `LOCK_STALE_MS`, `LOCK_POLL_MS`, `USAGE_HALF_LIFE_DAYS` and `WEIGHT_MAX` assigned on the
  shim (or by `monkeypatch`) are assigned on the generated module, which reads them at call time.
  `USAGE_HALF_LIFE_DAYS` and `WEIGHT_MAX` stay floats.
- *`_parse(ts)` answers seconds or raises `ValueError(f"not a ledger timestamp: {ts!r}")`* (it is
  `touch/*`'s and `skillmine`'s timestamp reader), and `weights` / `fold` raise that same
  `ValueError` for a bad `now`, as before (the generated ledger would raise node's `Error`).

**TypeScript refactors, each pure (Node's answers unchanged; `npm test` and `--suite recall-usage`
green):** `parseTs` counts days with Hinnant's `days_from_civil` instead of `new Date(0)` +
`setUTCFullYear` + `setUTCHours` (`usage.test.mjs` holds the two equal on all 3,652,059 days of years
1..9999) and keeps its answers in a bounded memo (a read parses each `ts` twice); `export { reduce as
reduceUsage }` became the function's own name; `Math.pow` became `pysem.pyPow`; the newline count is
a `latin1` split (Node measured faster: 72 µs against 91 µs over a 5,000-line ledger); `weightsOf`
and `valid` read each field once.

**Python-side behaviour changes, all toward Node** (`before` is the hand-written module at
`b3e570be`):

| Input | Python before | Python now = Node |
|---|---|---|
| a folded weight on a tie at the tenth decimal (a use 140 days before the fold: `0.5 ** 10` = 0.0009765625) | `"weight":0.000976562` (`f"{w:.9f}"`, half to even) | `"weight":0.000976563` (`toFixed(9)`, the larger) — a different ledger byte on disk; `--suite recall-usage` `tie: …` and `LITERAL: J89-2 a folded weight of 0.5 ** 10 is written 0.000976563` (red at b3e570be) |
| `append` past the fold threshold with a `ts` the fold cannot parse | the event written, then `ValueError` out of `append` | the event written, `False` |
| `UsageLedger(home, ...)` with `..`, `.` or a doubled separator in `home` | `.path` kept them (`Path(home) / ...`) | `path.join` normalises them (the same file); `missed_writes` / `status_line` key on that spelling |

**Found by J89-2, pinned UNRULED; CLOSED toward Node by J89-3**: a folded line dated far past `now`
(`9999-12-31`) decays by `0.5 ** (age / 14)` with a huge negative age; CPython's `**` raises
`OverflowError`, so the reference's `weights` and the recall that reads them raised, where node's
`Math.pow` answers Infinity and the fact weighs Infinity. Since J89-3 the `pyPow` adapter answers
Infinity where `**` overflows, and nowhere else (*Retrieval* below). (The dotless-i `tonight`
difference is in the D2 row above.)

**No `ruling: G3 as Node` case closed.** The two `G3 as Node` rows (a store root holding a NUL or a
lone U+D800) belong to `store.ts` (U2); `--suite store` still has its 13 ruled cases, none stale,
and the ruled U+DC80 `storeId` case stays (`--suite recall-usage`, 2 ruled: it and the new unruled
one).

**`memory/retrieval.ts` compiled, answered every case, and was NOT shipped generated.** J89-2
lowered everything it needs (G3-1 to G3-7 in RULES.md; `pysem` adapters for `round(x, 9)`,
`math.log`, `math.log1p`, NFKC + `lower` and the word-character test; `Float64Array` as arrays of
doubles) and `--suite recall-retrieval` (156), `recall-strings`, `recall-queries` and `recall-gate`
were green against it. Then `runtime-py/tests/test_storage_bar.py`, the #204 bar declared before any
number existed (a 5,000-fact recall at most 15 ms at p50), went red: **78.15 ms** against 6.1 ms for
the hand-written module (same machine, `before` tree). Warm calls, n = 9 medians (µs):
`bm25_segments` over 5,000 docs and 4 terms 1,366 -> 31,901 (+2,236%), `rank_columns` over 5,000
1,132 -> 26,662 (+2,256%), 5,000 `weight_of` 421 -> 17,065 (+3,956%), 5,000 `stale` 1,134 -> 6,548
(+478%), `tokenize_v2` of mixed-script text 37 -> 47 (+25%), `bm25_scores` over 200 docs +5.5%.
The cause is structural, not a missing helper: the hot loops do arithmetic on array elements and
Map values, which the fact system (SUBSET.md, *Types*) cannot prove numeric, so every `+`, `/`,
index read and write is a JS-semantics call, and `rank_columns`'s comparator sort calls Python once
per comparison where the hand-written module sorted by key at C speed. What generating it needs:
typed arrays whose elements are proven doubles (`Float64Array` as `array('d')`), number facts that
flow from such arrays and from a `typeof x === 'number'` narrowing, and a comparator-to-key lowering
for `(a, b) => f[b] - f[a] || a - b`. Until then `bantamkit.memory.retrieval` stays the hand-written
reference, `retrieval.ts` stays as it was, and the J89-2 rules it would use are pinned by
`tools/ts2py-bantamkit/tests/g3.rs`'s probe.

**Cost, measured (J89-2, macOS arm64, CPython 3.12.13; n = 9, medians; before = `b3e570be`, after =
this tree).** Over 20% is flagged. The user paths run over a 307-fact store whose usage ledger holds
3,000 recall events at distinct second-resolution times (a heavy user), rebuilt fresh for each run.

| Path | Before | After | |
|---|---|---|---|
| cold `import bantamkit.memory.usage` (fresh process) | 88.5 ms | 89.6 ms | +1.2% |
| cold `import bantamkit.memory.store` | 89.6 ms | 89.5 ms | -0.1% |
| `UsageLedger.weights` over 200 events (warm) | 654 µs | 755 µs | +15.4% |
| `UsageLedger.append` (warm, 200-line ledger) | 122 µs | 124 µs | +1.4% |
| `store_id` (warm) | 14.9 µs | 16.7 µs | +12.2% |
| `UsageLedger.fold` of 300 events (warm) | 782 µs | 1,177 µs | **+50.6% (over)** |
| `recall` over the store, warm, unstamped | 10.04 / 10.16 ms | 11.55 / 11.55 ms | +14.4% |
| `recall` over the store, warm, stamped (`memory_recall`) | 10.73 / 11.07 ms | 12.44 / 12.27 ms | +13.3% |
| `recall` in a fresh process (import included) | 102.7 / 102.8 ms | 116.3 / 118.4 ms | +14.2% |
| `--hook` UserPromptSubmit over the store, a process | 367.8 / 368.7 ms | 378.5 / 377.5 ms | +2.6% |
| `test_storage_bar` 5,000-fact recall p50 (usage generated, retrieval hand-written) | 6.1 ms | passes (<= 15 ms) | |

The fold is the one path over the bar; it runs once per 5,000 appended lines (and at Retention), not
per recall. Before J89-2's runtime fast paths (RULES.md G3-11), the memo and the `latin1` count, the
same tree measured `weights` +1,023%, `append` +198%, warm recall +1,040% and the hook +28%: the
JS-semantics runtime's per-operation cost, which G2 met in warm loops too.

**Tests.** Added (`test_memory_usage.py`): the ledger is the generated class; lock constants set on
the shim reach the generated module; the tie; the bad-`ts` auto-fold; the joined path. None retired.

### Retrieval (#316 G3, J89-3): generated, after numeric lowering in ts2py

Since J89-3 `bantamkit.memory.retrieval` runs code compiled from `runtime-ts/src/memory/retrieval.ts`:
`_generated/retrieval.py` (888 lines), from the same ts2py call as G1, G2 and the usage ledger. The
hand-written module (476 lines at `b3e570be`) is retired; `memory/retrieval.py` is a shim (419
lines). J89-2 had compiled the module and kept it hand-written because a 5,000-fact recall took
78 ms against the #204 bar of 15 ms; J89-3 gave ts2py what that code needed, and only where the
TypeScript proves it (`tools/ts2py/SUBSET.md`, *Typed arrays and counted loops*; `RULES.md`, J89-3):
a `Float64Array` whose elements are proven floats, native IEEE arithmetic on proven floats, counted
loops whose array bounds and element numbers are checked once before they run, and the key sort
`(a, b) => t[b] - t[a] || a - b`. The bar now measures **7.0 ms** (`test_storage_bar.py` passes).

**What the shim keeps (Python-only conveniences).**

- *Python shapes in*: a `Doc` (frozen dataclass), a `Candidate` (`NamedTuple`, `layer_order`),
  `Columns` (`NamedTuple`), dicts for `df`, `segs`, `postings` and usage, and `(weights, length)`
  rows are handed over as the objects, Maps and arrays the TypeScript reads. `doc_terms` answers
  `(dict, float)`, `weight` / `weight_of` / `length_of` a float, as before.
- *Constants*: `FIELD_BOOST` and `STALE_WORDS` stay tuples and every numeric constant a float.
  `W_TYPE` is a dict whose every write rebuilds the generated `Map` (`tune.py` assigns
  `W_TYPE["feedback"]`). `GATE_FLOOR`, `GATE_RATIO`, `W_TYPE_OTHER`, `W_FRESH_DEMOTE`, `W_USAGE`,
  `W_CONTEXT`, `W_FLOOR` and `QUERY_WEIGHT` assigned on the shim (or by `monkeypatch`) are assigned,
  as floats, on the generated module, which reads them at call time.
- *Scorers*: `BM25F`, `Bm25fScorer` and `QueryScorer` are Python classes over the generated ones
  (`column(cols, vecs)` takes `Columns`; `fallback` is settable; `QueryScorer.column` can be patched
  on the class, as `queries_ref.py` does). `Scorer` stays the `Protocol`.
- *The skill miner's names*: `_nospace(cp)` is the generated `nospace`, `_wordchar(ch)` the
  `pyWordchar` adapter.

**TypeScript refactors, each pure (Node's answers unchanged; `npm test` and every `recall-*` suite
green).** From J89-2's attempt: CPython's `round(x, 9)` (with the J68-5 fast path), `math.log`,
`math.log1p`, NFKC + `lower` and the word-character test moved into `pysem.ts` as `pyRoundFloat9`,
`pyLog`, `pyLog1p`, `pyNfkcLower`, `pyWordchar` (`roundHalfEven` is `pysem.pyRoundFloat`, `WORDCHAR`
moved there too; `skilllabel.ts` imports it from `pysem`), each mapped onto the CPython function it
ports; `forEach` loops became counted loops; `context?.get(...)` an explicit test; `rank` collects
its order in an array; `bm25Rows` asks `'scan' in row`; parameter properties became fields. New in
J89-3: `bm25Segments` and `rankColumns` keep their `Float64Array`s (J89-2 had turned them into plain
arrays) with the division's denominator in a `const`, the scores are written into `lengths.slice()`
(as fast in V8 as the `new Array(m)` it replaces, which ts2py would have to hold holes for: a `push`
loop measured 13% slower), and `rankColumns` takes its maximum in a counted loop. Node, interleaved
medians against `b3e570be`'s build (25 rounds; `bm25Segments` over one run per term 37.7 against
36.5 us in three more runs of 2,500): every function within 5% (`bm25Segments` +3.3%, `weightOf`
+2.3% / +3.9%, `stale` +4.1% / -5.2%, the rest within 2.5%).

**Python-side behaviour changes, all toward Node** (`before` is the hand-written module at
`b3e570be`. A differential of the two Python modules, 27,000 calls over edge inputs (NaN, ±0,
±Infinity, 5e-324, mixed scripts, U+0130 / U+0131, lone surrogates) to `tokenize_v2`,
`strip_nospace`, `stale`, `query_terms`, `weight_of`, `gate`, `rank_columns`, `length_of`,
`bm25_segments` and `bm25_scores`, values compared as doubles, found only `rank_columns`, 415 times;
the last two rows are by reading the code):

| Input | Python before | Python now = Node |
|---|---|---|
| `rank_columns` with a NaN weight (`[3, 1, 2, 5, 4]`, weights `[NaN, 1, NaN, 1, 1]`) | `sorted(admitted, key=final, reverse=True)` over NaN keys: `[0, 1, 2, 3, 4]` | V8's sort with the comparator a NaN makes inconsistent: `[0, 3, 4, 1, 2]` |
| `rank_columns` whose best score is Infinity or NaN at ratio 0 (`ratio * best` is NaN) | `max(floor, NaN)` is `floor`, so every positive score was admitted | `Math.max(floor, NaN)` is NaN, so nothing is admitted: `[]` |
| `gate(scores)` / `rank(...)` after `GATE_FLOOR` was reassigned | the default floor bound when the module was imported | the default read when called (a JS default parameter) |
| a score list that is all zeros (no query term, `n <= 0`) | `[0.0, ...]` | `[0, ...]`: the same numbers, spelled as ints |

`--suite recall-retrieval` `J89-3 rankColumns on raw columns (NaN, infinities, -0, ties): node
against python, 125 runs` and two per-side literals pin the first two (3 cases red against the
hand-written module, green now).

**The usage ledger's far-future line (J89-2's UNRULED pin), closed toward Node.** `pyPow`'s adapter
answers Infinity where CPython's `**` raises OverflowError, and changes no other result (a
ZeroDivisionError stays one). `--suite recall-usage`'s `future:` case is an agreeing case now (red
before the adapter changed: 2 failures) with a per-side literal for each runtime;
`test_memory_usage.py` pins the Python side.

**Cost, measured (J89-3, macOS arm64, CPython 3.12.13; n = 9 medians; before = `b3e570be`, J89-2 =
`181d7a8f` (usage generated, retrieval hand-written), after = this tree).** Over 20% against
`b3e570be` is flagged with its cause.

| Path | Before | J89-2 | After | vs before |
|---|---|---|---|---|
| #204 bar: 5,000-fact recall p50 of 20 (bar 15 ms) | 6.10 ms | 6.16 ms | 7.13 ms | +16.9% |
| `recall` over the 307-fact store, warm, unstamped | 10.40 ms | 11.65 ms | 12.64 ms | **+21.5%** (J89-2's ledger +12.0%, retrieval +8.5%) |
| `recall`, warm, stamped (`memory_recall`) | 10.85 ms | 12.45 ms | 13.42 ms | **+23.7%** (J89-2's ledger +14.7%, retrieval +7.8%) |
| `recall` in a fresh process, import included | 102.5 ms | 120.4 ms | 121.2 ms | +18.2% (retrieval +0.7%) |
| `--hook` UserPromptSubmit, a process | 362.4 ms | 382.0 ms | 385.4 ms | +6.4% (retrieval +0.9%) |
| cold `import bantamkit.memory.retrieval` | 95.3 ms | | 96.1 ms | +0.8% |

Warm calls (us, two runs each; the user paths above are what they cost a recall):

| Call | Before | After | |
|---|---|---|---|
| `bm25_segments`, 5,000 docs, 7 terms of one run each (the bar's shape) | 1,998 / 2,012 | 2,241 / 2,224 | +12% / +11% |
| `bm25_segments`, 5,000 docs, 4 terms of ~1,500 one-doc runs | 1,318 / 1,314 | 6,885 / 6,898 | **+422%**: each run is a turn of the outer loop over `seg[j]`, `seg[j + 1]`, `seg[j + 2]`, whose step of 3 and offsets the proven copy does not cover, so it runs the general lowering (about 1 us a run); the per-doc work inside is proven |
| `rank_columns` over 5,000 | 1,142 / 1,145 | 1,636 / 1,633 | **+43%**: one Python loop where the hand-written module mapped at C speed, and `x * weights[i]` through `_js_mul` (two proven numbers, neither proven a float) |
| `weight_of`, 5,000 calls | 421 / 436 | 11,456 / 11,528 | **+2,600%**: a scalar function of a Map value and adapter results, which prove nothing, so every operation is a JS-semantics call (`store` calls it once per type and once per used fact, not per row) |
| `stale`, 5,000 calls | 1,151 / 1,107 | 6,467 / 6,491 | **+470%**: the string helpers per character (the hot index calls it once per fact it writes) |
| `tokenize_v2`, mixed-script text | 38 / 37 | 46 / 47 | **+25%**: the code-unit loop; ASCII text is 94% faster (the `[a-z0-9]+` fast path) |
| `bm25_scores` over 200 docs | 10,573 / 10,414 | 10,225 / 10,200 | -3% |

**Tests.** Added (`test_memory_retrieval.py`): the module is the generated one and keeps the miner's
names; `W_TYPE` writes reach the generated Map; `GATE_FLOOR` is read at call time; the two moved
`rank_columns` answers. (`test_memory_usage.py`): the far-future line weighs Infinity. None retired.

### The store's constructs (#316 G3 U2, J89-4a): ts2py compiles `memory/store.ts`; generating it is J89-4b's

J89-4 counted 86 refusals compiling `runtime-ts/src/memory/store.ts` with the G1/G2/G3 call; J89-4a
leaves none (`tools/ts2py-bantamkit/tests/g3_store.rs` `j89_4a_store_compiles_with_the_committed_modules`;
the rules and the 34 adapter rows are in `tools/ts2py/RULES.md`, J89-4a). `store.py` is still the
hand-written module: no committed generated file changed (`workplan`, the codec, G1, G2, usage and
retrieval recompile byte for byte), only the runtime and adapter support modules ts2py writes.

**D1, fixed in Node (the orchestrator's ruling: python is right).** `candidatesDone`'s `ordinal` built
the day with `Date.UTC(y, mo - 1, d)`, which reads a year 0-99 as 1900-1999, so the year read back
differed and a fact `created` in 0001-0099 was never aged, where store.py's
`date.fromisoformat(...)` ages it. The day is now `parseTs(`${iso}T00:00:00Z`) / 86_400_000`
(`usage.ts`'s `daysFromCivil`, already held equal to `Date.UTC` on every day of years 1..9999); year
0000 and every impossible day stay refused on both sides. `--suite store`'s UNRULED case went STALE
by design and is the agreeing case `J89-4a candidates_done(older_than_days=0): created in the years
0001-0099` with a literal for each side (red against the old ordinal on a scratch copy: 2 failures).
30,000 seeded strings: the new ordinal agrees with `date.fromisoformat` (behind `_ISO_DAY_RE`) and
with the generated `usage.parse_ts` on every one; the old one disagreed on 3,908.

**TypeScript changes, each with Node's answers unchanged** (`npm test` and `--suite store` green):

| Was | Is | Why |
|---|---|---|
| `DONE_WORD_RE = new RegExp(`(?<!${PY_WORD_CLASS})(${pyCaseless(...)})(?!...)`, 'u')` and `.exec` | `pysem.pySearchWord(DONE_WORD_ALTERNATIVES, text)` (the same regex, built once per alternatives string) | ts2py compiles a pattern only when it is known at compile time; the adapter is store.py's `_DONE_WORD_RE`, which J89-1F and J89-2 swept the Node regex against |
| `private usage()` | `private usageLedger()` | `tokenledger.ts`'s `message.usage` (a plain object's property) is refused while any compiled class declares a method `usage`: a receiver's type is never a proven fact in ts2py, so the clash cannot be resolved by type (the orchestrator's first choice), and the private method was renamed |
| `(memo ??= usage())` | `{ if (memo === null) memo = usage(); return memo; }` | an assignment inside an expression is refused |
| `.filter(matchesMd)` | `.filter((name) => matchesMd(name))` | an adapter function as a callback would be called with the index and array too |
| `NOT_ONE_LINE.lastIndex = 0; NOT_ONE_LINE.exec(text); NOT_ONE_LINE.lastIndex = 0` (a `g` regex) | `NOT_ONE_LINE_UNIT.exec(text)` (the same class, no `g`, no `+`) | the subset models no `lastIndex`; the run's first unit is what `codepoint` reads either way. Found by running the compiled store (ts2py accepted the write and the runtime refused it); the write is now refused at compile time |
| the `Date.UTC` ordinal | `parseTs` (D1 above) | |

Node, medians of 11 per process over a 2,000-fact store, three processes each interleaved against
the build of `9e44aa5c` (old / new, the median of the three): `candidatesDone(30)` 35.74 / 35.05 ms
(-1.9%), `recall` 0.582 / 0.574 ms (-1.3%), `listFacts()` 34.09 / 34.45 ms (+1.1%), a refused
`save` (`notOneLine`) 10.9 / 10.8 us (-0.9%): every one within 5%.

**Ahead of J89-4b, found and not decided here.** The adapter rows make store.ts compile and a
scratch compile answer as Node does on saves, recall, lookup, `candidatesDone` and archived recall
over one store (identical trees and index file lists); J89-4b's suites will be the real test. Three
things it will meet: (1) store.ts reads `e.message` of a `PyOSError` (`skipped` reasons), and the
runtime refuses `message` on a Python exception (a Node fs error's message is not CPython's), so the
generated store needs the `OSError`'s CPython text there; (2) `parseFrontmatter` / `formatFact` are
the compiled codec's functions here, and the PyYAML fallback (#315's owner ruling) is J89-4b's to
route; (3) the pyfs adapters call CPython with the path as given (not the G2 `_os_char` policy), so a
lone-surrogate store root takes CPython's answers (`os.scandir` raises `UnicodeEncodeError`,
`Path.exists` answers false), not the Node answers `--suite store`'s `G3 as Node` rulings pin.

### The store (#316 G3 U2, J89-4b): generated, behind its shim

Since J89-4b `bantamkit.memory.store` runs code compiled from `runtime-ts/src/memory/store.ts`:
`_generated/store.py`, from the same ts2py call as G1, G2, the usage ledger and retrieval (the event
log now imports the compiled store's `.bantamkit` helpers from it). The hand-written module (2,635
lines at `5fc230c8`) is retired; `memory/store.py` is the shim. The orchestrator's three rulings on
J89-4's design questions are what it implements.

**1. The boundary.** The Python surface is unchanged: `Fact`, `Pool`, `SaveResult`, `ArchivedFact`,
`MergeResult` and `CompactResult` stay dataclasses of the values `yaml.safe_load` builds, and the
generated store keeps the codec's shape inside (dicts, `PyScalar`, `Map`s). The shim converts at
every crossing, both ways, checked: `_fact_in` / `_fact_out` through `factcodec.held_meta` /
`native_value`, `_pool_in` / `_pool_out` (a pool's lists are shared, its `df` / `segs` read as
read-only Maps). The modules not generated yet are untouched: `component`, `native`, `skills`,
`dream`, `hookadapter`, `mcpserver` and the hand-written hot and cold indexes call the same names
as before. `pick_hits` / `pooled_ranking` run the generated ranking over each layer's Python store
(a `_Resolver` per layer: `resolve` is the layer's own, the hit is that same `Fact` object) and the
Python scorer (`_Scorer` asks `scorer.column(Columns, vecs)`, so `queries_ref.py`'s hook on
`QueryScorer.column` still sees every column). The HotIndex <-> store cycle is the adapter's late
import (J89-4a), plus `HotIndex._of` for a caller that hands a store its own index
(`storage_ref.py`). A JS `TypeError` the generated store throws reaches a Python caller as the bare
`TypeError` the reference raised (`frontmatter scalar: links is an int` was the one case that
showed it).

The shim keeps these private names, each the generated method of the same job: `_facts`,
`_read_fact`, `_fact_paths`, `_listing`, `_fact_path`, `_index_line`, `_fact_text`, `_write_fact`,
`_rebuild_index`, `_check_index_budget`, `_after_write`, `_ensure_dirs`, `_present`, `_unwritable`,
`_reachable`, `_unreadable`, `_index_text`, `_indexed`, `_indexed_fact`, `_fact_named`,
`_probe_facts`, `_pool_indexed`, `_cold_synced`, `_use`, and the attributes `index_budget`, `k`,
`_today`, `_now`, `_index`, `_snapshot` (read through to the generated store, which reads them at
call time). **Retired: `_eviction_key` and `_staleness_key`** (store.ts ranks inside `compact`,
`byEviction`). One test reached one: `test_memory.py::test_the_eviction_rank_never_raises_on_a_hand_edited_type`
is rewritten against `compact` itself (five hand-edited types, `[1, 2]`, `{a: 1}`, `2026`, `null`,
`!!binary`, beside one `user` fact and room for one line: every weird one is archived and the `user`
fact kept). `test_archive_cli_…` / `test_restore_cli_prints_one_sentence_for_a_permission_error_at_the_move`
now refuse the move at `os.replace` (the `pyReplace` adapter; `Path.replace` is `os.replace`), not at
`Path.replace`. No other test changed.

**2. The PyYAML fallback stays** (#315's owner ruling). The `parseFrontmatter` / `formatFact` adapters
are `factcodec.held_frontmatter` (`load_frontmatter` — the compiled codec, then PyYAML where it
refuses — converted to the codec's shape; a PyYAML refusal is a JS Error carrying PyYAML's `str(e)`,
which `readFact`'s catch turns into `malformed fact file <name>: <that>`, the reference's sentence;
a non-mapping is `frontmatter is not a mapping`) and `factcodec.held_fact_text` (`fact_text` over the
Python values the fact stands for, so a write is the bytes the reference wrote). A value the codec's
shape cannot hold as Python holds it is carried OPAQUE (`factcodec._Opaque`, a `PyScalar` whose
`text` is `str()` of the value and whose `<` names its Python type): a set, bytes, a tuple, a
collection met twice (written back as PyYAML's anchor and alias), a dict with a non-text key, and a
list or dict where the store prints the value (`name`, `description`, `type`, the stamps, the
lifecycle fields, a `links` item, a `metadata` value), so the index line still prints Python's
`['a', 'b']` and not JS's `a,b`. The #120 rulings and the malformed-message rulings are unchanged
(`--suite store`: none STALE).

**3. `snapshot()` stays Python-only**, hand-written in the shim on the generated `candidates` /
`indexed` (the row in *Where the two runtimes deliberately differ*). Its callers
(`component.Memory.batch`, `test_memory.py`, `test_memory_queries.py`, `queries_ref.py`) are unchanged.

**Python-side behaviour changes, all toward Node.** The two `G3 as Node` store-root rows (a NUL, a
lone U+D800) are closed: the generated store's file calls take the G2 path policy (`_store_path`),
so Python saves a lone-surrogate root at U+FFFD and answers a NUL root with the store's own
could-not-be-created sentence, as Node does (*Where the two runtimes deliberately differ*, the two
struck rows; `--suite store` 428 cases, 11 ruled, 0 failures: the two `ruling:` cases went STALE as
designed and nothing else did). A store root holding a surrogateescape code point (U+DC80) stays
ruled (G2 target-specific, permanent).

**TypeScript changes, each with Node's answers unchanged** (`npm test` 2460 pass / 0 fail, every
suite above green):

| Was | Is | Why |
|---|---|---|
| `e.message` of a `PyOSError` (the `skipped` reason); `error.strerror` in `unwritable` / `unreadable` | `pyfs.pyOSErrorText(e)` / `pyfs.pyOSErrorStrerror(e)` (new; Node: `e.message` / `e.strerror`) | a compiled read of a Python exception's `message` / `strerror` stays refused (a Node fs error spells both differently); these two are adapters onto CPython's `str(e)` / `e.strerror` |
| `tokens`: `text.toLowerCase().match(/[a-z0-9]+/g)` | the `[A-Za-z0-9]+` runs, each lowered; a text holding U+0130 or U+212A lowered with every other non-ASCII code point read as a space | `.toLowerCase()` of arbitrary text is refused by ts2py (55 code points CPython's tables and Node's map apart; the suite's fuzz met one). Swept: every code point 0..0x10FFFF in six contexts against the old body in Node (0 differences) and the generated function against the reference's `re.findall(r"[a-z0-9]+", text.lower())` in Python (7,998,784 inputs, 0 differences, 0 refusals). Node speed, interleaved medians of 31 rounds over the live store's 91 names and descriptions: 21.25 against 21.40 ms (-0.7%); the first spelling (one `replace` pass) measured +15.6% and was dropped |
| `if (!(OUTCOME_TYPES as …).includes(type))`, the same in `lint` | the test named in a `const`, then `if (!…)` | the proven `includes` lowers to `in`, and `not x in y` is the E713 ruff refuses; Node within 0.1% (25 rounds) |

**Writes stay safe** (property 4). The atomic write is the `pyWriteTextAtomic` adapter (store.py's
`_write_text_atomic`, statement for statement); `--suite store`'s EFBIG cases (`j65-6: #161 …`, `J89-1F
a fact write cut short by EFBIG`, `J89-1F a save whose index.md write is cut short`) pass on the generated
store. ENOSPC, measured in a 1 MiB Docker tmpfs (CPython 3.13 `j88rf-py3.13`, Node 22 `node:22-slim`):
60 saves, the filesystem filled to two free pages, a 61st save. Python generated, Python at `b3e570be`
and Node answer the same: `OSError [Errno 28] No space left on device` from the `index.md` write,
`index.md` byte for byte the 11,390 bytes it was, no temp left, the new fact file landed (61 files).
Concurrency: 4 Python and 4 Node processes saving 30 distinct facts each into one store and each
rewriting one shared name after every save: 240 + 1 fact files, none lost, none duplicated, no temp
left, every file parses, `index.md` 241 unique lines and equal to `index_text()`.

**Cost, measured (J89-4b, macOS arm64, CPython 3.12.13; n = 9 interleaved rounds, medians; before =
`b3e570be`, after = this tree; the store a copy of this repository's 91-fact `.bantamkit/memory`, HOME
a scratch directory).** Over 20% is flagged with its cause.

| Path | Before | After | |
|---|---|---|---|
| #204 bar: 5,000-fact recall p50 of 20 (bar 15 ms) | 6.31 ms | 8.14 ms | **+29.0%**, under the bar: `poolIndexed`'s stride-5 segment loop runs the general lowering (`_js_mul` / `_js_add` per run; J89-3's proven copy covers stride-1 loops only) |
| first recall over 5,000 facts (builds the index) | 909.8 ms | 914.9 ms | +0.6% |
| `_facts()` over 5,000 facts | 378.4 ms | 537.0 ms | **+41.9%**: `readFact` is general JS-semantics code, plus the codec-shape conversion each way (`held_meta`, `_fact_out`) |
| cold `import bantamkit.memory.store` | 126.9 ms | 126.7 ms | -0.2% |
| cold `import bantamkit.eventlog` (now imports the compiled store) | 121.0 ms | 123.4 ms | +2.0% |
| `recall` in a fresh process | 124.7 ms | 127.8 ms | +2.5% |
| `--hook` UserPromptSubmit, a process | 383.5 ms | 388.0 ms | +1.2% |
| `Memory.recall` (`memory_recall`), warm | 3.80 ms | 4.50 ms | +18.3% |
| `Memory.save_outcome` (`memory_save`) | 31.5 ms | 36.4 ms | +15.5% |
| `MemoryStore.recall`, warm, unstamped | 284 us | 639 us | **+124.9%**: `poolIndexed` (above) and the hit's `readFact` |
| `MemoryStore.recall`, warm, stamped | 1,048 us | 1,781 us | **+70.0%**: the same, under the ledger write |
| `lookup`, warm | 22.3 us | 29.7 us | **+33.6%**: the generated `indexed()` / `names()` path |
| `_facts()` / `list_facts()` / `index_text()`, 91 facts | 2.50 / 2.50 / 2.48 ms | 5.48 / 5.48 / 5.37 ms | **+119%**: `readFact` and the conversions, as at 5,000 |

Every process-level path (what a hook, a CLI call or a server start pays) is within 3%; the warm
per-call paths that read facts are not. The remedy is ts2py work (a counted-loop proof with a constant
stride, and typed fact fields), not a shim change.

**Gates.** `--suite store` 428 cases, 0 failures, 11 ruled (13 before); `--all` 23,133 cases, 0
failures, 193 ruled; the F4 byte comparison and the sha256 header each red once on a scratch copy
(`ts2py/committed/store.py`; `test_generated_module_names_the_typescript_on_disk[store.py]`).

### The native layer (#316 G3 U3, J89-5): generated, behind its shim

Since J89-5 `bantamkit.memory.native` runs `_generated/native.py`, compiled from
`runtime-ts/src/memory/native.ts` in the G1/G2/G3 call (it imports the compiled store). The
hand-written layer is retired; `memory/native.py` is the shim: `NativeStore` keeps its Python
surface (a `Path` root, `Fact` / `Pool` dataclasses through the store shim's `_fact_out` /
`_pool_out`, `index()` answering the hand-written `HotIndex`, `_indexed`, `_listing`, `_read`,
`_named`, and the Python-only no-op `snapshot()`). A host file is read by `divergence.parse_fact`
through the new `parseNative` adapter, the function the hand-written layer called. The layer is
read-only on both sides: a probe over six files (two facts, a `metadata.type` fact, a file with no
fences, a duplicate name, `MEMORY.md`) through `pool`, `resolve`, `lookup`, `candidates` and
`count` left every file's mode, mtime and sha256 unchanged on Python generated, Python at
`8693f406` and Node, and all three gave the same answers. (The native MIRROR on save is
`hookadapter._export_to_native`, not this module, and is not generated.)

ts2py: a type imported from a compiled module declares its data fields (`pool.facts`), and an
annotated arrow parameter declares its fields (tokenledger.ts's `(o: Omission) => o.count`, which
`NativeStore.count()` would otherwise refuse under J89-4a's clash ruling); `tools/ts2py/RULES.md`,
*J89-5 rules*. TS refactors, Node's answers unchanged (`npm test` 2460 pass / 0 fail): native.ts's
two `skipped?.push(...)` are `if (skipped != null) skipped.push(...)`, and the callback annotation.

**A fix found by generating it.** The adapter that restates a hand-written `BantamError` built a
SECOND `BantamError` class on each direct call, so a compiled `e instanceof BantamError` missed the
restated error and the generated `candidates` raised on a malformed host file instead of skipping it.
No case covered it; `--suite recall-strings` now has `native candidates past a malformed file and a
duplicate name` (agreeing, plus a per-side literal), red (exit 2) against the old adapter.

**Cost (J89-5, macOS arm64, CPython 3.12.13; n = 9 interleaved rounds, medians; before = `8693f406`,
after = this tree; the native directory a copy of this project's 211-file Claude Code auto-memory,
the project store a copy of the 91-fact `.bantamkit/memory`, HOME a scratch directory per side).**

| Path | Before | After | |
|---|---|---|---|
| `NativeStore.pool` (warm, indexed) | 331 us | 342 us | +3.2% |
| `pool` + `resolve` of the top rows | 925 us | 952 us | +2.9% |
| `lookup` | 217 us | 231 us | +6.2% |
| `candidates` (parses all 211 files) | 40.4 ms | 42.2 ms | +4.5% |
| `count` | 211 us | 714 us | **+238%**: native.ts lists by `readdirSync` and then `statSync`s every name (`isFile`), where the hand-written layer read `os.scandir`'s cached type; two adapter speedups (`py_join` memoised, a code-point sort without the comparator) took it from 2,128 us |
| layered `Memory.recall` (`memory_recall`, native layer last) | 14.0 ms | 14.7 ms | +5.1% |
| cold `import bantamkit.memory.native` | 136.3 ms | 139.8 ms | +2.6% |
| `--hook` UserPromptSubmit with the native layer, a process | 419.6 ms | 415.3 ms | -1.0% (output byte-identical, and equal to Node's) |

**Gates.** `--all` 23,136 cases, 0 failures, 193 ruled; the F4 byte comparison
(`ts2py/committed/native.py`) and the sha256 header
(`test_generated_module_names_the_typescript_on_disk[native.py]`) each red once on a scratch edit.

### The queries sidecar (#316 G3 U3, J89-5a): generated, behind its shim

Since J89-5a `bantamkit.memory.queries` runs `_generated/queries.py`, compiled from
`runtime-ts/src/memory/queries.ts` in the G1/G2/G3 call (it imports the compiled store and
retrieval). The hand-written module is retired; `memory/queries.py` is the shim and keeps every
name its callers use (`component`, `mcpserver`, the tests, `queries_ref.py`): the constants,
`sidecar_path` / `terms_path` answering `Path`, `read_sidecar` a dict, `layer_terms` a dict of
`(weights, length)` tuples (a cached row's flat list read first-wins, `+ 0.0`, as `CountsView`
reads it), `check_queries`, `fact_sha`, `write_entries` and `status_line`. `write_entries` restates
the TypeScript's `SidecarWriteError` as `OSError` with its message, which is what `component.py`
catches (a lone surrogate in a query was a `UnicodeEncodeError` before; both are caught there, and
the reply is the same `WRITE_FAILED` tail).

ts2py (`tools/ts2py/RULES.md`, *J89-5a rules*): a class no export names keeps its method names in
its own module, so `CountsView`'s `get` / `has` / `keys` do not turn every Map call of the other
ten modules into a run-time dispatch (the other modules refuse an instance at run time instead of
answering for it). The codec call's `factfile.py` is regenerated by the same rule (pyyaml.ts's
private `Emitter` no longer makes its `push` calls dispatch). Adapters: `parseJson`, `dumpJson`,
`encodeBasestringAscii` (CPython's `json`, with the int/float kind kept as tags), `sha16`,
`pyDecodeUtf8`, `fs.writeFileSync`, and `createHash('sha1')` over a Buffer; a seeded fuzz of
20,000 JSON texts against Node's `pyjson.ts` agreed with 0 differences. TS refactors, Node's
answers unchanged (`npm test` green): `SidecarWriteError`'s name is a class field; `CountsView`'s
parameter property is a declared field; `doc['facts']` is read through a binding annotated with a
JSON type (J89-4a's clash ruling stands); `[n, [dl, c]]` is `[n, row]`; `flatMap` a loop; the
merge builds a new Map instead of `Map.delete` (the sidecar's keys are written sorted); and the
write's error text is `pyOSErrorText(asPyOSError(e))`, CPython's `str(e)`, on both sides.

Writes are unchanged. A probe (umask 022 and 077) through `write_entries` (a first write into a
missing directory, a merge with a removal, a lone surrogate refused, a BOM-led sidecar replaced, an
unwritable directory) and `layer_terms` (the cache built, then read) left the same files, modes
(0o644 / 0o600) and sha256s, and no `.tmp`, on Python generated, Python at `2737c34e` and Node;
the one difference is the exception type above.

**A fix found by generating it.** `layer_terms` (every recall) read the sidecar through
`json.loads`, which raised `RecursionError` out of the recall on a sidecar holding an entry nested
20,000 lists deep; Node's `JSON.parse` path reads it and skips the entry. The generated module takes
Node's path (`_js_json_parse`, J88-2), so both rank as the same bed without the entry.
`--suite recall-queries` `sidecar/deep: ...` (7 prompts, python against node and against the bed
without the deep entry), red against the Python of `2737c34e` (the reference raised).

**Found, not ruled, not changed (reported to the orchestrator):** `read_sidecar` (`readSidecar`, the
`memory_queries` coverage and missing list, `bantamkit_status`) reads through `parseJson`, the port
of `json.loads`, and the two disagree on a deep sidecar. Nested 3,000 deep, Node's recursive
`parseJson` overflows its stack and reads the sidecar as malformed (`[]`), where CPython's
`json.loads` reads it (`{'a': ['ok']}`); nested 20,000 deep, Node answers `[]` and Python raises
`RecursionError`. Python at `2737c34e` and Python generated answer the same at every depth
(the adapter is `json.loads`), so generation neither made nor moved this difference; no case pins
it and no ruling chooses a side. **Ruled and closed by J89-5d** (below): past CPython's limit Python
takes Node's answer; between the two limits the difference is a ruled divergence.

**Cost (J89-5a, macOS arm64, CPython 3.12.13; n = 9 interleaved rounds, medians; before =
`2737c34e`, after = this tree; the store a copy of the project's 172-file `.bantamkit/memory` and
its real 7,142-byte sidecar, HOME and the index dir scratch per side).**

| Path | Before | After | |
|---|---|---|---|
| `layer_terms`, cache current | 135.2 us | 431.5 us | **+219%**: the cache's validation loop (every term's `isCount`, `typeof`, `Number.isInteger`) runs through the runtime's untyped helpers, where the hand-written loop was `type(x) is int`; and `JSON.parse` is `json.loads` with JS number hooks |
| `layer_terms`, cache rebuilt | 460.6 us | 1,240.9 us | **+169%**: as above, plus `dumpTerms` and the tokenizer's generated path |
| `read_sidecar` | 40.0 us | 149.2 us | **+273%**: `parseJson`'s tagged value is built for every node and walked by the generated loop |
| `check_queries` (5 queries) | 0.4 us | 9.9 us | **+2,544%**: the code-point count is a per-character loop and `forEach` a callback, where Python's was `len(x)` |
| `write_entries` (one entry merged) | 246.9 us | 486.1 us | **+97%**: tagging and untagging the document; `fs.writeFileSync`'s UTF-8 is one strict `encode` (a surrogate scan first cost 140 us of it) |
| `memory_queries` missing list | 1.1 ms | 1.3 ms | +13.2% |
| `memory_queries` write (one fact) | 598.8 us | 979.2 us | **+63.5%**: `write_entries` and `check_queries`, above |
| layered `Memory.recall` (`memory_recall`) | 3.0 ms | 3.3 ms | +9.7% |
| cold `import bantamkit.memory.queries`, a process | 116.7 ms | 115.3 ms | -1.2% |
| `--hook` UserPromptSubmit, a process | 410.0 ms | 415.5 ms | +1.3% (output byte-identical, and equal to Node's) |

Node, the same bed (n = 9, before = `2737c34e`'s `dist`): `layerTerms` cached +0.2%, rebuilt +2.4%,
`writeEntries` +1.4%, a removal +2.4%: the TS refactors move Node less than 5%.

**Gates.** `--all` 23,151 cases, 0 failures, 193 ruled (`--suite recall-queries` 464); the F4
byte comparison (`ts2py/committed/queries.py`) and the sha256 header
(`test_generated_module_names_the_typescript_on_disk[queries.py]`) each red once on a scratch edit.

### The layers (#316 G3 U3, J89-5b): generated, the config read kept on PyYAML

Since J89-5b `bantamkit.memory.layers` runs `_generated/layers.py`, compiled from
`runtime-ts/src/memory/layers.ts` in the G1/G2/G3 call (it imports the compiled store). The
hand-written module is retired; `memory/layers.py` is the shim and keeps every name its callers use
(`component`, `hookadapter`, `mcpreport`, `divergence`, `__main__`, the tests, `layers_ref.py`,
`g3_ref.py`): `PROJECT_STORE` a `Path`, `CONFIG_NAME`, `MEMORY_DIR_ENV`, `StoreBinding` (the
frozen dataclass, `fact_count` / `searched_from` snake_case, `Path` fields), `discover_project_store`
and `load_grants` answering `Path`s, `resolve_project_store`, `count_facts`, `tab_sentence` and
`_pinned_store`.

**The config is still read by PyYAML (the orchestrator's ruling on J89-5's stop, option b).** It
follows the owner's #315 ruling for fact files: generated, with PyYAML kept on the Python side.
layers.ts's own reader (`firstTokenTab`, `parseConfigDocument` and their helpers) moved byte for
byte into `runtime-ts/src/memory/grantconfig.ts`, which is not compiled; layers.ts imports the two
functions and ts2py resolves them to adapters that ARE `yaml.safe_load` (one load per text): the
tab mark read off PyYAML's own `ScannerError` as the reference's `_token_tab` read it, the document
converted to the `ConfigDocument` the generated validator reads, a `yaml.YAMLError` a JS Error with
`str(e)`. Every other rule of layers.ts is generated. Pathlib calls are adapters onto the same
pathlib calls (`tools/ts2py/RULES.md`, *J89-5b rules*). TS refactors, Node's answers unchanged
(`npm test` green, Node's `loadGrants` / `resolveProjectStore` / `discoverProjectStore` within
-0.9%..-0.4%, n = 9 against `32831cff`'s `dist`): the move; `data.entries` read through a local
`ConfigMapping` binding (J87-12); `e.strerror` as `pyOSErrorStrerror(e)` and the read failure as
`pyOSErrorText(e)` (J89-4b).

Python's answers are unchanged. A battery of 72 config documents (anchors, aliases, merge keys,
tags, directives, a second document, a document end, block and folded scalars, flow mappings and
sequences over lines, `\x` / `\u` / `\t` / `\0` escapes, a BOM, a NUL, impossible timestamps, a
5,000-digit int, nesting 1,000 and 3,000 deep) gave byte-identical `load_grants` answers on the
generated module and on the hand-written module at `32831cff` (exception types included).

**The config family, ruled (J89-5b).** J89-5's finding, `extra_stores: &a [g]` (Python grants
`<…>/.bantamkit/g`, Node refuses with `invalid memory config <path>: extra_stores must be a list of
paths`), is a deliberate difference by the same ruling, and the scan for others found 28 documents
whose OUTCOME differs (Python grants, Node refuses) and 13 where both refuse in different sentences
(or, for `"g\t"`, after reading a different path). All 41 are one family, a document outside the
port reader's language, and carry the three pins: the divergence row above, a `RULED: config
outside the reader's language — <document>` case each in `--suite recall-strings`, a non-ruled
`J89-5b outcome bit per side: <document>` companion each (each side's grant/refuse bit against a
literal), and per-side literals of every answer. Red once: a scratch-tree shim that refused the
anchored list with Node's sentence turned the ruling STALE and its companion and the Python literal
red (3 failures).

**Found, not ruled, not changed (reported to the orchestrator).** Seven documents are NOT this
family: CPython raises out of `load_grants` an exception it never caught, where Node grants or
refuses by name. An implicit timestamp PyYAML cannot construct (`k: 2001-02-30`, `2001-02-30: x`,
`k: 2001-02-03 25:00:00`: `ValueError`, and Node GRANTS), an int past CPython's 4,300-digit limit
(`ValueError`; Node grants), the same timestamp as a grant (`ValueError`; Node refuses), a decoded
NUL in a grant (`"a\0b"`: `ValueError` from `Path.resolve`; Node reads `a0b` and refuses it) and a
flow sequence 1,000 deep (`RecursionError`; Node refuses). Generation keeps Python's answer (the
`firstTokenTab` adapter raises such an exception outside the compiled `try`, as it left
`load_grants`). Each is pinned `ruling: UNRULED DIVERGENCE (J89-5b) load_grants — <document>` with
its outcome-bit companion and the per-side literals; no ruling chooses a side. **Ruled and closed by
J89-5d** (below): Python refuses each by name, and all seven joined the family.

**Cost (J89-5b, macOS arm64, CPython 3.12.13; n = 9 interleaved rounds, medians; before =
`32831cff`, after = this tree; the project store a copy of the 91-fact `.bantamkit/memory`, granted
a second copy through `config.yaml`, the walk starting two levels below it, HOME scratch).**

| Path | Before | After | |
|---|---|---|---|
| `discover_project_store` | 40.6 us | 42.5 us | +4.6% |
| `resolve_project_store` | 112.4 us | 118.9 us | +5.8% |
| `load_grants` (one grant) | 96.2 us | 110.9 us | +15.2%: the converted document and the generated validator's `_js_get` reads |
| `count_facts` (91 facts) | 68.1 us | 69.8 us | +2.5% |
| `Memory.layered` (project, grant, profile) | 321.7 us | 348.5 us | +8.3% |
| layered `Memory.recall` (`memory_recall`) | 7.55 ms | 7.16 ms | -5.3% |
| cold `import bantamkit.memory.layers` | 91.2 ms | 89.9 ms | -1.4% |
| `--hook` UserPromptSubmit, a process | 423.1 ms | 421.6 ms | -0.3% (output byte-identical, and equal to Node's) |

**An instrument followed the lever.** `divergence.writer_store_env_names` (the register of env
names the writer's store resolution reads, Python-only, off the MCP path) scanned `memory/*.py`;
once the shim no longer spells `BANTAMKIT_MEMORY_DIR` the scan found nothing and
`test_no_environment_variable_moves_the_writers_store_behind_this_resolvers_back` went red. It now
also scans the generated body of each memory shim (`from bantamkit._generated import <x> as`) and
treats a module's `__all__` strings as names, not env reads (`_generated/store.py` lists
`BANTAMKIT_GITIGNORE_TEXT`): the population is `{BANTAMKIT_MEMORY_DIR}` again, read from
`_generated/layers.py`, so a lever added to `layers.ts` is seen.

**Gates.** `--all` 23,250 cases, 0 failures, 241 ruled (`--suite recall-strings` 261, 50 ruled);
the F4 byte comparison (`ts2py/committed/layers.py`) and the sha256 header
(`test_generated_module_names_the_typescript_on_disk[layers.py]`) each red once on a scratch edit.

### The dream (#316 G3 U3, J89-5c): generated, behind its shim

Since J89-5c `bantamkit.memory.dream` runs `_generated/dream.py`, compiled from
`runtime-ts/src/memory/dream.ts` in the G1/G2/G3 call (it imports the compiled store). The
hand-written module is retired; `memory/dream.py` is the shim and keeps every name its callers use
(`component`, `memory/__init__`, `test_memory_dream.py`, `dream_ref.py`): `PROJECT_LAYER`,
`PROFILE_LAYER`, `SUPERSEDED_HEADING`, the frozen dataclasses `DateHit`, `Superseded`, `DreamMerge`,
`SimilarPair` and `DreamResult` (with `over_budget`, `changes`, `superseded`) holding Python values,
and `collapse`, `block_key`, `split_blocks`, `claim_slot`, `union_keywords`, `absolutise`,
`merge_descriptions`, `merge_links`, `merge_bodies`, `dream`. Values cross through the codec
(`held_values` / `native_value`), the stores as the generated store each `MemoryStore` wraps, and a
JS `TypeError` / `AttributeError` the generated pass throws reaches a caller as the bare Python
exception the reference raised, with its text. The private helpers (`_resolve`, `_consume`,
`_size`, `_rebuild_if_present`, the compiled patterns) had no caller outside the module and are gone.

**The patterns are CPython's own.** Every pattern dream.ts built at run time from `pysem`'s CPython
classes under the `u` flag (`RELATIVE`, `UNRESOLVED`, `STAMPED`, `BULLET`, `SLOT`, `\s+`) moved byte
for byte into `runtime-ts/src/memory/dreamre.ts`, which is not compiled, with `pyIntDigits` and
`formatFixed3`; each is a port of a `dream.py` pattern or call, so ts2py reaches it through an
adapter that runs that CPython pattern or call (`tools/ts2py/RULES.md`, *J89-5c rules*). Every other
rule of dream.ts is generated. TS refactors, Node's answers unchanged (180,014 calls of dream.js's
exported functions over a seeded corpus, 053569d5's `dist` against this tree's: 0 differences;
`npm test` green): the move (the relative scan hands back each match's `lead` and a `tail`, so no
string position crosses the seam, and its count group is `digits`); `SUBJECT_OK` without its no-op
`u`; `flatMap` a loop; `pyHashKey` in an inline arrow; `store.internals()` destructured into locals
(a property call of a name a compiled class declares is dispatched, and refused on a plain object).
One runtime extension: `s.split(re)` (G3-29), which `splitBlocks` needs.

**Python's answers are unchanged but for the ruling.** The day-table lookup is dream.ts's, so a
matched spelling that is not a key (`tonıght`, `TONİGHT`, `yeſterday`) is reported unresolved where
the hand-written `_resolve` raised `KeyError`: the orchestrator's ruling on J89-5 (node is right).
The J89-2 UNRULED case went STALE by design and is an agreeing case with per-side literals, joined by
U+0130 and `yeſterday` (U+017F, the same lookup, never pinned before); red against 053569d5's python
(6 failures). The write probe below and every `--suite dream` scenario (plan and both trees) are
otherwise byte-identical to the hand-written module.

**Found, not ruled, not changed (reported to the orchestrator).** Two counts `int()` and node's
`pyIntDigits` read differently, the same before and after generation (the compiled dream reaches
`int()` through the adapter): a digit of U+1D7D8..U+1D7FF (four ten-digit Nd blocks that follow the
bold digits; node's walk back to the block's zero stops nine codepoints down and reads every one as
9: `𝟘 days ago` is 2026-08-28 on node and 2026-09-06 on python), and a count of more than 4,300
digits (`int()` raises `ValueError` out of `dream()`; node reports the term unresolved). Each is
pinned `ruling: UNRULED DIVERGENCE absolutise: …` with a literal per side in `--suite dream`; no
ruling chooses a side. **Ruled and closed by J89-5d** (below): Node's digit fixed, Python's limit
case answers Node's. UCD skew (a Unicode 16 assignment such as U+10D40, an Nd digit and a word
character to Node's ICU and unassigned to CPython 3.12) moves `\b`, `\d` and `lower()` as the
`candidates_done` row above describes; it is unchanged by generation.

**Writes (J89-5c probe, both sides).** One bed (an identical pair, a diverged pair with a slot
contradiction, mtimes and modes 0640 / 0600 / 0604, keywords and an extra key, a project-only fact
with relative dates, a profile-only fact, a project `index.md` and none in the profile) applied
with `dry_run=False` under umask 022 by 053569d5's python, this tree's python and Node: the three
trees are identical file for file, byte for byte and mode for mode (the profile copies moved to
`archive/` keeping 0604 and 0600, the survivors rewritten 0644 through the atomic write, the
profile store still without an `index.md`).

**Cost (J89-5c, macOS arm64, CPython 3.12.13, Node v26.13.0; n = 9 interleaved rounds, medians;
before = `053569d5`, after = this tree; the project store a copy of the repository's
`.bantamkit/memory`, the profile a copy of `~/.bantamkit/memory`, 313 files, HOME scratch).**

| Path | Before | After | |
|---|---|---|---|
| cold `import bantamkit.memory.dream` | 91.4 ms | 92.2 ms | +0.9% |
| `absolutise` (a 9-term body) | 38.7 us | 165.9 us | **+329%**: dream.ts's day arithmetic (`isoFromOrdinal` walks the years of a 400-year cycle) compiled, in place of CPython's C `date + timedelta`; ~14 us a term |
| `merge_bodies` | 77.3 us | 120.4 us | **+56%**: the compiled `splitBlocks` / `claimSlot` / `blockKey` through the runtime's UTF-16 helpers and the adapter's dicts, in place of three `re` calls |
| `claim_slot` | 1.41 us | 2.60 us | **+85%**: the same |
| `dream` dry run (the two stores) | 398.9 ms | 334.7 ms | -16.1% |
| `memory_dream` (`Memory.layered(...).dream_outcome(True)`) | 398.5 ms | 332.8 ms | -16.5% |
| `--hook` UserPromptSubmit, a process | 377.6 ms | 372.8 ms | -1.3% (output identical) |
| Node `absolutise` / `dream` dry run / import | 5.37 us / 45.1 ms / 9.68 ms | 5.37 us / 45.2 ms / 9.71 ms | +0.0% / +0.3% / +0.3% |
| Node `mergeBodies` / `claimSlot` | 36.5 us / 0.633 us | 30.6 us / 0.409 us | -16.3% / -35.4% (faster; cause not isolated: the `u`-less `SUBJECT_OK` alone measured equal) |

The user path is faster: the pass is dominated by the generated store's reads, and the per-call
regressions above are microseconds a fact.

**Gates.** The F4 byte comparison (`ts2py/committed/dream.py`) and the sha256 header
(`test_generated_module_names_the_typescript_on_disk[dream.py]`) each red once on a scratch edit.
`--all` 23,263 cases, 0 failures, 242 ruled (`--suite dream` 148, 2 ruled). The repo map's own
test over this package (`test_repomap.py`, `repomap.test.mjs`) focused `memory/dream.py` and
expected `memory/store.py` in its top three; the shim imports the codec's converters too, so
`memory/factcodec.py` ranks first and `memory/store.py` sixth, and both tests say so.

### Three crashes ruled, and a digit fixed (#316 G3, J89-5d)

The orchestrator ruled the three findings J89-5a, J89-5b and J89-5c left unruled. The rule for all
three: **a crash is a bug**, so where CPython raised out of a user path, Python takes Node's answer.
Generation is not involved, and the generated modules are unchanged. Every Python change is an
adapter in `tools/ts2py-bantamkit/adapters.py`, written out as `_generated/_ts2py_adapters.py`.

**The queries sidecar, nested.** `parse_json` (the `parseJson` adapter, which reads the sidecar
for `readSidecar` and for the merge in `writeEntries`) now answers `json.loads`'s `RecursionError`
with the RangeError `Maximum call stack size exceeded`, which is what Node's recursive `parseJson`
throws. The compiled `catch` sees that error, so the sidecar is malformed on both sides.
- Python's coverage, missing list, write and status no longer raise on a sidecar nested 20,000 or
  100,000 deep. They answer as the bed with no project sidecar, and a write replaces the sidecar.
- Between the two limits, the two sides differ by ruling. Node's limit is 1,562 cold and 6,902
  optimised; CPython's is 9,994. See the divergence row above, pinned at 8,500.
  **Superseded by J89-5e** (below): CPython's limit is 9,994 only on 3.12 and 3.13, so Python now
  reads to a fixed 512 and the ruled band is 512 to Node's stack, pinned at 513; 8,500 agrees.

**The scan for the same shape (rule 3)** was a probe of both sides at 3,000, 8,500 and 100,000 deep:
- **The term cache** (`cached`, `JSON.parse`) agreed on a deep entry, a deep row and a deep extra
  key: same rows, same cache bytes after.
- **The usage ledger** (`LogSegment._load`, `JSON.parse`) agreed with deep values in `keywords`,
  `weight`, `last`, `ts`, a stray key and a whole line. `weights`, `last_used_map`, `census`,
  `keywords_copy` and the fold were identical; the fold keeps a deep save line as it was read.
- **The pricing table** (`decodePriceJson`) agreed on a deep `note` and on a deep token-class rate:
  same `PriceTableError`. Its validation looks only one level down.
- **The event log** and **the store** have no JSON read in their generated modules. The event log
  writes `number | boolean | string` details. The store stringifies `[file, mtime_ns, size]`.
- **The token ledger and the log segment** are pinned at 100,000 deep by J88-2.

Each `JSON.parse` lowering, `_js_json_parse`, reads any depth without recursing, as V8 does (J88-2).
`parseJson` was the only recursive JSON read on a user path. Nothing found fits neither rule.

**The grants config: seven crashes are now refusals.** `yaml.safe_load` raised a `ValueError` for a
scalar PyYAML resolves but cannot construct, and a `RecursionError` past CPython's limit. The
`firstTokenTab` adapter now holds that error instead of raising it out of `loadGrants`.
`parseConfigDocument` then throws it as a JS Error, which the compiled `catch` turns into
`invalid memory config <path>: <reason>`. The reasons:
- CPython's own `str(e)` for a scalar that cannot be constructed, for example
  `day is out of range for month`;
- `the document is nested too deeply to read` past CPython's limit;
- `extra_stores must be a list of paths` for a NUL that PyYAML decoded into a grant. A path holding
  NUL names nothing, so the item is not a path. Before, `Path.resolve` raised `ValueError`.

The seven rows of `--suite recall-strings` are now in the family (48 documents) with its three
pins. Against 053569d5's Python, each of the seven outcome-bit companions and the Python literal
went red: 8 failures. A raw NUL in the YAML text is unchanged: it is still the both-refuse row.

**The dream's counts.**
- **Node's `pyIntDigits` was wrong.** It walked back at most nine code points to a block's zero.
  U+1D7CE..U+1D7FF is five ten-digit blocks back to back, so every digit of the last four blocks
  read as 9 (36 of 40 wrongly). It now reads a digit's distance from the start of its run of `Nd`
  code points, modulo ten. Swept over every code point CPython 3.12's `int()` accepts (680): 0
  differences. The sweep is a case in `--suite dream`; against a4321fdf's Node, it named the 36.
- **Python raised on long counts.** A count of more than 4,300 digits raised `ValueError` out of
  `dream()`. The `pyIntDigits` adapter now reads such a run as Node does: leading zeros dropped,
  and infinity past 400 digits. CPython's limit is left where it is.
  - So 4,301 nines is unresolved on both sides.
  - A zero-padded 4,301-digit `…03 days ago` resolves to three days on both sides.

The two UNRULED cases are now agreeing `J89-5d absolutise: …` cases, with a per-side literal each,
and a second mathematical spelling and the padded count are added. Against a4321fdf, nine cases
went red, on Node and on Python.

**Red once, each, in a scratch worktree with this change's suites.**
- `--suite recall-queries` against 32831cff's `runtime-py/src` stopped on the reference's
  `RecursionError` (exit 2).
- `--suite recall-strings` against 053569d5's: 8 failures.
- `--suite dream` against a4321fdf's `runtime-py/src` and `dreamre.ts`: 9 failures.

**Gates.** `--all` 23,289 cases, 0 failures, 241 ruled (242 before: the two dream rulings became agreeing
cases, and the nested-sidecar ruling was added). By suite: `--suite recall-queries` 482 (1 ruled),
`--suite recall-strings` 261 (50 ruled), `--suite dream` 156 (0 ruled), `--suite ts2py` 464,
`--suite store` 428, `--suite recall-usage` 256, `--suite eventlog` 131 and `--suite wire` 712, each
with 0 failures. ts2py `cargo test`: 87 passed (`j89_5b_layers_adapters_answer_like_the_reference`
now holds the held error, the two refusals and the NUL item); clippy (`-D warnings`) and fmt are
clean. `npm test`: 2,460 passed, 0 failed, 47 skipped. Full pytest: 5,335 passed, 0 failed. ruff is
clean.


### The nested sidecar on every supported CPython (#316 G3, J89-5e)

J89-5d ruled the band between Node's stack and CPython's `json.loads` limit at 8,500, measured on
3.12. The orchestrator probed 3.11, the supported floor: there `json.loads` of an array 8,500 deep
raises `RecursionError`, so Python answered `[]` as Node does and the ruled case went stale, and
between ~980 and Node's cold 1,562 the band ran the other way, unpinned. **Ruled (J89-5e): Python's
answer must not depend on the CPython version or its recursion limit.**

**Measured** (Docker, `python:3.11-slim`, `python:3.12-slim`, `python:3.13-slim`, `python:3.14-slim`,
default recursion limit 1,000; a binary search over `json.loads('[' * n + ']' * n)`):

| CPython | top level | 50 / 100 / 200 / 400 frames deeper | inside `parse_json` on the MCP path |
|---|---|---|---|
| 3.11.18 | 991 | 941 / 891 / 791 / 591 | 979 (978 one frame deeper) |
| 3.12.16 | 9,997 | 9,997 | 9,993 |
| 3.13.18 | 9,998 | 9,998 | 9,994 |
| 3.14.10 | none (20,000, the probe's ceiling) | | |

The MCP path is the real server under the real SDK (`memory_save`, `memory_queries` coverage and
write, `memory_recall`, `bantamkit_status`): `parse_json` runs 14-15 frames deep in the AnyIO worker
thread. The hook path (`--hook` UserPromptSubmit, SessionStart, Stop) is as shallow (981, on a local
3.11.15).

**The change.** `parse_json` (the `parseJson` adapter) reads at most 512 deep
(`_PARSE_JSON_DEPTH`), counted as `JSON.parse` nests: each array or object one level, the outermost
included. Past it, the RangeError `Maximum call stack size exceeded`, which the compiled `catch`
sees, so the sidecar is malformed. 512 is below every supported CPython's limit, with more than 450
frames to spare on 3.11, where the real paths use 15. The depth is found by `_json_too_deep`, a non-recursive
scan of the brackets outside strings; the 513th opener counts only when `json.loads` of the text
before it stops there with `Expecting value` (a well-formed prefix wanting a value), so a text
malformed earlier keeps `json.loads`'s own refusal, as a recursive descent would give it. A text
with no more than 512 brackets is not scanned. `RecursionError` stays mapped to the same RangeError
as the backstop, and the recursion limit is not touched.
- Checked against an oracle: CPython 3.11's `json.loads` with the recursion limit set so it reads
  exactly 512 deep, over 20,000 seeded texts nested around 512 in arrays and objects, with random
  corruptions. 0 differences in outcome (read, refused, too deep), but for 31 texts where 3.11 itself
  raised `RecursionError` while building a decode error within two frames of its limit: each is
  malformed no deeper than 512, and `parse_json` refuses it with `json.loads`'s message.
- The outcome of 20,000 more seeded texts (trailing commas included) hashes the same on 3.11, 3.12
  and 3.13.
- A 1.8 MB sidecar of 3,000 facts scans in 13 ms (its `json.loads` is 3 ms).
- `cargo test`: `j89_5e_parse_json_reads_a_fixed_depth` pins 512 and 513 in arrays and in objects,
  brackets inside strings, refusals before the deep opener, and the same answers with the recursion
  limit lowered to 600.

**The cases** (`--suite recall-queries`): the ruling moved to 513, the first depth past Python's
(`ruling: sidecar/nested — read of a sidecar nested 513 deep (between python's limit of 512 and
node's stack)`, in lists and in objects), with its per-side literals; new agreeing cases at 512 in
lists and in objects, where both read, with per-side literals; 8,500 joined 20,000 and 100,000 as
agreeing (both read it as no sidecar). Depth now means the whole document's, the sidecar's own
three objects included. Against 8539b384's `runtime-py/src` (a scratch worktree, this suite): 4
failures on 3.12 (the stale ruling, the Python literal at 513, and 8,500 now agreeing) and 2 on
3.11 (the stale ruling and the Python literal at 513). With this change the suite passes with a
3.11, a 3.12 and a 3.13 reference interpreter (`--python`, venvs made by `uv` with the repo venv's
pinned versions).

**The other JSON reads J89-5d scanned do not take the limit.** The term cache (`cached`), the usage
ledger and the log segment (`LogSegment`), the token ledger and the pricing table all read through
`_js_json_parse`, the `JSON.parse` lowering: it catches `RecursionError` and rereads without
recursing (J88-2), so its answer is an unlimited read on every CPython, as V8's `JSON.parse` is.
Applying 512 there would make a divergence where there is none. `--suite recall-usage`,
`tokenledger`, `storage-log`, `pricing` and `eventlog` pass with 3.11 and 3.13 reference
interpreters too.

**Gates.** `--all` 23,298 cases, 0 failures, 241 ruled (23,289 before: nine cases added, and the
one ruling moved from 8,500 to 513). By suite: `--suite recall-queries` 491 (1 ruled),
`--suite recall-usage` 256, `--suite ts2py` 464 and `--suite wire` 712, each with 0 failures.
ts2py `cargo test`: 88 passed; clippy (`-D warnings`) and fmt are clean. `npm test`: 2,460 passed, 0
failed, 47 skipped. Full pytest: 5,335 passed, 0 failed. ruff is clean.

**Left open (found, not changed here).** The same version dependence is outside the generated
modules. The hand-written `json.loads` / `parseJson` pairs (`hookadapter`, `hostinstall`,
`skillfile`, `client`, `mcpreport`, `contract`) still read to CPython's own depth. A transcript line
1,200 deep makes `hookadapter._previous_prompt` answer `''` on 3.11 and `'first prompt'` on 3.12,
3.13 and Node. CPython 3.13 also changed `json.loads`'s refusal for a trailing comma (`Illegal
trailing comma before end of object: … (char 6)` where 3.11 and 3.12 say `Expecting property name
enclosed in double quotes: … (char 7)`), so `parse_json`'s message moves with the version. (Closed
by J90-P8F: every `json.loads` in the package, the adapter's included, now raises 3.12's sentence;
see *CPython 3.13 and 3.14 answer 3.12's answers*.) The
sidecar's bare `catch` cannot see it, but `j89_5a_queries_adapters_answer_like_node` fails with
`TS2PY_PYTHON` set to 3.13. PyYAML's depth for the grants config does not move with the version
(492 nested flow sequences at the top level on 3.11, 3.12 and 3.13), but it does move with the
caller's stack.

### Lowercase and digits on every supported CPython (#316 G3, J89-7)

J89-R found two things that moved with the interpreter's Unicode table.

**Lowercase (F1, fixed).** `blockKey`, `claimSlot` and `mergeDescriptions` key on
`.toLowerCase()`. ts2py's runtime helper raised `TypeError` on any U+03A3 and on 55 code points.
So on a fact present in both layers, a body, claim or description in ordinary Greek made Python's
`memory_dream` fail, and the Stop hook's dream child exit 1 (and spawn again on every Stop). Main's
Python and Node merged it, with the same bytes. The helper (`tools/ts2py/python/ts2py/runtime.py`) now
answers as Node 26.13 does, measured over every code point on CPython 3.11, 3.12, 3.13 and 3.14:
- **The 55 code points.** CPython 3.11 to 3.13 have no lowercase for any of them (`Cn` there; 28 on
  3.14). Each maps one code point to one code point in Node. The helper maps them to Node's answer
  first, then calls `str.lower()`. Every single code point matches Node, with 0 refused.
- **Final sigma.** J89-7 still lowered U+03A3 with `str.lower()` and raised when the walk out
  from it reached a code point CPython has as `Cn`, or U+0295, or U+1171E. J89-R2 found that
  refused far more than it had to: `ΓΕΙΑ ΣΑΣ🫩` (U+1FAE9, Unicode 16) in both layers made Python's
  dream raise on 3.11 to 3.13 (`🩷`, U+1FA77, on 3.11), where Node merged and both would pick `ς`.
  Since J89-7b the helper lowers each U+03A3 itself, by Unicode's Final_Sigma walk, and never
  refuses. The walk skips Case_Ignorable code points and asks whether the first other one is
  Cased. For the code points the two tables classify apart, it uses Node's class, embedded as
  ranges (`_JS_SIGMA_NODE`). Everywhere else it uses CPython's own, read back off `str.lower()`.
  J89-7b's sweep probed every code point in both walk directions, against Node 26.13. The two
  tables classify 307 apart on 3.11, 196 on 3.12 and 3.13, and 100 on 3.14, each set inside
  3.11's. Every one is `Cn` to CPython but U+0295 and U+1171E. Both sides walk symmetrically
  everywhere. Embedding Node's class answers all inputs; keying a refusal on
  `unicodedata.unidata_version` would still refuse those 307 (or 196, or 100).

So `ΣΟΦΟΣ`, `ΟΔΟΣ 🫨` and `ΟΔΟΣ🫨`, `ΑΣ` directly before U+0378, ǅ and U+1C89 answer as Node does on
every supported CPython. Nothing refuses. The measure, the eleven contexts of J89-R2 over every code
point (12,255,232 strings), its 402,145 fuzzed strings, and every pair of the 307 in four contexts
(407,044), on CPython 3.11.15, 3.12.13, 3.13.18 and 3.14.10:

| CPython | J89-7 (8165f9a7): ok / refused | J89-7b: ok / refused | wrong, before and after |
|---|---|---|---|
| 3.11 | 3,956,872 / 8,298,360 · fuzz 366,129 / 36,016 · pairs 4,108 / 402,936 | all ok, 0 refused | 0 |
| 3.12 | 4,001,762 / 8,253,470 · fuzz 372,918 / 29,227 · pairs 63,316 / 343,728 | all ok, 0 refused | 0 |
| 3.13 | 4,008,032 / 8,247,200 · fuzz 372,918 / 29,227 · pairs 63,316 / 343,728 | all ok, 0 refused | 0 |
| 3.14 | 4,059,882 / 8,195,350 · fuzz 382,628 / 19,517 · pairs 201,616 / 205,428 | all ok, 0 refused | 0 |

There is no ruling, because the two runtimes agree. A string without U+03A3 is `str.lower()`. The 55
are translated first only when a precompiled class of ranges finds one. J89-R2 measured the
`translate` on every non-ASCII string as 2.01 → 12.85 µs. J89-7b measured a 63-character Thai and
Latin string without U+03A3 on 3.12 at 2.68 µs on 8165f9a7 and 0.55 µs now (`str.lower()` alone:
0.17 µs). `--suite dream` has four arms (`J89-7 dream lowercases …`), each with a block that differs
only in case: Greek with a medial-sigma twin, U+1C89 against U+1C8A, ǅ against ǆ, and (J89-7b)
`ΣΑΣ🫩` and `ΣΑΣ🩷` with a `σασ🫩` twin. Each arm compares the plan and both trees, plus a per-side
literal survivor. The first three were red on c4fc46d9 on 3.11, 3.12 and 3.13. The fourth was red
on 8165f9a7 on the same three. `--suite ts2py` compares 28 inputs against Node's `toLowerCase()`
(`runtime/toLowerCase …`). Four of them put each of the 307 on both sides of a U+03A3. The 10
inputs J89-7 and J89-R2 found refused, which now answer, are pinned against Node's answer typed into
the suite. Flipping one range's class in the table (cased to neither, ignorable to neither) reddens
those cases.

**Relative dates and the interpreter's Unicode table (F2, documented).** Node's `pyRelativeScan` and
`pyIntDigits` reproduce CPython 3.12's `\d` (UCD 15.0, 680 digits). CPython 3.11's `int()` and `\d`
read UCD 14.0 (660). So on 3.11, a count spelled in one of the 20 digits Unicode 15.0 added (Kawi
U+11F50..U+11F59, Nag Mundari U+1E4F0..U+1E4F9) is not a count to Python. `It landed 𑽓 days ago.`
stays unresolved there, where Node and CPython 3.12 to 3.14 date it 2026-09-03. Main's
hand-written dream did the same. This was not changed: the adapter is Python's own `re` and
`int()`, and pinning 3.11 to 15.0 would mean carrying a digit table for `\d`, `\b` and `\w`. In
`--suite dream`, the digit-count literal is keyed on the UCD version the reference reports: 660 on
14.0, 680 on 15.0 and 15.1, 760 on 16.0 (3.14). An unknown version is red. Each count went red on
3.11 and 3.12 when moved by one. A `ruling:` case pins the 3.11 Kawi answer, with each side's
literal; from UCD 15.0 the same case is an agreeing one.

### The component (#316 G3 U4, J89-6): generated, behind its shim

Since J89-6 `bantamkit.memory.component` runs `_generated/component.py`, compiled from
`runtime-ts/src/memory/component.ts` in the G1/G2/G3 call (it imports the compiled store, native
layer, queries sidecar, layers, dream, retrieval and usage ledger). The hand-written 1,745-line
module is retired; `memory/component.py` is the shim. G3 is generated end to end: usage,
retrieval, store, native, queries, layers, dream and component.

**The shim** keeps every name its callers use (grep over runtime-py, its tests and tools/, then the
suites): `Memory` with `layered`, `layered_for_eval`, `save` / `save_outcome` (and the old `_save`
/ `_recall` aliases), `recall` / `recall_outcome` / `recall_file`, `layer_stores`, `inject_candidates`,
`rank_all`, `usage`, `usage_census`, `queries_coverage` / `queries_missing` / `queries_write`,
`index_accounting`, `compact` / `compact_outcome`, `dream` / `dream_outcome`, `store`, `k`,
`repaired`, and the privates callers reach (`_layers`, `_show_layers`, `_binding`, `_pooled`,
`_fact_count` for `mcpserver`'s status line, `_unreadable_layers`, `_searchable_facts`,
`_walk_ascended`, `_binding_diagnosis`, `_is_profile_store`); the frozen `SaveOutcome`,
`RecallOutcome`, `CompactOutcome`, `DreamOutcome` (its `result` the dream shim's `DreamResult`);
and `normalize_name`, `_profile_store`, `_same_directory`, `_layer_label`. The boundary follows
J89-4b ruling 1: Python callers keep the dataclasses and plain values, facts cross as `Fact`s (the
store shim's `_fact_out`), a `TouchContext` as the object component.ts reads, a `StoreBinding` as
the layers module's shape, and a JS `TypeError` as the bare `TypeError`.

The layers are the stores a Python caller holds. The generated component constructs its stores
with `new MemoryStore(...)`; the shim binds that name in the generated module to the store shim's
core (`_Core`, which now also takes `(root, options)` and makes its own `MemoryStore` shim), so
every layer, the project store included, is a core with a Python face: `Memory.store` and
`_layers` hand back the same `MemoryStore` objects whose `snapshot()` pins what the generated
component reads. A native layer's face is made once, on first read; the skill layer is the
`SkillStore` adapter over the hand-written `SkillStore`. `_layers` is a list a caller may append
to or insert into (the eval harness, the dream and queries tests do): the layer is bound into the
generated component's own list. The usage ledger the component builds is the usage shim's (its
fold and rotate thresholds read at call time). `RECALL_MIN_SCORE_RATIO` and `_profile_store`,
which `tools/eval/recall/tune.py` and `test_memory_compact_tool.py` rebind on this module, are
forwarded to the generated module, as `retrieval`'s weights are. `setup()` and `batch()` stay
Python-only (ruling 1; *Where the two runtimes deliberately differ*).

**What is not compiled, and how it is reached** (`tools/ts2py/RULES.md`, *J89-6 rules*). The skill
layer, the touch modules, the asset pack, the reply-language frame and CPython's `str.lower()`
are reached through 15 adapter rows onto the hand-written modules component.ts's imports port.
Two moves made that possible without changing Node: `recallFile`'s repository half
(`process.cwd()`, `findRepo`, the touch graph over the layers, `lsFiles`, `FileSet`, the history
line, the linked names) moved statement for statement into `touch/recallfile.ts`'s `fileLinks`,
and `fire`'s three calls into `skills.ts`'s `fireOn`; the adapters make the reference's calls in
the reference's order. The census counted 82 refusals; the TS refactors that cleared the rest
(named imports for two namespaces, counted loops for `findIndex` and destructured `forEach`
parameters, `layerKind` for `split(':', 1)[0]`, `[...text]` for `Array.from(text)`, a `map` copy
of `PROJECT_STORE`, destructures for three property reads ts2py takes for method values, the
private `usage()` renamed `ledger()`) leave Node's answers unchanged: 25a9fadc's `dist` against this
tree's over a 41,166-record seeded corpus of component calls and store trees, 0 differences (three
wall-clock fields masked that differ between two runs of one dist too); `npm test` green.

**Python's answers are unchanged.** One Python-only harness answer differs from Node's and is kept
at the boundary rather than chosen: `layered_for_eval` with an engine other than `v2` raises
`ValueError("unknown engine: 'v1'")` as the reference did, where component.ts throws an `Error`
with the engine JSON-quoted (`unknown engine: "v1"`); no MCP tool, CLI or hook reaches it, and no
ruling covers it (reported to the orchestrator). `normalize_name` reaches `str.lower()` through
`pyLower`, where ts2py's `.toLowerCase()` would refuse `Σ` (a case `--suite store` pins); since
J89-7b that adapter is the runtime's `toLowerCase()` (see *Lowercase and digits*). Three
tests that reached the hand-written internals follow the generated ones:
`test_layered_reads_every_layer_and_ranks_them_as_one` spies on the profile store's core (the
method the component calls), and `queries_ref.py` hooks the generated `QueryScorer.column` and the
generated `layer_terms` beside the Python ones it already hooked (the trace and `force_off` read
what the generated walk does).

Parity beyond the suites: a seeded plan of 33,105 calls (20,000 `normalizeName`; 1,000 scenarios
over `layered`, `layeredForEval` and a budgeted store, with and without a skill, a native directory,
a profile collision and the trigger switch: save, recall, recall by name, `includeArchived`, the
outcome filter, queries listing, writing and coverage, compact, dream dry and applied, inject, rank,
accounting and the binding diagnosis) run by Node and by the generated Python and serialized by
`JSON.stringify` / its port: identical.

**Writes (J89-6 probe, both sides).** One bed under umask 022: 16 saves across the project store,
the profile store and a budgeted store (a duplicate nudge for a bent name, a validation refusal,
four budget refusals, a 0640 fact rewritten), a queries write, a stamped recall (ledger line and
read-repair), a dream applied across a diverged name collision with mtimes set, and two compactions
(three facts archived), through 25a9fadc's Python, this tree's Python and Node: the three trees
(28 entries) are identical byte for byte and mode for mode, and all 21 replies are identical. Concurrency: 4 Python and 4 Node processes saving 30 distinct facts
each through `Memory.save` into one store, each rewriting one shared name after every save (480
saves): 241 fact files, none lost, none duplicated, every one parses, no temp left, `index.md` 241
unique lines and equal to `index_text()`.

**Cost (J89-6, macOS arm64, CPython 3.12.13, Node v26.13.0; n = 9 interleaved rounds, medians;
before = `25a9fadc`, after = this tree; the project store a copy of this repository's
`.bantamkit/memory`, the profile a copy of `~/.bantamkit/memory`, 314 files, HOME scratch; each MCP
tool called through `build_server` over an in-process `mcp` client, median of three warm calls).**

| Path | Before | After | |
|---|---|---|---|
| cold `import bantamkit.memory.component` (a process) | 118.28 ms | 118.71 ms | +0.4% |
| `memory_recall` | 2.46 ms | 2.80 ms | +13.6% |
| `memory_recall`, a name-shaped query | 1.44 ms | 1.44 ms | +0.5% |
| `memory_save` | 32.02 ms | 31.93 ms | -0.3% |
| `memory_queries` (the missing list) | 1.58 ms | 2.18 ms | **+38.1%**: the body excerpt (`[...body].slice(0, 600).join('')`) spreads each body into one-character strings and joins them through the general `join` lowering (a nullish test and `_js_str` per character), in place of a slice |
| `memory_compact` | 12.51 ms | 12.59 ms | +0.6% |
| `memory_dream` (dry run) | 343.33 ms | 341.15 ms | -0.6% |
| `bantamkit_status` | 12.64 ms | 12.08 ms | -4.4% |
| `--hook` UserPromptSubmit, a process | 366.73 ms | 363.49 ms | -0.9% |
| #204 bar: 5,000-fact recall p50 of 20, a new `MemoryStore` each (bar 15 ms) | 8.03 ms | 7.99 ms | -0.5% |
| the same through a new `Memory` each | 10.96 ms | 11.99 ms | +9.3% |
| Node import / `recallOutcome` / `saveOutcome` / `queriesMissing` / `dreamOutcome` | 18.51 / 1.029 / 25.78 / 0.769 / 45.94 ms | 18.22 / 1.013 / 25.86 / 0.755 / 45.58 ms | -1.5% / -1.5% / +0.3% / -1.9% / -0.8% |

Every process-level path is within 1%; the one flag is a per-call 0.6 ms on the queries listing,
whose remedy is ts2py work (a join of a list proven to hold strings), not a shim change.

**Gates.** The F4 byte comparison (`ts2py/committed/component.py`, 60,037 bytes committed against
60,035 fresh) and the sha256 header (`test_generated_module_names_the_typescript_on_disk[component.py]`)
each red once on a scratch edit, then green. `--all` 23,299 cases, 0 failures, 241 ruled (no
ruling moved, none STALE). ts2py `cargo test` 90 passed (`j89_6_component_compiles_with_the_g3_call`,
`j89_6_component_adapters_answer_like_node` added); clippy (`-D warnings`) and fmt clean. `npm test`
2,460 passed, 0 failed, 47 skipped (`memory-skills.test.mjs` reads the ledger path through the
renamed private `ledger()`). Full pytest 5,337 passed and one failed, `test_build_identity`'s
k-floor mutation, which edited the hand-written line; it now edits the generated one, and the file
passes (12). The touched pytest files under `python:3.11` in Docker, `test_storage_bar.py` among
them: 604 passed. ruff is clean. A 20,000-query fuzz of the exact-name walk (the name-shape regex
and its strip, against a store holding three hyphenated names): 0 differences against Node (2,974
hits, 517 misses, 16,509 outside the shape).

### The lock and the hot index (#316 G4, J90-2): generated, behind their shims

Since J90-2 `bantamkit.storage.lock` and `bantamkit.storage.hotindex` run `_generated/lock.py` and
`_generated/hotindex.py`, compiled from `runtime-ts/src/storage/lock.ts` and
`runtime-ts/src/storage/hotindex.ts` in the one G1/G2/G3/G4 ts2py call. The hand-written index
(1,034 lines) and lock (77) are retired; the modules are shims. The generated store builds the
generated `HotIndex` itself (the two import each other: ts2py writes an import cycle's imports at
the end of each module, `tools/ts2py/RULES.md`, *J90-2 rules*), and `MemoryStore.index()` /
`NativeStore.index()` answer it through the shim (`HotIndex._of`, one shim per index), so a Python
caller and the store read one index.

**The Python surface is unchanged.** `exclusive(path, wait_ms=, stale_ms=, poll_ms=)` stays the
context manager its seven callers enter, over the generated `acquireLock` / `releaseLock` (lock.ts's
`exclusive` split in two, Node's answers unchanged); `LOCK_WAIT_MS` / `LOCK_STALE_MS` /
`LOCK_POLL_MS` are the generated values. `HotIndex(source, kind, home, index_dir=None)` keeps its
snake_case methods, `Path` attributes (`source`, `home`, `path`, `dir`; `real` a string), dicts
where the generated class answers Maps (`docs()`, `names()` as a keys view, `postings()`, `query()`,
`segments()`, `query_words()`, `df()`, `skipped`), `avgdl()` a float, `parse_file()`'s
`(doc, reason)` pair and `ValueError` for an unknown kind or refresh mode (the reference's
sentences; the generated class raises Node's). `size()` is the TypeScript's `docCount()` (renamed
under J89-4a's clash ruling: every Map's `.size` is a read of that name). `head_text`, `sha16`,
`shard_of`, `decode` (a `malformed postings` refusal still a `ValueError`), `encode` and the
constants are the generated ones; `dumps` stays the hand-written `json.dumps(..., sort_keys=True,
ensure_ascii=False, separators=(",", ":"))` because the UNGENERATED modules write with it
(`touch.graph`, `skillreport`, the refs; `coldindex` and `retention` until J90-3 generated them), and
`_loads` / `_iso` stayed for the hand-written cold index until J90-3 generated it (retired then). `no_gc` is Python-only (the table above). One test
reached a private: `test_touch_graph.py` reads `idx._loaded()["shards"]`, which the shim keeps as the
generated head's `shards` (no test was rewritten).

**What the generated index reads through an adapter.** `parseNative` stays the adapter onto
`divergence.parse_fact` (the #228 row above: the reference's index keeps reading a native file with
PyYAML); since the generated index reads a native file's `links` and `tags` from `parseNative`'s
`meta`, the adapter now carries it, as the reference's `_secondary` read it. The realpath an index
is named by stays `os.path.realpath` (`nodeRealpath`, below); `extractRefs` / `factRefs` are
`touch.refs`; the serialisation is `dumpJsValue` (`json.dumps` of the value as `fromJs` reads it).

**Found by J90-2, settled by J90-3 to Node's answer (the orchestrator's ruling): a source through a
dangling symlink.** The rest of this paragraph is J90-2's account as it stood; since J90-3 the
`nodeRealpath` adapter is Node's function (`realpath(3)`, the parent resolved and the name joined
as spelled where it throws), so both runtimes name the index by the link, and the case is agreeing
(the subsection below). The reference names an
index by `sha16(os.path.realpath(source))`, and `os.path.realpath` follows a dangling symlink to its
missing target; Node's `realpathSync` refuses it and the port keeps the link as spelled. So the two
runtimes name such a source's index (and its head's `source`) differently, and each rebuilds the
other's. It predates generation (9c6bc181 answers the same on both sides) and generation keeps it:
the generated Python reaches `os.path.realpath` through the `nodeRealpath` adapter. Pinned in
`--suite storage-index` as `ruling: UNRULED DIVERGENCE (J90-2) the hot index of a source through a
dangling symlink — realpath and sha16` with a literal per side; a live symlink is compared and pinned.
Left to the orchestrator.

**Python answers that moved to Node's (inputs no user path is known to reach).** Generation makes
the Python side answer what the TypeScript answers where the hand-written module differed from it
on an input no suite held: an `exclusive` path holding a NUL (main raised CPython's `ValueError`;
now Node's: the open fails, the wait runs out and the block runs unlocked); a source whose realpath
holds a POSIX surrogateescape byte (main raised `UnicodeEncodeError` out of `sha16`; now hashed as
Node's UTF-8 writes it); a frontmatter whose `tags:` / `links:` line follows a `\r`, U+2028 or
U+2029 (JS's `^` under `m`; main's `re.MULTILINE` saw only `\n`); a `KeyError` out of the native
`metadata:` read (main raised; now `{}` as for any other refusal); `HotIndex.path` built with
`path.join` (a `..` in `home` is collapsed); an index file's JSON integer of 16 or more digits or
`-0` read as `JSON.parse` reads it (main read the exact Python int, J90-1F having moved only floats).

**Settled before generation (J90-1F, 9c6bc181), recorded here by J90-RF (F5).** J90-1 pinned sixteen
storage inputs `UNRULED`; J90-1F settled fifteen to one answer (the sixteenth is the #228 row in the
divergence table). The ones a 0.40.0 Python user can see, each pinned in `--suite storage-index` or
`storage-lock` with a literal per side: a hand-edited head whose `lens_total` holds `1.0` (0.40.0
rebuilt the index; now read as `1` and trusted: Node's), a head whose `full_at` is spelled with a
lowercase `t` and `z` (0.40.0 trusted it; now unreadable, so a full refresh rewrites it: Node's), a
postings shard whose run length is `1.0` (0.40.0 raised `malformed postings` on every query of the
shard; now `1`: Node's), a postings shard, a head line or a cold segment holding an invalid UTF-8
byte (refused and rebuilt on both: Python's answer, Node moved), and the lock file's mode (0.40.0
created it `0o755`; now `0o666` before the umask, `0o644` under 022: Node's). `CHANGELOG.md`
entries 18 and 21.

**Write and lock safety (J90-2 probe; this tree's Python and Node against 9c6bc181's).** On a 2 MB
HFS+ volume (`hdiutil`) and under `ulimit -f 64`, over a copy of this repository's `.bantamkit/memory`
(92 facts; the facts on a normal disk, the index on the volume): a rebuild into 48 KB of free space
(ENOSPC mid-shards), the same with space back, a build then one new fact patched onto a FULL volume,
the same with space back, the lock taken on a full volume, and a rebuild under `ulimit -f 64`
(EFBIG, a short write) then without it. All eight steps answer identically on the four sides,
byte for byte on every index file (`full_at` masked): the refusals leave `persisted` false, no
`.tmp` file and no head, the patch onto a full volume answers `patched` from memory with the old
head on disk, and the next reader with space rebuilds or patches to the same bytes; the lock on a
full volume is not held after its 200 ms wait, and no lock file is left. Lock: a free lock, a stale
one (20 s old) taken over at once, a fresh one waited out (200 ms), a wall clock stepped +5 s and -1 s
mid-wait (still ~200 ms: the wait is on a monotonic clock), stepped +100 s (the lock then looks stale
and is taken), and a directory that refuses the lock file (given up at once): identical on all four
sides. Concurrency: 3 Python, 3 Node and one 9c6bc181 Python process, 400 locked read-increment-
rename rounds each through `exclusive` on one counter, four runs: 2,800 every time, no body run
unlocked, no lock or temp file left.

**Real data (J90-1's `run_idx.mjs` over copies of the user's stores, 14 sources: 12 native
directories, this repository's and the home store; 674 docs).** This tree's Python against
9c6bc181's Python: 14 of 14 sources identical (docs, skipped, loose, the head's bytes but `full_at`,
every shard's bytes); this tree's Node against 9c6bc181's Node: 14 of 14. Python against Node: 11 of
14 on both trees alike — the three others differ only in a `skipped` sentence for two native files
PyYAML and the codec refuse in their own words (a `mapping values are not allowed here` against the
port's named refusal): a difference 9c6bc181 answers the same way, not one J90-2 moved.

**Cost (J90-2, macOS arm64, CPython 3.12.13, Node v26.13.0; n = 9 interleaved rounds, medians,
one fresh process per side per round; before = 9c6bc181, after = this tree; the real-data copy above,
14 sources, 674 docs; the first save into a copy of this repository's store whose index exists; the
#204 bar store of 5,000 synthetic facts).**

| Path | Python before | Python after | | Node before | Node after | |
|---|---|---|---|---|---|---|
| cold import (`hotindex` + `store`) | 95.11 ms | 95.69 ms | +0.6% | 7.81 ms | 8.00 ms | +2.4% |
| cold build, 14 sources | 409.12 ms | 620.27 ms | **+51.6%** | 266.95 ms | 264.69 ms | -0.8% |
| a new index per source: fast refresh, `segments`, `cols` | 4.73 ms | 11.60 ms | **+145.0%** | 4.83 ms | 5.08 ms | +5.2% |
| held indexes: fast refresh + `query`, x20 | 5.10 ms | 25.66 ms | **+403.0%** | 4.06 ms | 3.95 ms | -2.7% |
| a full refresh of every source (nothing moved) | 14.89 ms | 36.68 ms | **+146.4%** | 31.17 ms | 31.17 ms | +0.0% |
| the first `memory_save` (`MemoryStore.save`, index patched) | 33.12 ms | 55.12 ms | **+66.4%** | 29.01 ms | 27.54 ms | -5.1% |
| #204 bar: 5,000-fact recall p50 of 20, a new `MemoryStore` each (bar 15 ms) | 8.39 ms | 13.84 ms | **+64.9%** | 2.89 ms | 2.70 ms | -6.7% |

Every Python path that touches the index is slower: the generated index runs each read through the
runtime's general helpers (`_js_get`, `_js_lt`, a callback per element) where the hand-written one
used C-speed set and `min`/`max` checks over a column and `json.loads` with native integers, and the
generated stat and hash calls go through adapter objects (`BigIntStats`, `Hash`). Before J90-2's runtime
fast paths (JSON integers, `new Map(entries)`, `Object.keys`/`entries`, the two `every` tests) the bar
was **20.89 ms, over its 15 ms**; with them it is 13.28-13.84 ms, under the bar with 1.2-1.7 ms to spare.
Carried to #317 (ts2py performance), not fixed here: a typed column check that reads a proven-int
list at C speed, a stat adapter that does not build an object per call, `shardOf` without the `Hash`
adapter, and the decode loop's per-element dispatch. Node moves within ±7% on every path (the
TypeScript changed only in spelling); the one move past 5%, +5.2% on the new-index path, is
0.25 ms on 5 ms, and the paths beside it moved the other way.

**Gates.** The F4 byte comparison (`ts2py/committed/hotindex.py`, `ts2py/committed/lock.py`) red on a
scratch hand edit of each committed module, then green (507 cases); the sha256 header
(`test_generated_module_names_the_typescript_on_disk[hotindex.py]` / `[lock.py]`) red on a one-byte
change to each TypeScript source, then green. The `ruling: UNRULED DIVERGENCE (J90-2)` pin goes
STALE (and its python literal red) when the realpath adapter keeps a dangling link as Node does.
`--all` 23,462 cases, 0 failures, 243 ruled (no ruling moved; the #228 hot-index ruling holds).
ts2py `cargo test` 94 passed (`tests/g4.rs` added: four tests, each red under its mutation: a
`delete` that always answers true, an `every` fast path that takes a bool, a JSON fast path that
never falls back, an iteration that visits deleted entries, `2**53` lifted as an int, the cycle
undetected); clippy (`-D warnings`) and fmt clean. `npm test` 2,460 passed, 0 failed. Full pytest
5,344 passed, 0 failed (before the runtime fast paths `test_storage_bar.py` failed at 20.91 ms).
The touched pytest files under CPython 3.11.15: 537 passed; `storage-lock`, `storage-index`,
`storage-log`, `storage-cold`, `storage-tiers`, `storage-retention` and `store` green with a 3.11
reference (`--python`). ruff is clean.

### The cold index, retention and the tiers (#316 G4, J90-3): generated, behind their shims

Since J90-3 `bantamkit.storage.coldindex`, `bantamkit.storage.retention` and
`bantamkit.storage.tiers` run `_generated/coldindex.py`, `_generated/retention.py` and
`_generated/tiers.py`, compiled from the TypeScript in the one G1/G2/G3/G4 ts2py call, and
`storage/index.ts` (the re-export table) is compiled too, as `_generated/index.py` (held by the F4
compare; `bantamkit/storage/__init__.py` stays the hand-written package file over the shims). The
hand-written cold index (322 lines), retention (859) and tiers (249) are retired; no "#316 G4 not
generated" adapter row remains (the `ColdIndex` / `ColdIndexError` rows are retired:
`tools/ts2py/RULES.md`, *J90-3 rules*). `storage/retention-child.ts`, Node's child entry script (a
top-level `await`), is not generated: its Python counterpart is `python -m bantamkit.storage.retention`.

**The Python surface is unchanged.** `ColdIndex(name, home, cold_dir=None)` keeps its snake_case
methods, `Path` attributes, dicts where the generated class answers Maps, `query()`'s tuples, `add`
taking a dict (the TypeScript's `addDocs`: an exported compiled class's `add` would make every
`Set.add` of the call a run-time dispatch, J89-4a's rule) and `ValueError` for a bad name; the store
shim's `cold()` answers the generated index through it (`ColdIndex._of`). Retention keeps every
public name (`run_retention`, `parse_now` with its `ValueError`, `due`, `maybe_spawn(home, cwd, *,
server=False)`, `child_main(argv, now=None)`, `search_archived(checkpoint, search, home=None)`,
`sync_jobs` / `shiftwork_cold` answering the shim, `hook_log_reducer`, `bundle_bytes`, `job_doc`,
the constants); the tiers every function, `settings_paths` as `Path`s and a `Memory` handed over as
the generated one it wraps. The retired `hotindex._loads` / `_iso` went with the hand-written cold
index.

**Three seams stay CPython.** The archive's fsynced write (`retentionFs`, moved to
`storage/retentionfs.ts`; the reference's `_write_archive`), the detached spawn (`storage/
retentionspawn.ts`; `subprocess.Popen` of `python -m bantamkit.storage.retention`), and the child's
async half: `childMain` awaited the experience miner after a dynamic `import()`, so retention.ts
keeps the compiled sweep half (`childSweep`: claim the day, run, record) and `storage/
retentionmain.ts` (Node only) runs the skill audit and the miner after it; the shim's `child_main`
does the same two halves, the second synchronous. No `async`, `await` or `import()` is lowered.

**Tests that reached a retired private.** Three Python tests swapped `retention._write_archive`;
they swap `retention.retention_fs.writeArchive`, as Node's tests swap `retentionFs.writeArchive`
(the same strength: the one write retention makes). The cold index's `builtins.open` spy is
unchanged: the `coldFs` adapter reads through the builtin `open`, so it still counts every shard a
query opens. Node's tests and the conformance suites import `retentionFs` and `childMain` from their
new modules.

**Settled: a source through a dangling symlink (J90-2's divergence, the orchestrator's ruling:
Node's answer).** The `nodeRealpath` adapter is Node's function, `realpath(3)` and the parent where
it throws, so both runtimes name the hot index of such a source by the link; a path below the link
and a directory name spelled in another case on a case-insensitive filesystem (where `realpath(3)`
answers the filesystem's spelling and `os.path.realpath` kept the caller's) agree too. The
`ruling: UNRULED DIVERGENCE (J90-2)` case is an agreeing case with a literal per side, six cases red
on 743b54b9's adapter. No other `realpath` caller is in the J90-3 modules (retention names a root's
job index by `storeId`, the `pyRealpath` adapter, agreeing since J89-1F).

**Settled (J90-3F, the orchestrator: one shared sentence): a cold file that is not JSON.** J90-3
found a `ColdIndexError` for a manifest that is not JSON quoting each runtime's own parser:
`Expecting property name enclosed in double quotes: line 1 column 2 (char 1)` (CPython's `json`) on
the reference, `Expected property name or '}' in JSON at position 1 (line 1 column 2)` (V8) on the
port, pinned `ruling: UNRULED DIVERGENCE (J90-3)`. It predated generation (743b54b9 answered the
same). Both runtimes now answer ONE sentence with no parser's wording in it, for the manifest, a
segment and a shard alike: `cold index manifest unreadable: the file is not JSON` (`cold index segment
<id> …`, `cold index shard <NN> …`); `coldindex.ts`'s `readJson` throws its own `COLD_NOT_JSON` when
`JSON.parse` refuses, so the `coldErrorText` adapter only ever words a failed read (CPython's
`OSError` and decoder wording, on both sides, as before). The pin is an agreeing case in
`--suite storage-cold` with a literal per side (red on 2cca2564 on both sides). No other error
sentence in the G1–G4 generated modules quotes a JSON parser's message: `layers.ts` quotes PyYAML's
(ruled), `store.ts` / `native.ts` / `component.ts` quote the codec's own `BantamError`s, and the two
`parseJson` readers (`queries.ts`, `tiers.ts`) answer no sentence at all; a compiled read of a
`JSON.parse` SyntaxError's `message` still raises (`_JsJsonParseError`), so a new one cannot slip in.

**Fixed (J90-3F): the temps a killed writer left.** Every G4 writer writes `<file>.<pid>.tmp` and
renames it over `<file>`: the cold index's segments, shards and manifest, the hot index's head and
shards, retention's archives and `retention.json`. A SIGKILL (or a power cut) between the write and
the rename left the temp, and since the next write's pid differs, nothing ever removed it (J90-3
measured eight of nine killed children leaving `<archive>.<pid>.tmp`, on all three sides). Now each
writer removes ITS OWN stale temps, by one rule on both runtimes (`lock.ts`'s `removeStaleTemps`,
generated): a regular file named `<base>.<digits>.tmp` whose `base` the writer writes and whose
mtime is older than the lock's stale window (`LOCK_STALE_MS`, 10 s) — the window after which the
lock already treats its holder as dead. A pid-liveness test was not chosen: CPython's `os.kill(pid,
0)` on Windows sends CTRL_C rather than testing the pid, and a pid says nothing across pid
namespaces or hosts sharing a home. A live writer never holds a temp that old: each temp is written
in one call and renamed at once (the archive is now compressed BEFORE its temp is opened, on both
sides, so the temp is never idle while gzip runs), and every write moves its mtime. The cold index
sweeps under its lock on every `addDocs` / `compact` (so on every retention run, which compacts
every cold index); the hot index on every persist, under its lock, only names of its own index
(`<sha16>.json`, `<sha16>.*.json`), never another index's in the same directory; retention at the
start of each run (`retention.json`'s temps) and of each root's archive pass (`*.json.gz`'s),
reporting each removed path in `deleted`. `writeState` also removes its own temp when the write
fails, as every other G4 writer already did. A directory, a symlink, a fresh temp, a name with no
pid and a name the writer does not write are left. Pinned in `--suite storage-cold`,
`storage-index` and `storage-retention`, and by a test per writer on each side (red on 2cca2564).

**Settled (J90-3F): the audit half of the child.** The shim's `child_main` ran the skill audit and
the miner inside `except OSError`, so anything else they raised (an `ImportError` of the miner, a
`TypeError`) left the child with a traceback, where Node's `retentionmain.ts` swallows every throw
in its `catch`. Both are silent, and neither costs the sweep (which runs and is recorded before the
audit): the shim now catches `Exception`, Node's answer. Node's audit is reached through
`childAudit.daily` so its test can swap it, as the Python test patches `bantamkit.skillreport.daily`.
`--suite storage-retention`, `J90-3F an audit that throws a TypeError` (red on 2cca2564's Python).

**Accepted as is (the orchestrator, J90-3F), and why each side's answer is the one kept.**
- *The short archive write* (below): NODE's answer moved, to the reference's: Python's `fh.write`
  already wrote all or raised, so Python's answer did not move. Kept because a truncated archive
  renamed into place refused that job forever (`archive exists and differs`).
- *The opt-out switch read through JS `trim`*: Python's answer moved (743b54b9's `str.strip()` also
  stripped U+001C..U+001F and U+0085 and kept U+FEFF). Kept because the switch is one string read
  by both runtimes from the same environment: one reading, and the generated one is JS's.
- *A failed sweep's `error` record naming `Error`*: Python's answer moved (743b54b9 wrote the Python
  class, e.g. `ValueError`). Kept because `retention.json` is shared on disk, and the record is
  written by the compiled `childSweep`, whose `e.constructor.name` is the JS class on both sides.

**Python answers that moved to Node's.** Where the hand-written module differed from the TypeScript
on an input no suite held, generation makes Python answer Node's, each now pinned: the
`BANTAMKIT_RETENTION` / `BANTAMKIT_SKILL_AUDIT` switch read through JS `trim` (743b54b9's `strip()`
also stripped U+001C..U+001F and U+0085 and kept U+FEFF: `off\u001c` was off on the reference and
on on the port; `--suite storage-retention`, `J90-3 the BANTAMKIT_RETENTION switch is read through JS
trim`); a sweep's `error` record naming the JS class (`Error`) where the reference named Python's;
a `child_main` claim or sweep that raises anything (the reference let all but an `OSError` out); and
a cold-index JSON integer read as `JSON.parse` reads it (`-0`, 16 digits or more).

**Moved to Node's answer, found by J90-R (F4): a job doc whose `file` is absolute.** Compaction keeps
a doc of a root's job cold index while `<root>/<file>` is a file. `keepUnder` joins the two with
`path.join`, so an absolute `file` names a path UNDER the root; the hand-written Python (743b54b9,
0.40.0) joined with `Path /`, where the absolute path wins, and kept a doc naming any existing
absolute file. Over `a` (absolute, outside the root), `b` (`real.json`), `c` (gone), `d`
(`../root/real.json`), `f` (absolute, inside the root) and a later `e`, 0.40.0's Python kept
`a b d e f`; this tree's Python and Node keep `b d e`. bantamkit writes a root-relative `file` for
every job it archives (`.shiftwork/archive/<job>.json.gz`), so only a hand-built doc is absolute.
Node's answer is kept: the join is one rule on both runtimes, and the cold index is shared on disk.
`--suite storage-retention`, `J90-RF compaction drops a job doc whose file is absolute` with a
literal per side (both red when `keepUnder` resolves the path instead of joining it);
`CHANGELOG.md` entry 22.

**Fixed in Node (J90-3): a short archive write.** `retentionFs.writeArchive` wrote the archive with
ONE `writeSync` and did not read its count, so under a file-size limit (`ulimit -f`: write(2) answers
a short count, then EFBIG) a truncated archive was renamed into place; it failed to verify (nothing
was deleted) but stayed, and every later run refused the job as `archive exists and differs`. The
reference's `fh.write` writes all or raises (`archive write failed`, nothing left). The write now
loops as `logsegment.ts`'s `writeAll` does. `test_a_short_archive_write_renames_nothing_into_place_
and_is_refused` and its Node twin (red on 743b54b9's Node: `archive did not verify`).

**Measured (J90-3; this tree's Python and Node against 743b54b9's Python, macOS arm64).**
- *Real data* (copies of this machine's `~/.bantamkit` hooks, usage, touch logs and memory, this
  repository's `.bantamkit/memory` and `.shiftwork`; a fixed clock `2026-11-16T12:00:00.000Z`): two
  retention runs (the second a no-op), the status lines before and after, five archived-job
  searches, the job cold index, and a facts cold index per memory store built 100 docs a segment,
  queried, compacted, compacted with a `keep`. Over the whole tree (46 jobs, 40 archived, 394
  ledgers deleted, 2,529 logs folded, 90 rotated) Python equals Node in every answer and in all
  21,858 files (each `.gz` compared decompressed, a cold manifest's `created` masked); the status
  lines differ only in the bytes a rotated `.gz` holds (the ruled `gzipSync` row). Against
  743b54b9's Python the same over the tree without jobs 63..99 (21,675 files, 23 archived): equal,
  status lines included. 743b54b9 cannot run the rest: its tokenizer is quadratic on a long text
  that is not ASCII (job 63, 640 KB: over 120 s, killed), which this unit fixed in the runtime
  (`_js_code_units`, `tools/ts2py/RULES.md`, *J90-3 rules*; 0.93 s).
- *Write safety* (an 8 MB HFS+ volume and `ulimit -f`; 17 steps, three sides): a cold `add` into
  20 KB of free space (ENOSPC), a compaction on a full volume, an `add` under `ulimit -f 16`
  (EFBIG), each then with space back; retention archiving onto a full volume (the job that does not
  fit refused `archive write failed`, the others archived), the hook log folded and rotated on a
  full volume (left as it was, then folded and rotated), and retention under `ulimit -f 16`. Every
  answer and every file (a `.gz` decompressed) is the same on the three sides once the Node short
  write above is fixed; no `.tmp` is left and nothing is lost. A cold index whose sync failed
  mid-write keeps a segment and some shards with no manifest: rows no reader trusts, as designed.
- *A SIGKILLed child* (eight real jobs; the child killed after 1, 3 and 5 archives, nine kills on
  three sides): nothing lost (every original either still there or in an archive that verifies),
  and the next day's run completes, the tree then equal to an uninterrupted run's but for
  `retention.json` and, when the kill landed during an archive's write, that write's orphan
  `<archive>.<pid>.tmp` (eight of nine), never removed by a later run, on all three sides: found,
  not fixed by J90-3; fixed by J90-3F (above: a later run removes it once stale).
- *Speed* (n = 9 interleaved fresh processes, medians, this tree against 743b54b9): cold build
  (two 300-doc segments) 153.9 ms against 114.6 (+34%), 20 cold queries 165.9 against 35.7 (+364%),
  a compaction with `keep` 114.2 against 64.7 (+76%), a retention run over eight real jobs 1,408
  against 1,287 (+9%), the tier lines x5 1,792 against 1,767 (+1%), the first `memory_save` 55.7
  against 55.9 (0%); the #204 bar (limit 15 ms) 13.40 against 13.37 ms p50 over 15 rounds (the
  ranges overlap; the only changed code on that path, `_js_code_units`'s identity test, runs 59
  times a recall, about 3 us). The cold index is read only for `include_archived` and retention
  runs detached: carried with J90-2's index paths to #317.

### The last speed gap and what the hand-written Python got wrong (#316 G4, J90-P4)

**The 207 bytes.** J90-P3's real-data run had Python's `logs: usage/*` total 207 bytes under Node's
after retention (4,963,736 against 4,963,943). It is the ruled `gzipSync` row above, not a new
difference: of the 108 segments retention rotated, 94 differ in compressed size (CPython's level 9,
XFL 2, against Node's level 6, XFL 0), every one equal decompressed, and the 94 differences sum to
exactly 207. Python's and Node's status lines read over the SAME bytes (a copy of Node's bed for
each) are equal, the usage total included.

**A difference found and fixed: the held head's inode.** `hotindex.ts` keys its held head on
`${mtimeNs}:${size}:${ino}`; the adapter `Stats` carried no `ino`, so the generated Python read
`undefined` there and kept a head renamed over by one of the same mtime and size, where Node and
the hand-written 9c6bc181 reloaded it. Fixed in the adapter (`tools/ts2py/RULES.md`, *J90-P4
rules*), red on efda7291 in `test_storage_hotindex.py` and its Node twin.

**Speed** (n = 9 interleaved fresh processes, medians in ms; 9c6bc181 hand-written, efda7291, this
tree; the same machine and inputs as J90-P3):

| path | Python 9c6bc181 | Python efda7291 | Python J90-P4 | Node efda7291 | Node J90-P4 |
|---|---|---|---|---|---|
| hot index build (14 sources) | 402.6 | 500.8 | 495.8 | 262.9 | 260.8 |
| held query x20 | 6.6 | 10.3 | 9.2 | 4.1 | 2.8 |
| full refresh | 15.7 | 30.4 | 26.4 | 38.0 | 34.8 |
| cold build | 84.7 | 102.8 | 93.5 | 37.1 | 31.4 |
| cold query x20 | 35.9 | 57.3 | 57.6 | 21.0 | 20.7 |
| compaction with `keep` | 51.3 | 67.3 | 63.4 | 30.5 | 28.6 |
| first `memory_save` | 31.8 | 42.7 | 41.2 | 27.6 | 27.2 |
| retention run | 1,236 | 1,222 | 1,222 | 207 | 203 |
| tier lines x5 | 1,419 | 741 | 744 | 243 | 244 |
| #204 bar p50 | 8.07 | 8.53 | 8.39 | 2.66 | 2.66 |

Seven Python paths are still slower than the hand-written module. The floor is the same on each:
the time is in per-value JS-semantics helpers (`_js_get`, `_js_m_get`, `_js_strict_eq`, `_js_add`,
`_js_rows`) applied to values read from JSON, which prove nothing, so neither a typed method body
nor a Map fact reaches them (lowering a fresh Map's `get` / `set` inline in the cold query's row
loop measured 3%). What the hand-written Python did there instead is skip the semantics:

- it summed and compared JSON integers as Python ints: a cold query whose term frequencies pass
  2^53 answered `18014398509481986` where Node (and the generated module) answer
  `18014398509481984` (two rows of `9007199254740993`; measured on 9c6bc181, this tree's generated module
  and Node);
- its row check (`_is_rows`: `isinstance(r[3], int) and not isinstance(r[3], bool)`) admits every
  int past the doubles, which JS's `Number.isInteger` admits too but then rounds;
- it read the cold rows as trusted shapes (`for name, seg, _field, tf in table.get(t, ())`,
  `owners.get(name) == seg`, a `Counter`), where the TypeScript reads a short row's missing items
  as `undefined` and compares with `===`.

Each is an answer the generated module gives as Node does and the hand-written one did not; the
speed it bought is the gap above.

### Per-call shape guards, and the floor they leave (#316 G4, J90-P5)

**Adapter members audited.** `--suite ts2py` lists, with the TypeScript checker, every member the
compiled sources read off an object an adapter builds and asks the adapter what it provides: a
member read and not provided is red, so the `Stats.ino` class of difference cannot hide again
(`tools/ts2py/RULES.md`, *J90-P5 rules*; red with `ino` removed, and with `meta` dropped from
`parseNative`'s dict). None is missing today.

**What moved.** Three per-call guards in the adapters, each a C-speed check of a value's shape that
hands the value over as it is and otherwise takes the unchanged path: `_lifted` (`dumpJsValue`)
for lists, plain dicts and plain Maps of strings, safe ints and nested lists / dicts of them;
`hash_hex` / `Hash.update` for any string without a surrogate; `_os_text` likewise. No TypeScript
changed, so Node's answers and timings are unchanged.

| path (n = 9 interleaved, median ms [min..max]) | Python 9c6bc181 | Python e59e9661 | Python J90-P5 | Node e59e9661 | Node J90-P5 |
|---|---|---|---|---|---|
| hot index build (14 sources) | 406.9 [402.5..440.4] | 496.1 [493.8..499.7] | 483.0 [478.7..486.5] | 261.2 | 264.3 |
| held query x20 | 6.1 [5.5..7.8] | 8.5 [8.3..9.9] | 8.5 [8.2..8.9] | 3.1 | 3.0 |
| full refresh | 16.6 [16.1..18.5] | 27.2 [26.2..27.7] | 26.1 [25.1..28.0] | 35.1 | 36.0 |
| cold build | 85.4 [84.0..88.1] | 94.3 [93.9..125.2] | 89.7 [88.8..93.3] | 32.1 | 30.9 |
| cold query x20 | 36.0 [35.7..36.5] | 57.7 [57.3..57.9] | 57.6 [57.2..59.8] | 20.9 | 21.2 |
| compaction with `keep` | 51.1 [50.6..52.6] | 63.1 [62.4..65.0] | 58.6 [58.3..59.6] | 28.1 | 28.7 |
| first `memory_save` | 32.2 [31.7..33.4] | 41.8 [41.3..43.3] | 40.1 [39.4..43.3] | 27.2 | 27.1 |

**The floor, measured, path by path.** All seven are still slower than the hand-written module.

- *Cold query* (+60%, 1.1 ms a query): the row loop is 727 us generated against 173 us
  hand-written over the same 3,324 rows; the hand-written loop checks nothing (`for name, seg,
  _field, tf in rows`, `owners.get(name) == seg`, a `Counter`), and the body alone with no check
  is 167 us. Any sound fast copy must check each row (a list of four, two strings, a number a
  double holds) because a short row, a `true`, a `-0` or an int past 2^53 answers differently in
  JS (J90-P4's list): that check alone is 45-65 ns a row, and with every helper inlined the loop
  is still 314-374 us. A per-row guard that proves only the row's own items moved nothing (761
  us): the time is in the Map reads and `+` on a Map value, which no row guard proves, and a
  fallback row that stores an unproven sum rules out a Map value fact (RULES.md, *J90-P5 rules*).
  The shard read adds about 140 us over `json.loads` (ints exact past 2^53, NaN refused) and the
  owners map 65 us (`_js_get` of each segment's id).
- *Hot index build* (+19%): `derive` 125 ms against 75 ms. Tokenizing is the same 37 ms on both
  sides; the rest is the per-token count (`c[fi] = c[fi]! + 1` on a Map value, four helpers a
  token where the hand-written module calls `Counter(toks)` once a field) and the per-term
  postings: inlining every helper of that closure by hand moved the build 483 -> 472 ms. Parsing
  natives reads each file three times (`parseNative`'s own read for `meta`, then `safeRead`)
  where the hand-written module read it twice: 27 ms of `pyReadText`.
- *Full refresh* (+57%): the head write is 14 ms against 6 ms (the lazy tail parsed by the exact
  JSON reader on first need, 3.7 ms, which the hand-written module paid at open; the head's
  `_lifted`, now 2.0 ms, where `df` holds index-like keys that `_js_own_keys` must order).
- *Held query* (+39%): per-shard `lookup` / `decodeSegments` helpers on segments read from JSON,
  unchanged by this unit.
- *Cold build, compaction, first save* (+5%, +15%, +25%): what remains after the dump guard is
  the same row and Map helpers as the cold query, and `_js_rows` over rows the body could mutate
  (a list snapshot would not see an append JS sees, so the generator stays).

What the hand-written code skipped on these paths is J90-P4's list: JSON ints past 2^53 summed and
compared exactly where JS rounds, rows trusted without a shape check, a short row read by
unpacking where JS reads `undefined`.

### Guarded inline expansion, interpreter versions, and a mypyc spike (#316 G4, J90-P6)

**What moved (`tools/ts2py/RULES.md`, *J90-P6 rules*).** Inside a loop body, `m.get(k)`, `a === b`
/ `a !== b` and `a + b` are written inline: the helper's own first branch under an exact-type
guard, the unchanged helper call otherwise; an operand that is not a name or a literal is bound
once by `:=` in the guard's first test. No TypeScript changed, so Node's answers and timings are
unchanged. Seven helpers were measured; four (`_js_get`, `_js_num`, `_js_coalesce_value`,
`_js_list_at`) and comprehension elements moved no path past the three-helper form's spread and
put the wheel 12.4 KB over 794b63a6 (cap +4.8 KB); the three cost +3.1 KB.

| path (n = 9 interleaved, median ms [min..max], CPython 3.12.13) | 9c6bc181 (hand) | 794b63a6 | J90-P6 | J90-P6 + mypyc runtime | J90-P6 + mypyc runtime, coldindex, hotindex | Node |
|---|---|---|---|---|---|---|
| hot index build | 410.4 [404.8..416.6] | 484.8 [480.5..500.2] | 481.4 [476.8..510.9] | 447.3 | 431.2 [429.4..440.8] | 261.6 |
| held query x20 | 5.6 [5.4..5.6] | 8.9 [8.4..9.2] | 8.8 [8.3..9.7] | 6.9 | 6.4 [5.5..7.6] | 3.1 |
| full refresh | 17.4 [16.2..17.9] | 26.2 [25.5..27.6] | 26.3 [25.5..28.5] | 24.2 | 24.5 [23.5..64.2] | 36.0 |
| cold build | 85.6 [83.8..87.0] | 89.5 [89.1..91.6] | 86.8 [86.5..90.6] | 65.3 | 62.1 [60.2..63.3] | 30.8 |
| cold query x20 | 36.3 [35.6..38.9] | 57.7 [57.2..58.9] | 53.6 [53.1..55.5] | 50.5 | 31.2 [30.9..32.2] | 20.8 |
| compaction with `keep` | 51.3 [50.4..52.9] | 59.1 [57.4..60.8] | 57.1 [56.1..58.8] | 46.7 | 42.6 [41.9..44.1] | 28.4 |
| first `memory_save` | 32.1 [31.3..34.4] | 39.8 [38.9..41.3] | 39.1 [38.3..39.7] | 33.2 | 33.1 [31.6..35.5] | 27.2 |

The expansion's own share (cProfile, 794b63a6 -> J90-P6): the cold query's `_js_m_get` calls
118,120 -> 18,300, `_js_strict_eq` 66,520 -> 40, `_js_add` 33,240 -> 0, total tottime 177.0 -> 153.3
ms; the hot build's `_js_m_get` 145,995 -> 54,047, `_js_add` 70,470 -> 19,100. Every path is still
slower than the hand-written module in pure Python. Size: wheel 962,958 -> 965,687 bytes (cap
967,773); `_generated/*.py` 740,763 -> 759,495 bytes raw, 145,351 -> 147,999 gzip -9. The committed
form (literal operands left alone, `type(t := x)`) re-measured against the form in the table, n =
9 on 3.12: every path within the other's spread (cold query 55.1 against 55.6, hot build 491.0
against 493.6).

**The gap is the same on every supported interpreter** (same table, other CPythons; median ms,
hand / 794b63a6 / J90-P6): cold query 3.11 33.8 / 57.7 / 53.2, 3.13 32.9 / 59.4 / 55.0, 3.14 33.2
/ 53.9 / 50.8; hot build 3.11 414.9 / 497.0 / 495.8, 3.13 435.6 / 523.6 / 518.7, 3.14 417.0 /
489.2 / 487.1; held query 3.11 5.4 / 8.6 / 9.2, 3.13 5.6 / 9.8 / 9.5, 3.14 5.7 / 8.9 / 9.1. 3.13 is
the slowest of the four on every Python column; no version closes the gap (PEP 659's specializing
interpreter speeds the helper calls and the hand-written code alike).

**Whole-loop guard (measured, not built).** One C-speed guard over all rows of the cold query's
loop and an unchecked body (`micro_loop.py`, 3.12): 394 us against 751 generated as 794b63a6
lowered it, about 510 with the per-op expansion, and 178 hand-written; the guard alone is 228 us,
more than the body. On 3.14 the Python-level guard (487) beats the C-level one (508).

**mypyc (measured, nothing shipped).** mypy 2.4.1, CPython 3.12.13, macOS arm64
(`cp312-darwin` only; no other platform tag was built). The runtime compiles after: the classes
interpreted code subclasses or that multiply inherit `Exception` (`_JsObject`, the `Error`
hierarchy, `_JsMatchArray`) moved to an uncompiled sibling (compiled `isinstance()` did not see an
interpreted subclass of a non-native class); every other class `allow_interpreted_subclasses`;
surrogate literals as `chr()`; `-> bool` / `-> str` on `__bool__` and a property; `var-annotated`
and `override` silenced. `coldindex` and `hotindex` compile too with `-> object` on each property
and `ClassVar` on each `_js_*` class attribute. Compiling all 22 generated modules did not run:
a compiled class under the interpreted `Error` hierarchy segfaulted assigning `self.message`, and
with those classes non-native a hand-written `MemoryValidationError` refused its arguments.
`.so` bytes (raw / zip -9): runtime only -g1 1,755,648 / 472,034, -g0 1,342,608 / 399,501, -g0 +
`strip -x` 1,068,080 / 355,429; runtime + coldindex + hotindex 3,302,568 / 807,485, 2,598,056 /
682,958, 1,964,872 / 603,403; all modules 13,654,104 / 3,028,770, 10,900,120 / 2,551,492, 8,357,064 /
2,240,987 — against a 962,958-byte pure wheel. The pure-Python fallback needs no code: a platform
wheel would carry the `.so` beside each `.py`, and CPython's path finder tries extension modules
before source (verified: `bantamkit._generated.store.__file__` is the `.so`). What shipping it would
need from ts2py: `-> object` on each property it emits, `ClassVar` on each `_js_*` class attribute
(a native class turns a class attribute into a per-instance slot, which `_js_class_names` read as a
descriptor), the class split above, and `mypy_extensions` at run time for the `mypyc_attr`
decorators (or a guarded import). No value annotations: every gain above is untyped code compiled
to C calls; typed parameters were not tried.

### The generated Python compiled with mypyc, as it stands (#316 G4, J90-P7)

**What moved (`tools/ts2py/RULES.md`, *J90-P7 rules*).** The runtime and all 22 generated modules
compile with mypyc (mypy 2.4.1) straight from the committed files, with no step between: classes
are non-native with `_ClassVar` lists and `-> object` getters; a method holding a closure forwards
to a module function (mypyc/mypyc#1205); `instanceof` is `_js_instanceof` (`-> bool`); a module
variable is `_JsAny`; four shim-rebound names read at call time (`lib.rs`, `REBOUND`); the runtime's
constants are `_Final`; `fromJs` moved from the adapters into the runtime. The adapter module stays
interpreted. No TypeScript changed. Interpreted, every change is the same code or an alias of it:
`pytest`, every conformance suite and `--all` are green on the pure build AND with the `.so` files
beside the `.py` files (cp312, and cp311 for the `--python` 3.11 suites).

**Three mypyc faults that change answers silently**, each pinned by `tests/j90p7.rs` (compiled leg
with `TS2PY_MYPYC` set), none in a mypyc release or issue we could find for the last two:
a compiled `isinstance(x, C)` of a non-native class C tests the exact type (`flatten_classes`
takes it for a native class), so an interpreted subclass is not an instance and `_js_get` read
`undefined` from every adapter object; a class whose base mypy sees as `Any` (the adapters'
`BantamError`, built by `__getattr__`) is built on `object` alone; and an unannotated function
returning a generic `isinstance` answers the int `1` / `0` (the `instanceof` probe printed
`1,1,0` where Node prints `true,true,false`; the compiled `--all` run before that fix was green,
so no conformance case reaches an `instanceof` value). A module variable typed by its first value
refused a forwarded `GATE_FLOOR = 1.5` (TypeError, pytest red before `_JsAny`).

| path (n = 9 interleaved, median ms [min..max], macOS arm64) | 9c6bc181 (hand) 3.12 | J90-P7 pure 3.12 | J90-P7 mypyc 3.11 | 3.12 | 3.13 | 3.14 | hand 3.11 / 3.13 / 3.14 | Node |
|---|---|---|---|---|---|---|---|---|
| hot index build | 415.6 [406.4..435.8] | 494.1 | 420.1 | 430.9 [412.7..449.5] | 449.3 | 439.0 | 428.4 / 442.9 / 421.9 | 269.7 |
| open + query | 6.67 [5.7..7.1] | 6.62 | 5.91 | 6.75 | 6.21 | 6.26 | 6.22 / 6.22 / 6.10 | 5.16 |
| held query x20 | 5.59 [5.5..5.8] | 9.24 | 4.98 | 5.48 | 5.92 | 6.44 | 5.45 / 5.71 / 5.87 | 2.71 |
| full refresh | 16.68 [16.1..17.6] | 27.63 | 23.11 | 23.24 [22.0..24.4] | 24.39 | 24.68 | 15.91 / 17.89 / 16.75 | 37.56 |
| cold build | 85.83 | 89.67 | 45.55 | 47.99 | 53.01 | 56.54 | 92.14 / 107.43 / 87.65 | 32.52 |
| cold query x20 | 36.69 [36.1..38.9] | 55.57 | 40.93 | 30.69 | 32.67 | 35.12 | 34.21 / 33.50 / 33.65 | 21.66 |
| compaction with `keep` | 51.96 | 58.99 | 35.91 | 37.00 | 39.43 | 41.69 | 53.75 / 62.21 / 53.78 | 29.70 |
| retention run | 1251.9 | 1236.5 | 904.8 | 955.0 | 981.4 | 962.9 | 1296.8 / 1415.1 / 1228.2 | 218.5 |
| tier lines x5 | 1445.0 | 781.6 | 678.5 | 698.9 | 734.1 | 761.3 | 1367.9 / 1630.0 / 1742.7 | 252.7 |
| first `memory_save` | 33.06 | 40.21 | 29.97 | 30.87 | 33.27 | 33.46 | 34.30 / 36.03 / 33.45 | 28.08 |
| #204 bar recall p50 | 8.23 [8.1..9.4] | 8.96 | 7.70 | 8.52 | 9.17 | 9.33 | 8.05 / 8.94 / 8.68 [8.3..9.0] | 3.06 |

Against the hand-written module on the same interpreter, the compiled build is faster or inside its
spread on every path except: **full refresh** on all four (+36 to +47%), **cold query** on 3.11
(+20%) and 3.14 (+4%, outside a 32.8..34.6 spread), and the **#204 bar** on 3.14 (+8%). The pure
build is J90-P6's code: every path within J90-P6's spread on that interpreter but held query 3.12
(9.24 against 8.85, max 9.2) and compaction 3.11 (62.5 against 61.5), both within 4%. Runtime +
coldindex + hotindex alone (3.12): hot build 437.5, held 5.70, full refresh 23.70, cold query 30.68,
bar 8.56 — no better than all modules on any path that still loses.

**Full refresh is not a compiler gap** (cProfile of one refresh of 14 sources, 3.12; compiled code
appears as its caller's tottime): the compiled build spends 3 ms in 26 `os.listdir` where the
hand-written one makes 14 `os.scandir` calls (the generated `refresh` lists a native directory and,
in `remove_stale_temps`, the index directory once per write; the hand-written one did neither
twice), 750 `os.stat` against 736, and the interpreted adapters 722 `stat_sync` / `Stats` objects
and 694 `path_basename`. The JSON encode and decode are the same 6 ms on both. Closing it means
changing what the TypeScript asks the file system (both runtimes) or compiling the adapters.

**Not taken, measured.** Compiling the adapter module: after a concrete `BantamError`, a native
`_JsReadMap` and `cmp_codepoint`'s function attribute replaced by a list, it compiled and
segfaulted on the first hot-index build (exit 139). Native generated classes: `_js_object_get` reads
an instance's `__dict__` and `Object.freeze` overrides `__setattr__`, neither of which a native
class has. Type annotations from TypeScript types (lever 1) were not built in this unit.

**Size.** Pure wheel 968,167 bytes (J90-P6's rebuilt here 966,014; cap x1.005 = 970,844). `.so`
total, all modules, `-g0` + `strip -x`, raw / zip -9: cp311 8,414,344 / 2,209,453; cp312 8,425,944 /
2,165,111; cp313 8,307,352 / 2,154,858; cp314 8,274,152 / 2,133,459; cp312 at `-g1` unstripped
13,421,544 / 2,910,790. Runtime + coldindex + hotindex, cp312, `-g0` + strip: 2,037,736 / 593,638.
`mypy_extensions` is not needed at run time (the runtime falls back to an identity decorator).
Compile time, all modules: about 35 s per interpreter on this machine.

**The compiled gate is one command (J90-RF2).** `tools/release/compiled-gate.sh --python <py>`
makes a scratch worktree of HEAD (or `--rev`) with its own venv and Node build, builds the
compiled wheel there (`BANTAMKIT_MYPYC=1`, or takes `--wheel`), unpacks its extensions beside the
worktree's `.py` files (mypyc's group library `<hash>__mypyc.<suffix>` beside `bantamkit/`, where
the wheel puts it), and refuses to go on unless every module of the compile set imports from an
extension and `build_identity` says `mypyc (23 compiled, 1 interpreted)`. It then runs pytest and
`--all` in the worktree with a load logger in its venv (a `.pth` file) that records, at the exit of every
Python process, where each `bantamkit._generated` module was loaded from, and fails if any
process loaded one from a `.py` in the tree under test or none loaded a compiled one. HOME is a
scratch directory throughout; the worktree is removed at the end (`--keep` keeps it). Its checks
are `tools/release/compiled_gate.py`, pinned by `runtime-py/tests/test_compiled_gate.py`.

Why: the compiled runs J90-PF and J90-PF2 reported green were `PYTHONPATH=<compiled tree> node
run.mjs --all`, and every reference script puts `<checkout>/runtime-py/src` first on `sys.path`,
so they loaded the `.py` files. Run for real (J90-RR, 3.12, the `.so` files in-tree) the compiled
build was red: six errors in `test_build_identity`, 12 `cli` failures in `--all` and a dead
`version` server per fixture, because those copy `bantamkit/` into a scratch tree and left the group library behind (each copy
now takes it, `tools/conformance/lib/pypackage.mjs`, so a copy is the same build as the checkout);
four `test_conformance_harness_resilience` failures, a different cause (the rig named
`<repo>/.venv/bin/python`, which that tree lacked; it now uses the running interpreter); and
`version` then left `run.mjs` with an unsettled promise, so Node exited 13 with no FAIL line and
the suites after it never ran (a suite that does not settle is now one red suite, and a run that
dies inside a suite prints a FAIL line naming it). A real install is not affected: the group
library is in the wheel's `RECORD` (`docs/install.md`, *Compiled wheels*).

### The compiled build's last three losses closed (#316 G4, J90-P7B)

J90-P7's compiled build lost full refresh (all four interpreters), cold query (3.11, 3.14) and the
#204 bar (3.14). Each was profiled first (cProfile for the interpreted parts, macOS `sample` for
the compiled ones); what each turned out to be, and what closed it:

- **Full refresh was the head's second line dumped again.** A full refresh that finds nothing moved
  still rewrites the head (`full_at`), and `write` dumped `files`, `docs`, `df` and `lens` again:
  4.6 ms of JSON plus 1.5 ms of UTF-16 slicing of a non-ASCII text, of a 17.9 ms refresh of 14
  sources. `hotindex.ts` now keeps the second line it wrote (`IndexData.tailText`, cleared by any
  patch that changes a doc) and, per process, the line it last wrote at each head path
  (`WROTE_TAIL`): a head read back whose second line is exactly that text holds what `tailLine`
  gives for what it parses to, so the write reuses it. A second line in any other spelling is dumped
  again (case `J90-P7B a write reuses the second line only when this process wrote that text`). Also:
  `patch` builds its maps in one loop and `order` only past its early return, and a native file is
  listed by name (`mdNames`), so `statListing` takes no `path.basename` of a path it just joined.
  The stale-temp sweep (`removeStaleTemps`) still lists the index directory on every write (2.3 ms
  of the refresh): sweeping once per process breaks `J90-3F a hot index persist removes its own
  stale temps` (a second index in the same process must still sweep), and a directory-mtime test is
  blind to a temp made between a write and its stat and to a 1 s mtime clock, so it was not taken.
- **Cold query was each query parsing the same shards again.** `ColdIndex.shard` now keeps, per
  shard, the text it last parsed and the table it gave, and reuses the table when the text read
  (still through `coldFs`, so the read count a test spies on is unchanged) is the same; no stat is
  trusted (case `J90-P7B a cold shard rewritten to the same length is read as written`). Node and
  Python both: cold query x20 3.12 36.2 (hand) / 12.4 (compiled) / 20.6 (pure); Node 21.9 -> 10.2.
- **The bar was CPython's `round(x, 9)`**, 10,000 per recall at 5,000 facts (every doc scores
  above 0 for that query), each through a decimal string (`float.__round__` -> `PyOS_snprintf`):
  15% of a compiled recall, called from compiled code into the interpreted adapters. It is now the
  runtime's `_js_py_round_float9` with `pyRoundFloat9`'s own J68-5 fast path (`tools/ts2py/
  RULES.md`, *J90-P7B rules*). The rest of the 3.14 gap is the generic `Any` arithmetic mypyc writes
  for the counted loops of `bm25Segments` (`binary_op1`, `PyNumber_Index`, `float_add` in the
  samples): with `retrieval` left interpreted on 3.14 the bar was 7.98 against 8.27 compiled
  (n = 7), and typed locals in the proven loop copies would need annotated functions (mypy skips
  the body of an unannotated one, so an annotation inside it compiles to nothing) — not built.
  Also exact and pinned: POSIX `path.basename` / `dirname` from the last `/`, `pyReadText` through
  `io.open` for a path `PurePath` leaves as it is, `statSync`'s option check without a set.

| path (n = 9 interleaved, median ms; hand [min..max]) | 3.11 hand / pure / mypyc | 3.12 | 3.13 | 3.14 | 3.12 J90-P7 pure / mypyc | Node J90-P7 / now |
|---|---|---|---|---|---|---|
| import | 129.28 [118.2..139.8] / 93.09 / 102.51 | 148.42 [141.3..183.8] / 103.73 / 119.28 | 150.86 [141.7..155.6] / 106.53 / 122.12 | 138.63 [136.4..158.1] / 106.32 / 121.97 | 105.10 / 116.38 | 30.19 / 20.59 |
| hot index build | 423.51 [417.0..479.4] / 491.38 / 411.39 | 413.33 [405.1..465.1] / 483.10 / 412.60 | 440.43 [434.1..452.0] / 518.37 / 432.74 | 420.02 [410.4..436.8] / 489.79 / 435.07 | 484.76 / 419.95 | 278.82 / 269.17 |
| open + query | 7.16 [5.6..7.9] / 6.90 / 6.22 | 6.85 [5.7..8.4] / 6.43 / 7.24 | 6.36 [5.6..7.4] / 6.38 / 5.97 | 6.50 [5.3..8.4] / 6.50 / 5.81 | 7.10 / 6.62 | 5.42 / 6.41 |
| held query x20 | 5.50 [5.4..6.0] / 9.39 / 4.99 | 5.54 [5.5..5.8] / 8.88 / 5.42 | 5.64 [5.6..6.0] / 9.67 / 5.92 | 5.75 [5.6..6.4] / 9.13 / 6.20 | 8.75 / 5.45 | 2.79 / 3.04 |
| full refresh | 16.12 [15.3..17.3] / 19.17 / 15.82 | 16.48 [16.1..18.3] / 19.00 / 16.35 | 17.71 [17.0..31.3] / 20.91 / 15.81 | 16.84 [16.3..20.1] / 19.27 / 16.45 | 26.17 / 23.21 | 35.70 / 17.34 |
| cold build | 91.01 [89.4..96.6] / 93.97 / 44.27 | 85.02 [84.0..87.8] / 88.10 / 47.47 | 104.86 [103.4..106.8] / 110.13 / 51.36 | 84.87 [84.0..87.9] / 86.79 / 55.98 | 87.23 / 47.61 | 32.46 / 34.47 |
| cold query x20 | 34.15 [33.7..35.7] / 21.01 / 11.31 | 36.18 [35.9..37.1] / 20.59 / 12.41 | 33.15 [32.6..35.8] / 24.40 / 13.11 | 33.44 [32.8..34.3] / 21.18 / 13.89 | 54.15 / 30.44 | 21.85 / 10.23 |
| compaction with `keep` | 53.65 [52.4..60.5] / 59.09 / 33.62 | 51.77 [51.0..54.3] / 56.33 / 35.28 | 61.67 [60.5..64.1] / 69.38 / 36.47 | 51.65 [50.8..56.6] / 55.93 / 40.44 | 57.44 / 36.26 | 29.63 / 29.09 |
| retention run | 1287.41 [1280.9..1344.0] / 1271.43 / 911.64 | 1241.82 [1235.4..1278.6] / 1217.55 / 956.30 | 1408.93 [1395.2..1426.8] / 1415.66 / 969.73 | 1222.03 [1216.8..1237.4] / 1189.16 / 955.30 | 1218.13 / 939.08 | 231.33 / 226.88 |
| tier lines x5 | 1356.76 [1343.8..1411.6] / 719.03 / 662.89 | 1428.86 [1421.0..1460.0] / 769.45 / 691.57 | 1615.90 [1604.7..1634.7] / 792.95 / 721.60 | 1735.00 [1719.1..1794.8] / 801.77 / 747.84 | 769.69 / 680.42 | 256.63 / 251.82 |
| first `memory_save` | 33.54 [32.8..37.6] / 40.73 / 28.11 | 32.45 [31.8..33.7] / 37.99 / 30.05 | 35.35 [35.0..36.5] / 46.21 / 30.99 | 32.86 [32.3..70.9] / 40.12 / 31.30 | 40.08 / 30.45 | 28.63 / 28.59 |
| #204 bar recall p50 | 8.22 [7.6..8.6] / 7.81 / 6.84 | 8.20 [8.1..8.8] / 8.09 / 7.55 | 8.68 [8.5..8.8] / 8.94 / 8.34 | 8.49 [8.2..9.7] / 8.12 / 8.62 | 8.73 / 8.63 | 2.96 / 2.83 |

Compiled, every path is at or below the hand-written module's median, or inside its spread (hot
build 3.14 435.1 in 410.4..436.8, held query 3.13 / 3.14 5.92 / 6.20, the bar 3.14 8.62 in
8.2..9.7). Pure (3.12) against J90-P7's pure: every median lower or inside its spread (held query
8.88 in 8.4..9.6, cold build 88.10 in 86.1..91.5). Node against J90-P7's Node: full refresh 35.7 ->
17.3, cold query 21.9 -> 10.2; open query 6.41 and held query 3.04 inside J90-P7's spreads (5.0..9.6,
2.6..3.1).

**Real data, byte for byte.** The user's stores copied to scratch (the repo's `.bantamkit/memory`
and `.shiftwork`, `~/.bantamkit`, the 120 `~/.claude/projects/*/memory` directories: 31,779 files,
245 MB), each side on its own fresh copy: retention twice and the tier lines around it, archive
search, the jobs and facts cold indexes (add, query, compact, compact with `keep`), the facts hot
indexes (query, postings), a hot index per native directory (fast and full refresh), the memory
component's recall over seven queries on both stores, its dream dry run and compaction, then the
dream applied across the two stores and compaction forced under a 9,000-byte budget (63 and 45
facts archived). Python pure, Python mypyc 3.12, Python mypyc 3.14 and J90-P6 answer every one
identically, and leave the same 28,452 files byte for byte (the usage ledgers' `ts` masked, a
ledger named by its store's path matched by content). Node answers the same but in the two places
already pinned: the ruled gzip row of the status line (207 bytes, *J90-P4*) and the YAML refusal
sentence of five native facts (`YAML_REASONS_PY` / `YAML_REASONS_NODE`, `storage-index`); the same
files are skipped on both sides.

### The platform wheels and the compiler package (#316 G4, J90-P8; #337, J90-PKG)

**The compiled build ships (J90-P8).** `runtime-py/hatch_build.py` compiles J90-P7's set, the
runtime and the 22 generated modules (`_ts2py_adapters.py` stays interpreted), with mypyc 2.4.1
when `BANTAMKIT_MYPYC=1` is set, and tags the wheel for its interpreter and platform; unset, the
build is the pure `py3-none-any` wheel, byte for byte what it was before the hook, and any other
value is refused. `tools/release/build-wheels.sh` builds the set from the sdist: macOS arm64 on
this Mac with python-build-standalone interpreters (`uv`), manylinux x86_64 and aarch64 in
cibuildwheel's `manylinux_2_28` images under local Docker; `tools/release/smoke-wheel.sh`
installs one wheel and drives it; `tools/release/publish.sh` builds, checks and uploads the
whole set. `build_identity`'s `compiled` field tells the two Python builds apart (the
divergence row above). Steps and the platform matrix: `docs/install.md`, *Compiled wheels and
the pure fallback*. No answer moved: the suites run against both builds.

**The compiler is its own package (J90-PKG).** `tools/ts2py` holds no bantamkit name. The
runtime's source is `tools/ts2py/python/ts2py/runtime.py`; bantamkit's half is
`tools/ts2py-bantamkit/`: `ts2py.toml` (the host file, every adapter row with its reason,
passed with `--config`), `adapters.py` (the source of `_ts2py_adapters.py`), `census.mjs` and the
cargo tests that compile bantamkit's modules. The rules stay in `tools/ts2py/RULES.md`. J90-D
repointed the comments that still named `tools/ts2py/src/adapters.rs` and changed the
`shipped_note` line to name the moved sources; regenerating rewrote that one comment line in
`_ts2py_runtime.py` and the header of `_ts2py_adapters.py`, and no other byte.

**What a Python user sees change** across #314, #315 and #316 G1-G4, entry by entry with
before, after and Node's answer: [the 1.0.0 Python migration note](python-1.0.0-migration.md).

### CPython 3.13 and 3.14 answer 3.12's answers (#316 G4, J90-P8F)

J90-P8 installed every wheel it built and ran the suites under each interpreter, which put 3.13
and 3.14 through the conformance suites for the first time (CI and every earlier gate ran 3.11 and
3.12). They failed, on the PURE wheel as on the compiled one, so the cause was the interpreter and
not mypyc: the Node port reproduces CPython 3.12, and 3.13 and 3.14 changed some of the answers
3.12 gave. `requires-python = ">=3.11"` promises both, and the wheels ship for both, so each
change is pinned: Python now gives 3.12's answer, which is Node's, on every interpreter. Nothing
changed on 3.12, and no ruling was added: every difference below could be pinned. On 3.11 one
answer moved, toward Node: CPython 3.11.15's `invalid choice` sentence, which its gate had never
run (J90-P8 ran eleven suites against 3.11, not `cli` or `memorycli`).

**Where the pins live.** `runtime-py/src/bantamkit/stdlib312.py` is the one hand-written module
that asks the standard library a question whose answer moved, each function either 3.12's own
code or the live answer corrected by a rule exact for the one change it undoes (its docstring
names each). The adapters (`tools/ts2py-bantamkit/adapters.py`) and the hand-written modules ask
it instead of the library: `Path.exists()`/`is_file()`/`is_dir()`/`resolve()` and `json.loads`
were rewritten to `stdlib312.path_exists(...)` and so on at every call site under
`runtime-py/src/bantamkit` (126 sites, by an AST rewrite; `os.DirEntry`, `zipfile.Path` and
other non-`pathlib` objects still answer with their own method). The CLIs parse with
`bantamkit/_argparse312.py`, CPython 3.12.13's `argparse.py` vendored verbatim
(`stdlib312.argparse`), on every interpreter: on 3.12.13 it is the interpreter's own file byte
for byte, and 3.11.15 needs it too. A label-driven decode
resolves through `bantamkit/_codecs312.py`, 3.12.13's alias table and module list, the registry
`runtime-ts/src/charsets.ts` already holds. `runtime-py/tests/test_stdlib312.py` pins the 3.12
literals on every interpreter and, below 3.13, that each pin IS the live library; removing a pin
turns it red on 3.13 or 3.14 (measured by swapping each pin back to the library: json, resolve
and the suffix red on both, the datetime sentences and the predicates red on 3.14).

| what moved | CPython change | failing before (suite / node) | who differed | pinned in |
|---|---|---|---|---|
| a trailing comma: `Illegal trailing comma before end of object` at the comma, not 3.12's `Expecting property name enclosed in double quotes` (or `Expecting value`) at the next non-blank | 3.13, gh-113149 (`Lib/json/decoder.py`, `Modules/_json.c`) | shiftwork 3 (`unparseable-checkpoint`, `unparseable-non-ascii-offset`); validate 29 (`raw_decode/...`); cargo `j89_5a` under `TS2PY_PYTHON` 3.13 | hand-written `shiftwork._read_valid` and `contract.extract_json`; the `parse_json` adapter; the validate reference | `stdlib312.json_loads` / `json_raw_decode` / `pin_json_error` |
| a `\uXXXX` escape whose four digits end the document: `Unterminated string starting at` the opening quote, not 3.12's `Invalid \uXXXX escape` at the `u` (3.12's C `scanstring` tested `next + 4 >= len`) | 3.13.x and 3.14.x (`Modules/_json.c`; 3.13.18 and 3.14.10 both answer it) | validate 1 on 3.14 (`raw_decode/... "\u00e9`) | `contract.extract_json`; the validate reference | `stdlib312.pin_json_error` (`_ends_in_u_escape`) |
| `\B` matches an EMPTY string; 3.12's `SRE_AT_NON_BOUNDARY` answered no whenever the whole string was empty | 3.14, gh-124130 | validate 3 (`pattern/dialect/178 "\B"`, `2427 "\A\B"`, `2725 "$\B"`) | the JSON Schema `pattern` search (`contract._BoundedRe`, its child); the validate reference | `stdlib312.re_search` / `without_nonboundary` (each `\B` outside a class made a never-match, for an empty string only, after the pattern is compiled as given) |
| `re.error` is `re.PatternError` (`error` kept as an alias), so the pattern child named it `PatternError`, which `builtins` lacks | 3.13 | none measured (the parent re-raised it as `RuntimeError`) | `contract._PatternChild` | the child reports `error` for any `re.error` |
| `list.sort`'s `count_run` takes non-strictly descending runs, so the first incomparable pair, and the TypeError's two type names, moved | 3.13, gh-116554 ("Relax list.sort()'s notion of 'descending' runs") | store 1 (`the recall tie-break over 50000 generated lists`) | the REFERENCE: both runtimes sort recall with the compiled `sort_scored` | the case is armed below 3.13 only, withheld above with a note (the J63-1b shape), plus a literal case on the arming |
| `Path.resolve()` no longer raises `RuntimeError("Symlink loop from %r")` for a loop in non-strict mode | 3.13 (pathlib docs, "Changed in version 3.13: symlink loops are treated like other errors") | store 1 (`str(OSError) and the symlink-loop RuntimeError`), recall-strings 1 (`Path.resolve(): ... and the loop`) | the `py_resolve` adapter, `shiftwork._real_target`, the references | `stdlib312.path_resolve` (3.12's `check_eloop` over `os.path.realpath`) |
| `PureWindowsPath.is_absolute()` became `ntpath.isabs()`, which stopped calling `/x` absolute | 3.13, gh-44626 | store 1 (`ntpath.splitroot and PureWindowsPath parsing`) | the `py_is_absolute` adapter on Windows; the reference | `stdlib312.win_is_absolute`, `nt_isabs` |
| the `IOBase` finalizer reports a failed `close()` through `sys.unraisablehook` | 3.13, gh-62948 | wire 2 (`j66-3: #181 stdout closed mid-answer`): `Exception ignored in: <_io.BufferedWriter name=7>` / `BrokenPipeError` on stderr | `mcpstdio.serve_stdio` | fd 1 is claimed by `serve_stdio` itself (the SDK's own `_claim_fd`, no new private name); on a broken pipe the buffer's descriptor is pointed at the null device and flushed (`_quiet_dead_pipe`) |
| `argparse` wraps a usage line inside a mutually exclusive group, and spells `invalid choice: ... (choose from 'a', 'b')` with reprs | 3.13 (`Lib/argparse.py`: `_check_value` joins `repr(str(choice))` where 3.12.13 joins `str`, and `_format_usage` wraps group parts; 413 diff lines from 3.12.13 to 3.13.18, 995 to 3.14.10, which also colours help) | cli 4, memorycli 8 (`help-columns-*`, `usage-block*`, `bad-choice`, `install-bad-host`); and on CPython 3.11.15, whose `_check_value` also joins reprs, cli 1 + memorycli 2 (`install-bad-host`, `bad-choice`, `list-bad-filter`) | `mcpserver`, `memory.__main__`, `criticreplay`, `evalrun` | `stdlib312.argparse`: 3.12.13's module, vendored, on every interpreter |
| `encodings.aliases` grew (`cp00858`, `windows_31j`, `ibm01140`; 3.14 `iso_8859_8_i`, `cseuckr`, `ms874`, ...) and `palmos` 0x9B became U+203A | 3.13 and 3.14 (`Lib/encodings/aliases.py`; `palmos.py`, gh-135995 "Missing char in palmos encoding") | charsets 3 (`charsets.ts is what the generator writes`, `CODEC_ALIASES`, `single-byte palmos`) | `docread._decoded_body`; the reference | `stdlib312.codec_decode` over `_codecs312`; the charsets reference answers the pinned registry from 3.13 and the generator byte-compare is withheld there with a note |
| `punycode` decodes bytes past the last `-` without ASCII-checking them, so `errors="replace"` swallows what 3.12 raised on | 3.13 (`Lib/encodings/punycode.py`) | docread 3 (`charset-raises-punycode.eml`), pytest 1 | `docread._decoded_body` | 3.12's ASCII check, asked first |
| `html.parser` unescapes attribute values through `_unescape_attrvalue` -> `_replace_attr_charref` -> `unescape`, so `unescape` left `parse_starttag`'s own names | 3.13.x/3.14.x security releases (HTML5 attribute and CDATA handling) | docread 2 (`xmp-charref-4301.html`), pytest 2 (`HTML_UNESCAPE_BOUNDED` False, the whole-markup fallback in use) | `docread._with_bounded_unescape` | every module function that reaches `unescape` is rebuilt over the capped namespace (`_bounded_namespace`); on 3.12 that set is empty |
| `date`/`datetime`/`timezone` range sentences: `month must be in 1..12, not 13`, `day 30 must be in range 1..28 for month 2 in year 2026`, `year must be in 1..9999, not 0`, no full stop after the offset repr | 3.14, gh-109798 | store 6 (`frontmatter scalar: date ... / datetime ...`), recall-strings 1 (`load_grants over the config family`) | `factcodec`'s PyYAML read (and `divergence.parse_fact`, `skillfile`), the grants-config adapter | `stdlib312.pin_datetime_error` (`factcodec.safe_load`) |
| `Path.exists()`/`is_file()`/`is_dir()` answer `False` for every `OSError`; 3.12 re-raised all but ENOENT/ENOTDIR/EBADF/ELOOP, so an EACCES parent RAISED (and `save`'s check before a write must) | 3.14 (`Lib/pathlib`: the predicates call `os.path.exists`/`isdir`/`isfile`) | store 1 (`facts is readable but not traversable`), install 2 (`an origin that could not be STATTED`: the reference), pytest 2 (`restore` names the unreadable directory) | the `py_exists`/`py_is_dir`/`py_is_file` adapters and every hand-written call | `stdlib312.path_exists` / `path_is_dir` / `path_is_file` (3.12's `_ignore_error`) |
| `PurePath.suffix` of `a.` is `.` | 3.14, GH-82805 | store 1 (`PurePath / and with_suffix`) | the `py_suffix` adapter; the reference's `with_suffix` | `stdlib312.path_suffix`; the store reference carries 3.12's `with_suffix` from 3.13 (no product path asks it) |
| `io.DEFAULT_BUFFER_SIZE` 8 KiB -> 128 KiB | 3.14 | pytest 1 (`the two render failure rigs straddle the measured stdout buffer`) | the TEST's rig: 40 cells no longer passed the crossover | the large rig scales with the buffer, `max(40, io.DEFAULT_BUFFER_SIZE // 256)` (40 below 3.14, 512 on it) |

**The references.** Where a conformance reference asks the library itself (`store_ref.py`,
`layers_ref.py`, `charsets_ref.py`, `validate_ref.py`, `install_ref.py`), it asks the live library below 3.13, exactly as before, and
the pin from 3.13, so the expected answer is 3.12's on every interpreter; `test_stdlib312.py` is
what makes those one reference. Two cases cannot be asked of a 3.13 interpreter at all (3.12's C
listsort; the generator's live registry), and those are withheld there with a note naming them,
the shape J63-1b uses for the winpaths case below 3.12, never a `ruling:`.

**Installed-layout pytest nodes.** Eleven nodes failed from an installed wheel on every
interpreter, 3.11 and 3.12 included, because each asks about the checkout's layout (the asset pack
at `<repo>/assets`, force-included only when a wheel is built). `conftest.checkout_only` skips them
when the imported package has a `bantamkit-*.dist-info` beside it, with `CHECKOUT-ONLY` in the
reason, and runs them unchanged in a checkout; `test_packaging.py::
test_checkout_only_skips_do_not_fire_in_a_checkout` requires the condition false in one.

**Gates (J90-P8F, macOS arm64; 3.11.15 python-build-standalone, 3.12.13 the repo venv, 3.13.18 and
3.14.10 Homebrew).** `node tools/conformance/run.mjs --all`: 3.12 23,659 cases, 0 failures; 3.13
23,657, 0; 3.14 23,657, 0 (240 ruled-different there against 242: CPython 3.14's Unicode 16.0
makes U+1C89 a letter, as Node's 17.0 does, so `skillaudit` compares those two cases instead of
ruling them); 3.11 23,658, 0. The compiled build (the cp313/cp314 wheels the J90-P8 hook builds
from the sdist, installed, `runtime-py/src/bantamkit` a copy of the install): 3.13 23,650, 0 and
3.14 23,650, 0, `build_identity` `mypyc (23 compiled, 1 interpreted)` (seven store cases fewer:
the scratch tree has no `.bantamkit/memory` corpus). Full pytest: 3.11 5,395 passed, 3.12 5,396,
3.13 5,392, 3.14 5,391, none failed; from an installed compiled wheel with `src/bantamkit` linked
to it, 3.13 5,381 and 3.14 5,380 passed with the 11 `CHECKOUT-ONLY` skips. ts2py `cargo test`
54/54 and the host crate 72/72, both again with `TS2PY_PYTHON` a 3.13 venv, the host crate 72/72
under a bare 3.14 too (a bare 3.13 has no PyYAML, which `j89_5b` needs); clippy and fmt clean.
`npm test` 2,467 passed, 0 failed, 47 skipped. ruff clean.


### The pure build against the hand-written Python, after J90-R (#316 G4, J90-RF)

**The owner's bar is "never slower than the hand-written Python", and the pure wheel (Windows,
musl, any platform without a compiled wheel) does not meet it yet.** J90-R measured the pure build
slower than 9c6bc181 on four paths; J90-RF profiled each and changed the one place a TypeScript
spelling was the cost, `HotIndex.derive` and `encodeSegments`: the per-doc `forEach` callback is a
counted loop, the shard memo is read inline (no closure per term, so `Map.get` takes ts2py's guarded
dict read), each term's posting row is built as it is counted and pushed as it is (no count triple
copied into a new row, 68,000 fewer `_js_get` calls on the build below), and `encodeSegments` holds
the open run in locals instead of reading the last five numbers back. Same index bytes
(`--suite storage-index` compares every file byte for byte), Node within its spread (the 14-source
build 213-222 ms before and 220-222 after, best of 7, three alternating runs).

**Measured (`bench/drive.py`, n = 7 interleaved fresh processes per side, medians [min..max] ms,
macOS arm64; hand = 9c6bc181, pure = this tree, comp = this tree's mypyc wheel built locally).**

| Path | 3.12 hand | 3.12 pure | 3.12 comp | 3.14 hand | 3.14 pure | 3.14 comp |
|---|---|---|---|---|---|---|
| hot cold build, 14 sources | 401.9 [397..431] | **457.8** [455..459] | 401.6 [395..412] | 389.8 [387..401] | **446.3** [443..457] | 394.7 [393..399] |
| hot open + query | 5.68 | **6.18** | 5.66 | 6.61 | 5.91 | 5.39 |
| hot held query x20 | 5.61 [5.4..6.7] | **8.39** [8.2..9.0] | 5.50 | 6.02 | **8.05** | 5.49 |
| hot full refresh | 16.64 [16.0..29.6] | **18.18** [17.8..18.9] | 16.22 | 15.53 [15.2..22.8] | **17.58** | 15.94 [15.1..16.4] |
| cold build | 84.49 | **85.83** | 46.48 | 79.74 | **81.34** | 52.05 |
| cold compact with keep | 50.81 | **55.77** | 33.96 | 48.37 | **53.29** | 36.43 |
| first `memory_save` | 31.99 | **35.73** | 29.02 | 31.14 | **35.14** | 29.54 |
| cold query x20, retention run, tier lines x5, #204 bar | 35.9 / 1234 / 1405 / 8.09 | 20.4 / 1211 / 742 / 7.82 | 12.4 / 933 / 696 / 7.53 | 30.5 / 1177 / 1497 / 7.72 | 20.2 / 1159 / 740 / 7.42 | 12.7 / 933 / 695 / 7.67 |

J90-R's pure figures on the same bench were 475.5 (build), 8.42 (held), 18.24 (full refresh) and 37.9
(first save); the build moved -3.7%, the others within their spread. The compiled build is at or
under the hand-written one on every path but the import (within its spread) and the 3.14 full
refresh (15.94 against 15.53, inside both ranges).

**Why the rest is not closed here, from the profiles.** Each gap is the general helpers' cost per
operation, not an algorithm: the hand-written code and the generated code do the same work.
- *Build* (phase timers, best of 6, 3.12: hand 363 ms = parse 217 + derive 72 + write 62; pure 424 =
  parse 244 + derive 95 + write 72): `parse` pays for each fact through the adapters
  (`parse_native`, `extract_refs`, `py_read_text`, `py_text`) about 40 us more a file over 680
  files; `derive` still writes each count through `_js_put` and reads it through `_js_get` (31,000
  calls), sets through `_js_m_set` (69,000) and pushes through `_js_m_push`.
- *Held query* (per index and call: hand refresh 5.4 us + query 13.0; pure 9.2 + 18.6): the two stats
  go through `stat_sync` and a `BigIntStats` object (0.4 us each) and the head stamp is built with
  `_js_str` of three BigInts (1.2 us); `lookup` (10.2 us against 3.5) is `new Set` plus `_js_m_sort`
  (1.25 us against 0.2 for `sorted(set())`), and `shard` reads the fingerprint through three
  `_js_get` and a key string through `_js_str` (0.63 us a shard). Regrouping the lookup by an array
  per shard (tried) moved it 0.5 us and was reverted.
- *Full refresh, first save, compaction*: the same helpers on the same objects (refresh's stats, the
  head's `dumpJsValue`, the cold index's row loop, whose floor J90-P5 measured).

**What closing it would take**: an emitter rule in the shape of J90-P6's guarded expansions for
`_js_put` / `_js_get` / `_js_list_at` of a list by an int, `Map.set`, `Map.has` and `Array.push` in
loop bodies (J90-P6 measured `_js_get` and `_js_list_at` alone as moving no path past its spread,
so it would need the writes too), a stat adapter that answers the three fields a head stamp reads
without building an object, and `new Set(xs).sort(cmpCodepoint)` of strings lowered to
`sorted(set(xs))`. Each is a compiler or adapter change with its own probe and fuzz, beyond this unit;
the compiled wheel meets the bar today on every platform that has one.

### The pure build against the hand-written Python, after J90-PF (#316 G4)

**What moved** (`tools/ts2py/RULES.md`, *J90-PF rules*; no answer changed, every conformance suite
compares the two runtimes as before). By where the time was, from profiles of each path against
9c6bc181 (cProfile for the callers, then unprofiled best-of-N timings of each piece, since the
profiler charged the collector's passes to whatever allocated next):

- *The collector* (an adapter, Python-only): the generated index makes every posting row and
  table a list or a Map, which CPython always tracks, where 9c6bc181 made tuples and dicts of
  atomic values that it untracks; the collector's passes over them were 18-21 ms of the 14-source
  build (measured with `gc.disable()` around the whole run: pure 435 -> 417 ms, hand 375 -> 376).
  The hot index shim's `refresh` and the cold index shim's `add` / `compact` now run with it off
  (inline, re-enabled only if it was on), as `no_gc` already did for the parses. (J90-PF2 took
  the hot index's back out: it moved the collections instead of saving them; *after J90-PF2*.)
- *The build* (TS respellings): `write` reuses the text `derive` printed each table's fingerprint
  from (`dumpIndex` of `{fingerprint, terms}` is the fingerprint's member, then the terms' own text);
  a native file is read twice, not three times (`parseNative` hands back the `front` it split); a
  term's `df` is its posting list's length after the push; `postings` is built in a loop; the count
  update goes through a local so the store is written inline.
- *The held query* (adapters and rules): the head's stamp and the directory's are each one `os.stat`
  answered as the string compared (`statStamp`, `statMtimeNs`), not a `BigIntStats` object read
  through three `_js_get`; `[...new Set(terms)].sort(cmpCodepoint)` is `sorted(set(terms))`;
  `[...byShard.keys()].sort((a, b) => a - b)` is `list.sort`; `shard`'s held-table test runs inline
  in `lookup`; the shim's `_dict` copies a plain Map's entries at once.
- *The open path and the full refresh*: `shardPath` joins its stem once; a listing's stat is one
  `statFile` adapter call; `endsWith('.md')` is `str.endswith`; a `-0` inside a string (`audit-0`)
  no longer sends a 180 KB head through the per-integer JSON hook; a dense shard of 513-2048
  characters takes the exact-ints scan.
- *Everywhere in loops*: `has`, `get` and `set` with an int key, `===` of two ints, `push`, stores
  and reads by an index, written inline under the helper's own guard (J90-P6's shape).
- *First save*: `JSON.stringify` of a list of plain values (the derived key) is `json.dumps`.

**Measured** (`bench/drive.py` as J90-RF ran it, scratch HOME; n = 7 interleaved fresh processes
per side, median [min..max] ms, macOS arm64, a loaded machine; hand = 9c6bc181, pure = this tree,
comp = this tree's mypyc wheel built locally; verdict = pure against hand's range).

| Path | 3.12 hand | 3.12 pure | 3.12 comp | 3.14 hand | 3.14 pure | 3.14 comp | verdict 3.12 / 3.14 |
|---|---|---|---|---|---|---|---|
| import | 94.7 [89.1..106.3] | 97.1 [91.2..98.1] | 98.2 | 89.7 [82.2..153.0] | 90.1 [84.5..97.3] | 91.0 | in / in |
| hot cold build | 407.7 [395.7..462.4] | 415.7 [399.9..420.0] | 365.6 | 392.7 [377.5..406.6] | **410.8** [397.0..418.2] | 368.5 | in / over (+4.6%) |
| hot open + query | 5.46 [4.7..6.0] | 5.88 [5.3..7.0] | **8.06** | 4.71 [4.3..6.0] | **6.15** [5.2..7.1] | 5.18 | in / over |
| hot held query x20 | 5.18 [5.0..5.6] | 5.19 [5.1..5.7] | 3.68 | 5.10 [4.9..5.7] | 5.34 [5.0..5.8] | 3.75 | in / in |
| hot full refresh | 15.39 [14.7..15.8] | **15.86** [14.9..16.4] | 14.64 | 14.76 [14.0..15.5] | **15.88** [14.6..18.6] | 14.28 | over (+3%) / over (+8%) |
| cold build | 85.44 [83.9..87.1] | **87.20** [82.9..110.3] | 47.18 | 81.63 [79.3..82.7] | 81.76 [78.8..82.5] | 54.17 | over (+2%) / in |
| cold query x20 | 36.42 | 20.74 | 13.12 | 30.60 | 22.57 | 13.50 | under / under |
| cold compact with keep | 51.47 [50.6..53.0] | **53.75** [52.3..56.5] | 34.18 | 49.79 [48.1..50.6] | **51.42** [49.7..52.5] | 36.17 | over (+4%) / over (+3%) |
| retention run | 1244.3 | 1237.9 | 960.7 | 1198.9 | 1186.4 | 956.6 | under / under |
| tier lines x5 | 1440.3 | 776.6 | 707.4 | 1547.5 | 777.6 | 722.4 | under / under |
| first `memory_save` | 33.97 | 31.25 | 24.11 | 32.15 | 30.70 | 25.03 | under / under |
| #204 bar recall p50 | 8.33 | 7.72 | 7.70 | 7.81 | 7.64 | 7.81 | under / under |

Against J90-RF's table: the build 457.8 -> 415.7 on 3.12, the held query 8.39 -> 5.19, the full
refresh 18.18 -> 15.86, first save 35.73 -> 31.25. Node's 14-source build, best of 7, three
alternating runs: 224.2 / 230.2 / 235.7 ms before, 189.3 / 190.2 / 194.9 after (one dump and one
file read fewer). **The compiled build is faster than its J90-RF wheel on every path but the 3.12
open path** (n = 5 against that wheel: 7.83 against 6.19; 3.14 5.81 against 6.07). Warm, step by
step, it is the same (refresh 0.72 against 0.73 ms, segments 3.04 against 3.06): the bench's open
path is one cold pass right after the build, and with the collector off for each refresh the
build's young collection lands in it (the wheel without that adapter: 6.50, its build 9 ms
slower); the other 0.9 ms is not isolated.

**What is still over, and why (profiles above).** Each remaining gap is the general helpers'
per-operation cost where 9c6bc181 used a C-level construct, not an algorithm: *build* 3.14 and the
*full refresh*: the derive loop's Map and list operations (35 ms of loop against 16 hand, now
inline where a rule proves the operation; 9c6bc181 counted with `Counter` and `dict.setdefault`),
`encodeSegments` (7.3 ms against 0.9: a destructuring generator and four guarded `===` per row),
and `dumpIndex`'s lift guard (2.8 ms a pass over 448 tables, the exactness check `json.dumps` alone
does not make); *open*: the head's checks and the exact-ints scan (about 20 us a head) and, in the
bench, the build's deferred collection; *compaction*: the per-token count and per-row filter, now
inline, still a guard per operation. Closing them would need either type facts for values read
from JSON and Maps (so a loop body could drop its guards; ts2py proves facts for locals and
parameters only), or C-level counterparts of the hand-written module's `Counter` / `setdefault`
idioms as runtime helpers with their own exactness proofs, or the compiled wheel, which meets the
bar on these paths today.

**Measured and not taken.** An explicit young collection at the end of a refresh (so the build pays
for its own collector work instead of whatever runs next): 3.12's open path went from 5.9 to 8.5-9.1
ms. The collector off around shard reads (`query`, `segments`): no change past the spread (the
parsed tables stay alive, so the deferred collection is the same work). The exact-ints scan for
every text past 128 characters: tier lines 3% slower (event lines carry one or two ints among
strings); past 512 with a comma every eight or fewer, tier lines are unchanged. One regex for the
scan: 7x slower than the translate-and-find it would replace. `array('q', ...)` as the lift guard of
`dumpIndex`: it admits `__index__` objects, so it is not exact.

**Sources researched** (each one the mechanism a gap above comes from):
- Function call cost against inline code in hot loops: the Python wiki's
  [Performance Tips](https://wiki.python.org/moin/PythonSpeed/PerformanceTips) ("function call
  overhead is large compared to other instructions"), and
  [What's New in Python 3.11](https://docs.python.org/3/whatsnew/3.11.html) (inlined Python calls
  and cheaper frames: 1-3% and 3-7% on pyperformance; subscript and call specializations "up to"
  10-25% and 20% per operation) with [PEP 659](https://peps.python.org/pep-0659/): the specializing
  interpreter speeds the helper calls and the hand-written code alike, which is why no interpreter
  version closes a per-operation gap (J90-P6 measured 3.11-3.14).
- Emitted code that reproduces another language's semantics pays a call and a type test per
  operator in inner loops: Transcrypt's design note on `a + b` as `__add__(a, b)`
  ([InfoQ](https://www.infoq.com/articles/transcrypt-python-javascript-compiler)) and PScript's
  ("the overhead to realize the more Pythonic behavior can have a negative impact on performance in
  tight loops", [PScript introduction](https://pscript.readthedocs.io/en/stable/intro.html)). The
  guarded expansions are this repository's answer: the helper's own first branch inline, the call
  only for the values it is for.
- Compiled attribute and container access: [mypyc's performance
  tips](https://mypyc.readthedocs.io/en/latest/performance_tips_and_tricks.html) (reading a dict,
  list indexing and `append` are fast compiled; interpreted classes and callable values are slow),
  which is why the compiled wheel meets the bar on every path and the pure build pays for the
  same operations.
- The collector: CPython's [garbage collector design
  notes](https://github.com/python/cpython/blob/main/InternalDocs/garbage_collector.md) (a young
  collection runs when allocations minus deallocations pass `threshold0`; tuples whose contents are
  untracked can be untracked, a list is always tracked).

### The pure build against the hand-written Python, after J90-PF2 (#316 G4)

**The collector is on again for a hot index refresh** (`storage/hotindex.py`; pinned by
`test_a_refresh_leaves_the_collector_on`, which fails on the J90-PF shim). J90-PF wrapped
`HotIndex.refresh` in `gc.disable()`. That saved no collector work. It only moved the work to
later operations. While the collector is off, CPython still counts allocations against
`threshold0` and still counts young collections against `threshold1` ([gc
module](https://docs.python.org/3/library/gc.html), *set_threshold*). The collections a refresh
owed therefore ran in whatever operation the caller ran next.

This was measured with a `gc.callbacks` timer on each bench path (n = 5, interleaved; collector ms
per path, median). Each comparison is with the collector off around `refresh` against on:

- **Compiled, 3.12.** The open path paid for a 2.6 ms middle-generation collection. The J90-PF
  wheel's open path took 7.51 ms; without that shim change it took 5.05 ms. The build's full
  collection (about 6 ms) was not saved either: it ran in the retention pass instead, which spent
  10.7 ms of collector time against 4.0.
- **Pure, 3.12.** The build spent 2.1 ms in the collector against 8.2, and the retention pass
  spent 9.1 ms against 2.4. Over the whole run, the collector took 119.3 ms against 115.6. The sum
  of all path medians was 2755.8 ms against 2753.2.
- **Pure, 3.14.** The interpreter was 3.14.5, whose collector is again 3.13's generational one
  ([gc module](https://docs.python.org/3/library/gc.html), *Changed in version 3.14.5*). Over the
  whole run, the collector took 108.4 ms against 102.6. The sum of the paths was 2660.0 ms against
  2666.8.

The cold index keeps its `gc.disable()` around `add` / `compact`. The collections it defers run
in the caller's next operation, as the Decision below measures (+1.3 to +1.75 ms on a recall after
a compaction or an add). With the collector left on there, 3.14 compaction took 52.5 ms against
50.7 (n = 7).

**Decision (the owner, 2026-11-18): the collector stays off around `ColdIndex.add` / `compact`,
and this is its cost.** J90-RR measured it on this branch against the same code with `_no_gc`
made a no-op, interleaved, n = 9 pure and n = 7 compiled (`gc_rr.py`, `gcdrive.py` in J90-RR's
scratch; quoted from J90-RR, not rerun in J90-RF2). No answer changes either way.

- **Gained: the writes are faster.** Compaction −2.7 ms pure 3.12, −4.5 ms compiled 3.12, −18 ms
  compiled 3.14. Over a long-lived server loop (30 rounds of add + query + recall, compaction every
  10) the total time is the same or better.
- **Paid: the caller's next operation runs the deferred collection.** A recall after a compaction
  +1.3 ms pure 3.12 (9.17 against 7.84) and +1.4 ms compiled 3.12; a recall after an add +1.75 ms
  compiled 3.14 (9.92 against 8.17). The worst single collector pause is larger: 16.4 against
  11.6 ms pure 3.12, 23.2 against 18.1 ms compiled 3.12, 16.9 against 7.5 ms compiled 3.14. Peak
  RSS is higher: +7 MB pure 3.12, +17.6 MB pure 3.14, +17 MB compiled 3.12, about 0 compiled 3.14.
- **Why this differs from the hot index**, where J90-PF2 removed the same wrapper: there it saved
  no time and only moved the cost to later operations; here the write itself gets faster and the
  total does not get worse.

**Measured and not taken.**

- **`gc.freeze()` / `gc.unfreeze()` at the end of a refresh.** This would reset the young count,
  but only by moving every object the process tracks, including the caller's, into the permanent
  generation and then back into the oldest. The [gc module](https://docs.python.org/3/library/gc.html)
  and the change it came from ([Instagram's copy-on-write
  fix](https://instagram-engineering.com/copy-on-write-friendly-python-garbage-collection-ad6ed5233ddf),
  [bpo-31558](https://bugs.python.org/issue31558)) describe it as a process-wide tool to call
  before `fork()`. A library should not change that for its host. `unfreeze` would also release
  objects the host had frozen itself.
- **A `Counter`-backed tally adapter for the derive's per-field token counts.** It made `derive`
  slower: 88 ms against 84 (3.14, phase timer). Of the build's 27,000 tokens, 25,000 occur once in
  their field. The `Map` the tally returns and the walk over it cost more than the counting saved.
- **`encoded.set(t, encodeSegments(r))` written through a local**, so that ts2py writes the
  statement `set` inline: no change (80.6 against 80.5 ms, micro, 3.14).
- **`encodeSegments` as an indexed loop:** 6.3 ms against 4.7 over the 8,285 calls of a real build.

**Measured** (`bench/drive.py` with a scratch HOME; n = 9 interleaved fresh processes per side;
median [min..max] ms; macOS arm64).

- **Load:** average 2.6 at the start and 3.4 at the end. An editor's language servers were running;
  no other suite was.
- **Sides:** hand = 9c6bc181, pure = this tree, comp = this tree's mypyc wheel.
- **Verdict:** each median against hand's range on the same version.

| Path | 3.12 hand | 3.12 pure | 3.12 comp | 3.14 hand | 3.14 pure | 3.14 comp | verdict pure / comp, 3.12; 3.14 |
|---|---|---|---|---|---|---|---|
| import | 90.4 [88.2..145.5] | 93.6 | 94.8 | 84.4 [82.0..111.8] | 87.6 | 87.8 | in / in; in / in |
| hot cold build | 398.5 [394.2..431.3] | 415.0 [405.7..439.5] | 363.9 | 384.2 [380.0..402.7] | **402.8** [399.5..417.9] | 360.5 | in (median +4.1%) / under; **over (+4.9%)** / under |
| hot open + query | 5.82 [4.5..6.3] | 5.39 | 4.85 | 5.33 [4.3..5.9] | 5.18 | 4.63 | in / in; in / in |
| hot held query x20 | 5.37 [5.0..5.6] | 5.26 | 3.76 | 5.33 [4.9..5.6] | 5.02 | 3.71 | in / under; in / under |
| hot full refresh | 14.74 [14.4..17.1] | 15.31 | 14.66 | 14.87 [14.0..15.6] | 15.09 | 13.83 | in / in; in / under |
| cold build | 84.36 [83.9..87.8] | 83.98 | 46.11 | 79.78 [78.6..90.0] | 80.31 | 50.10 | in / under; in / under |
| cold query x20 | 36.03 | 20.09 | 12.98 | 30.30 | 20.05 | 13.28 | under / under; under / under |
| cold compact with keep | 51.00 [50.5..54.0] | 51.91 | 33.07 | 49.13 [48.1..66.2] | 50.07 | 35.11 | in / under; in / under |
| retention run | 1236.1 | 1205.2 | 937.3 | 1179.1 | 1167.5 | 936.4 | under / under; under / under |
| tier lines x5 | 1417.4 | 776.6 | 705.9 | 1522.7 | 752.8 | 710.2 | under / under; under / under |
| first `memory_save` | 32.19 | 30.53 | 23.64 | 31.62 | 29.57 | 23.65 | under / under; under / under |
| #204 bar recall p50 | 8.22 | 7.76 | 7.66 | 7.61 | 7.27 | 7.61 | under / under; under / in |

**Against earlier wheels:**

- **The J90-PF wheel, same run.** Open + query took 7.10 ms on 3.12 (4.85 now) and 5.73 ms on 3.14
  (4.63 now). Its other paths were within this wheel's spread.
- **The J90-RF wheel, an earlier run (n = 7).** Its 3.12 open path took 5.62 ms against 4.68 for
  this shim, so J90-PF's unexplained 0.9 ms does not reproduce.
- **Node.** No TypeScript changed, so Node is unchanged: the 14-source build took 182.8, 188.0 and
  189.1 ms (best of 7, three runs).

**What is still over: the pure 14-source hot build.** On 3.14 it is over hand's range. On 3.12 it is
inside only because hand's range reaches its 431 ms outlier.

*Where the time goes.* Phase timers on 3.14, best of 6:

| Phase | hand (ms) | pure (ms) |
|---|---|---|
| parse | 213 | 223 |
| derive | 70 | 83 |
| write | 67 | 62 |
| total | 360 | 378 |

The parse runs the same shared code (603 against 619 ms under cProfile), so the gap is in
`derive`. A micro of `derive` alone (best of 15, 3.14), stubbing one piece at a time:

| `derive` micro | hand (ms) | pure (ms) |
|---|---|---|
| as written | 68.4 | 79.1 |
| tokenizing stubbed | 23.9 | 43.3 |
| fingerprints also stubbed | 16.5 | 32.3 |
| `encodeSegments` also stubbed | 13.7 | 26.6 |

The 13 ms left after those stubs is the loop's own per-operation guards:

- The same loop with every guard dropped (as if every type were proven) took 21.1 ms against 32.1
  and built the same postings.
- Dropping only the receiver tests ts2py could prove today (a `const` bound to `new Map()` or to an
  array literal) bought about 1 ms.
- An inline per-row test in place of `_js_rows`, for `for (const [i, a, b, c] of rows)` over a
  proven list, bought 0.7 ms of `encodeSegments`' 4.7.

This is the gap J90-PF and J90-P6 already named. PEP 659's adaptive specialization
([PEP 659](https://peps.python.org/pep-0659/)) already type-tests every dict read, list store and
int add inside the interpreter. Each Python-level guard in the generated code is extra work that
hand-written code does not do. mypyc compiles those operations to C
([performance tips](https://mypyc.readthedocs.io/en/latest/performance_tips_and_tricks.html)),
which is why the compiled build is 7-10% under hand on this path.

*The smallest change that would close it: element and return type facts in ts2py.* For example,
`tokenizeV2` returns a list of `str` (every push is a slice of a `str`), `tfs` holds only rows the
loop built itself, and a `for (let i = 0; i < n; i += 1)` counter is a safe int. With those facts
the derive loop could drop its key, receiver and index tests.

- **Estimated gain:** the bound above, about 11 ms of a 14-source build (2.7%). That would bring
  3.14 to about 392 ms, inside hand's range.
- **Estimated cost:** an interprocedural fact pass in `lower.rs`, with its own soundness proof for
  each fact (a `Map` reached from outside the module may hold kept keys; a list may be pushed a
  non-`str`). Judging by the size of `types.rs` and of J90-PF's rules, that is a unit of its own,
  not a single rule.


### The pure build after J91-1 (#341: type facts for guarded expansions)

**What J91-1 built** (`tools/ts2py/RULES.md`, *J91-1 rules*): three facts (`map`: a value `new Map()`
made; `int`: a safe int; `idx`: an int in `[0, 2**52]`), counted loops (`for (let i = L; i < B; i += S)`
whose variable is an index in its body), lengths as indices, exact `+` / `-` of two indices, and
guarded expansions that leave out each test an operand's fact answers. No TypeScript changed (a
`derive` respelling that let ts2py count its field loop was reverted: Node's `cold query x20` was
0.5 ms slower after it in three runs). Every conformance suite still compares the two runtimes.

**What it bought, where J90-PF2's bound said 11 ms.** That bound came from a `derive` micro with
tokenizing, fingerprints and `encodeSegments` stubbed. In the real build (phase timers, 3.14, best of
6) dropping EVERY guard of the derive loop by hand moved `derive` from 82 to 79-80 ms; hand's is 68.
Key tests alone were about 1 ms, receiver tests 0.5, index tests 0.5. The facts J91-1 proves take
about half of that bound (derive 82 to about 80). The element facts the brief named (`tokenizeV2`
returns `str`s; a Map the loop fills keeps its row shape) are inside that same 1.3 ms bound and need
more than the facts: `tokenizeV2` is called through its guarded entry (its argument, `text[field]`
of a parsed doc, is not proven a `str`), whose untyped body slices what the `pyNfkcLower` adapter
returns, of no proven type.

**Where the remaining gap is** (3.14, 14-source build, best of 6; callees timed inside `derive`):

| | hand (ms) | pure (ms) |
|---|---|---|
| `tokenizeV2` | 31.2 | 28.5 |
| `tokens` | 12.4 | 7.1 |
| shard hashing (8,285 terms) | 3.5 | 6.3 |
| `encodeSegments` (8,285 calls, 2.65 rows each) | 2.2 | 5.8 |
| fingerprints of 448 tables | 7.5 | 11.2 (lift guard 3.2 warm) |
| `derive`'s own loops | 14.8 | 24.2 |
| `derive` | 71 | 84 (wrappers included) |

Parse is about 6 ms over hand and write even. The loop gap is structural: hand counts tokens with
`collections.Counter`, whose `update` calls the C helper `_count_elements`
([Lib/collections/__init__.py](https://github.com/python/cpython/blob/main/Lib/collections/__init__.py)),
and fills postings with `dict.setdefault` and `Counter.update` of the keys, one C call each; the
generated loop does the same work one Python-level operation at a time. With every guard gone, the
loop alone measured 21.1 ms against hand's 13.7 (J90-PF2), so no type fact closes it. The adaptive
interpreter already specializes each of those operations ([PEP 659](https://peps.python.org/pep-0659/)),
and the compiled wheel, where mypyc compiles list and dict operations to C
([performance tips](https://mypyc.readthedocs.io/en/latest/performance_tips_and_tricks.html)), is
under hand on this path. `encodeSegments` is per-call overhead on tiny inputs (a guarded entry and a
typed body per call); a one-time element check per call costs more than the guards it would save.

**Measured** (`bench/drive.py` as J90-RR ran it, scratch HOME; n = 11 interleaved fresh processes
per side; median [min..max] ms; macOS arm64; a virtual machine was running, load 3.7 at the start
and 2.8 at the end; hand = 9c6bc181, main = a9ae1ff7, J91 = 9ce87c65, comp = each tree's mypyc wheel;
verdict = J91 pure against hand's range without hand's maximum).

| Path | 3.12 hand | 3.12 main | 3.12 J91 | comp main / J91 | verdict |
|---|---|---|---|---|---|
| import | 139.9 [95.8..157.4] | 101.8 | 99.7 | 108.5 / 109.7 | in |
| hot cold build | 393.8 [384.3..440.2] | 407.2 [398.6..414.0] | 404.6 [389.1..410.6] | 359.9 / 358.4 | in (median +2.7%) |
| hot open + query | 4.64 [4.2..5.2] | 5.06 | 5.07 | 4.53 / 5.08 | in |
| hot held query x20 | 4.95 [4.7..5.2] | 5.20 | 5.06 | 3.55 / 3.70 | in |
| hot full refresh | 14.48 [13.9..16.0] | 15.12 | 15.15 | 13.94 / 14.30 | **over** (+4.6%) |
| cold build | 83.76 [81.6..108.0] | 83.37 | 82.49 | 44.91 / 45.31 | in |
| cold query x20 | 35.72 | 19.81 | 19.52 | 12.65 / 12.81 | under |
| cold compact with keep | 50.73 [49.0..54.3] | 51.45 | 51.23 | 31.87 / 32.16 | in |
| retention run | 1230.1 | 1199.6 | 1199.4 | 928.6 / 930.7 | under |
| tier lines x5 | 1404.6 | 771.5 | 770.8 | 699.9 / 704.0 | under |
| first `memory_save` | 30.58 | 29.12 | 29.04 | 22.84 / 23.14 | under |
| #204 bar recall p50 | 7.84 | 7.51 | 7.51 | 7.43 / 7.51 | under |

| Path | 3.14 hand | 3.14 main | 3.14 J91 | comp main / J91 | verdict |
|---|---|---|---|---|---|
| import | 127.8 [89.5..149.7] | 93.9 | 93.0 | 103.7 / 103.7 | in |
| hot cold build | 380.7 [375.3..401.2] | 398.3 [385.5..412.7] | 394.1 [388.6..414.3] | 357.6 / 358.0 | **over** (+3.5%) |
| hot open + query | 4.36 [3.8..5.1] | 4.96 | 4.96 | 4.42 / 4.60 | **over** |
| hot held query x20 | 5.02 [4.6..5.2] | 5.05 | 5.11 | 3.67 / 3.73 | in |
| hot full refresh | 13.94 [13.6..42.8] | 14.77 | 14.90 | 13.82 / 14.15 | **over** |
| cold build | 79.01 [77.5..86.6] | 78.45 | 77.98 | 49.25 / 49.78 | in |
| cold query x20 | 29.77 | 19.94 | 19.43 | 13.03 / 13.16 | under |
| cold compact with keep | 47.88 [47.1..53.9] | 49.73 | 49.40 | 34.21 / 34.80 | **over** (+3.2%) |
| retention run | 1173.2 | 1163.7 | 1163.1 | 930.5 / 930.6 | under |
| tier lines x5 | 1513.2 | 752.3 | 751.6 | 705.5 / 714.3 | under |
| first `memory_save` | 30.23 | 28.92 | 28.75 | 22.75 / 22.95 | under |
| #204 bar recall p50 | 7.62 | 7.31 | 7.28 | 7.53 / 7.60 | under |

**Not closed.** The pure build is still over hand on the hot build (3.14), the hot open path
(3.14), the full refresh (both) and compaction (3.14). J91-1 moved the 3.14 build 4 ms (398.3 to
394.1 here; 395.6 to 391.2 on a quieter run of 9ce87c65's parent, n = 9); nothing else moved past
its spread. What would close the build is C-level counterparts of hand's idioms (a tally into a
`dict`, `setdefault`-and-append) as runtime helpers with their own exactness proofs, which #341
did not ask for. Node is unchanged: no TypeScript changed (n = 11: 14-source build 213.3 main,
213.4 J91).

**The compiled build: one small regression, not closed.** A compiled-only rerun (n = 15) puts every
path within its spread except the cold build, which is consistently about 0.5 ms slower: 45.20
[44.2..46.6] against 44.73 [43.9..47.1] on 3.12 and 49.80 [48.4..51.8] against 49.20 [48.5..55.2]
on 3.14, the same direction in all three runs that measured it (n = 9, 11, 15). The 3.14 full
refresh was 13.93 against 13.42 here and 13.71 against 13.49 at n = 11. The open path is not slower
(4.60 against 5.03 on 3.12). Not yet isolated: the generated code mypyc compiles differs only where a
guard was dropped or a counter is now a plain int `+`.

### The pure build after J91-2 (#341: exact runtime helpers, and mypyc's narrowing)

**Re-measured first** (`bench/drive.py` as J90-RR ran it, scratch HOME, n = 11 interleaved fresh
processes per side, load 1.52 at the start and 5.0 at the end with the VM running; 78f8d10c against
hand 9c6bc181; verdict against hand's range without its maximum). Really over: the hot build (3.12
+3.6%, 3.14 +4.4%), the full refresh (3.12 +4.9%, 3.14 +6.3%), the 3.14 open path (+2.6%) and the
3.14 compaction (+3.1%). The 3.12 open path and compaction were inside hand's range.

**What J91-2 built** (`tools/ts2py/RULES.md`, *J91-2 rules*): `hash_hex_int` for
`parseInt(<hash chain>.slice(0, N), 16)` (the shard hash: `derive` 80.4 to 78.6 ms, 3.14, best of
4 per process over 6 interleaved processes), a destructuring for-of over a proven list unpacked in
the loop without `_js_rows`' generator (`encodeSegments`' 8,285 calls 5.25 to 4.42 ms), and type
tests kept where J91-1's facts had dropped them (below). The other idioms were each built by hand in
the generated `derive` and measured there first; none was faster (RULES.md, *Measured and not
taken*): a `Counter` tally 79.7 against 79.0, a group-into helper 79.5, an inline `shardOf` memo
-0.5 ms, a per-call element check in `encodeSegments` 7.89 against 5.25 ms.

**The compiled regression J91-1 left: found and fixed.** J91-1's facts dropped `type(m) is _JsMap`,
`type(xs) is list` and `type(i) is int` from the guarded expansions. Those are the tests mypyc
narrows a value by. Every generated function is unannotated, so mypy does not check its body and a
value's only static type is what such a test narrows it to. With the test, mypyc reads `m._entries`
from the native struct; without it, mypyc does a generic `CPyObject_GetAttr`. This was checked in the
C that mypy 2.4.1's mypyc writes for a two-function module. A local annotation would type the value
too, but mypy refuses it in an unchecked function (`annotation-unchecked`), and the build's mypy
configuration is J90-P7's. J91-2 keeps every type test and drops only range and sign tests. Pure
cost: about 0.5 ms of `derive`. Compiled, n = 15 interleaved, load 1.49 at the start (main / J91-1
/ J91-2, median [min..max] ms):

| Path | 3.12 main | 3.12 J91-1 | 3.12 J91-2 | 3.14 main | 3.14 J91-1 | 3.14 J91-2 |
|---|---|---|---|---|---|---|
| cold build | 44.75 [42.3..46.2] | 45.59 [43.8..47.1] | 45.05 [43.6..45.9] | 49.39 [47.5..50.8] | 50.11 [49.0..51.3] | 49.74 [48.4..50.9] |
| cold compact with keep | 32.55 | 32.79 | 32.55 | 34.89 | 35.17 | 34.93 |
| cold query x20 | 12.48 | 12.73 | 12.52 | 12.88 | 13.00 | 12.84 |
| hot open + query | 5.00 [4.2..5.4] | 5.19 | 5.17 [4.5..5.5] | 4.98 [4.4..5.3] | 5.06 | 5.11 [4.2..5.4] |
| hot full refresh | 14.49 | 14.42 | 14.51 | 14.13 | 14.05 | 14.14 |

The cold build's +0.8 / +0.7 ms is now +0.3 / +0.35, inside main's spread. Compaction and cold query
are back to main. The open path and the full refresh were never apart beyond their spread: a 3.14
run of n = 11 before the fix put main 4.96, J91-1 4.98 and the fix 5.03 on the open path, and J91-1
13.42 against main 13.55 on the refresh.

**Measured** (n = 11 interleaved, load 1.30 at the start and 2.46 at the end; hand = 9c6bc181, main
= a9ae1ff7, J91-2 = 2a2284b6; comp = each tree's mypyc wheel; median [min..max] ms):

| Path | 3.12 hand | 3.12 main | 3.12 J91-2 | comp main / J91-2 | verdict |
|---|---|---|---|---|---|
| import | 143.61 [125.4..182.3] | 101.15 | 100.17 | 109.43 / 108.52 | under |
| hot cold build | 398.70 [393.5..437.6] | 410.73 [396.1..435.5] | 408.95 [401.9..465.2] | 362.60 / 360.79 | **over** (+2.6%) |
| hot open + query | 4.56 [4.3..5.4] | 5.06 | 5.10 [4.8..5.3] | 4.66 / 5.32 | **over** |
| hot held query x20 | 5.06 [4.8..5.4] | 5.23 | 5.18 | 3.58 / 3.67 | in |
| hot full refresh | 14.64 [14.3..15.3] | 15.17 | 15.37 [14.4..16.7] | 14.48 / 14.42 | **over** (+5.0%) |
| cold build | 84.21 [82.5..85.3] | 83.71 | 83.71 | 44.86 / 45.11 | in |
| cold query x20 | 35.62 | 19.89 | 20.16 | 12.52 / 12.62 | under |
| cold compact with keep | 51.03 [48.7..52.0] | 52.23 | 52.09 [51.6..76.6] | 32.51 / 32.71 | **over** (+2.1%) |
| retention run | 1231.65 | 1197.69 | 1194.82 | 926.63 / 927.24 | under |
| tier lines x5 | 1406.78 | 767.70 | 771.00 | 698.03 / 696.28 | under |
| first `memory_save` | 30.90 | 29.19 | 29.07 | 23.05 / 22.80 | under |
| #204 bar recall p50 | 8.01 | 7.42 | 7.49 | 7.43 / 7.45 | under |

| Path | 3.14 hand | 3.14 main | 3.14 J91-2 | comp main / J91-2 | verdict |
|---|---|---|---|---|---|
| import | 120.15 [114.3..201.0] | 94.84 | 91.85 | 103.66 / 100.34 | under |
| hot cold build | 381.99 [378.1..391.0] | 399.67 [396.7..407.4] | 398.07 [393.2..400.1] | 359.45 / 359.14 | **over** (+4.2%) |
| hot open + query | 4.80 [4.4..5.0] | 5.09 | 5.01 [4.8..5.2] | 4.52 / 4.89 | **over** (+4.5%) |
| hot held query x20 | 5.06 [4.7..5.4] | 5.12 | 5.06 | 3.68 / 3.79 | in |
| hot full refresh | 14.13 [13.4..15.3] | 15.25 | 15.17 [14.8..15.6] | 14.11 / 14.01 | **over** (+7.3%) |
| cold build | 79.18 [78.0..90.4] | 78.96 | 78.55 | 49.74 / 49.35 | in |
| cold query x20 | 29.72 | 19.81 | 19.83 | 13.03 / 12.90 | under |
| cold compact with keep | 48.59 [47.9..50.6] | 50.11 | 49.90 [49.6..50.6] | 34.78 / 34.73 | **over** (+2.7%) |
| retention run | 1169.35 | 1160.75 | 1154.17 | 929.47 / 929.34 | under |
| tier lines x5 | 1505.50 | 745.34 | 745.60 | 705.66 / 706.16 | under |
| first `memory_save` | 30.24 | 28.78 | 28.49 | 23.21 / 22.90 | under |
| #204 bar recall p50 | 7.55 | 7.24 | 7.24 | 7.49 / 7.54 | under |

The compiled open path (4.66 / 5.32 and 4.52 / 4.89 in this run) is not a regression: at n = 15 (the
table above) its three trees lie within each other's spread. Node is unchanged (no TypeScript
changed; n = 11, main / J91-2 dist: 14-source build 217.71 / 218.83, open 4.22 / 4.17, refresh
14.04 / 14.18, cold build 32.64 / 32.76, compaction 30.31 / 30.49).

**Not closed: the floor.** J91-2 moved `derive` about 1.5 ms (3.14, best of 4 per process: J91-1
79.8, J91-2 78.1). That is under 0.5% of the hot build, which is still over hand by 2.6% (3.12) and
4.2% (3.14). Where the rest of `derive`'s gap is (3.14; the generated `derive` edited by hand, one
change at a time, `/private/tmp/claude-501/j92/{ideal.py,mkexp.py}`):

- every guard and helper of the loops removed: 77.3 to 69.6 ms (the per-field work over
  `FIELD_BOOST`, an imported array no fact reaches, 2.5 of it);
- `_js_lifted`'s shape scan: 3.1 ms of `dumpIndex`'s 9.3 over 448 tables, a type scan of every
  item;
- `encodeSegments`' guarded compares: 4.4 ms against 1.8 for the same loop on plain ints.

A tight exact-JS `derive` with element facts assumed is 55-58 ms, against hand's 66-68. So the gap is
element facts (what `tokenizeV2` returns, what `tfs` and `words` hold, what an imported const array
is), not C helpers. Hand's C helpers do not beat plain Python here:

- `Counter.update` runs `_count_elements` in C ([Lib/collections/__init__.py](https://github.com/python/cpython/blob/main/Lib/collections/__init__.py)).
  Its loop still does a hash-keyed dict lookup and a generic `PyNumber_Add` per element
  ([Modules/_collectionsmodule.c](https://github.com/python/cpython/blob/main/Modules/_collectionsmodule.c)).
  With 25k of 27k tokens distinct, the saving is one interpreter dispatch per repeat, and building
  the rows pays it back per distinct term (measured above).
- The adaptive interpreter already specializes the plain loop's attribute and subscript operations
  per instruction ([PEP 659](https://peps.python.org/pep-0659/)).

The compiled wheel is the build where those operations are C. mypyc compiles operations on `Any`
values to generic ones; the docs give the reason: "Operations on erased types use generic
operations that work with arbitrary objects"
([using type annotations](https://mypyc.readthedocs.io/en/latest/using_type_annotations.html)).
Typed native-class attribute access is listed as fast
([performance tips](https://mypyc.readthedocs.io/en/latest/performance_tips_and_tricks.html)).
mypy does not check the bodies of unannotated functions without `--check-untyped-defs`
([command line](https://mypy.readthedocs.io/en/stable/command_line.html),
[annotation-unchecked](https://mypy.readthedocs.io/en/stable/error_code_list.html)).

The full refresh and the open path were not profiled into `derive`: neither rebuilds. Parse (6 ms
over hand on the build) is `extract_refs` and the YAML read, shared with hand.

### The pure build after J91-3 (#341: element and return facts; the open path and the full refresh)

**What J91-3 built** (`tools/ts2py/RULES.md`, *J91-3 rules*; pinned in
`tools/ts2py-bantamkit/tests/j93.rs`): sealed `own` lists, Maps and Sets keep what was put in
them; what a function returns is what every return proved, across the compiled modules (rounds of
the whole compile, so also through the `hotindex.ts` / `store.ts` cycle); a `str` contract on the
`pyNfkcLower` adapter row; a `g` match's `str`s; `a ?? b`; a for-of `const` narrowed by a guard;
and `_js_json_ints_exact` over a byte probe. In `derive` the token loop's `t`, the term loop's
`term` and the word loop's `w` are proven `str`s, so their eight key tests are gone; `shard_of` is
called through its typed body; `toks.length` is `len(toks)`. `derive` (3.14, best of 4 per process,
6 interleaved processes, `/private/tmp/claude-501/j93/vdrive.py`): 77.5 to 71.3 ms.

Found and fixed on the way: a `const` and a `let` of one name in two blocks of one function are one
Python binding, so the `const`'s key let a guard narrow the `let` past an assignment to it
(`let v = rows[1]; if (Array.isArray(v)) { v = opaque(5); v.length }`: Node `undefined`, Python a
TypeError). A binding is now narrowable only when nothing assigns it. No shipped module had the
shape: regenerating every module with the fix changed none.

**Measured and not taken**: `FIELD_BOOST` as a frozen constant across modules (an exported
constant every importer only reads), whose counted per-field loop the generated `derive` was edited
by hand to: 71.9 to 70.7 ms (3.14), about 0.3% of the build; it needs an escape analysis over every
importing module and over the hand-written Python that imports the generated constant. A
destructuring for-of over a sealed Map as `_entries.items()` (about 0.5 ms of `derive`): it needs
proof that the body cannot change the Map.

**The open path and the full refresh, profiled** (`/private/tmp/claude-501/j93/acc.py`: inclusive
time of each method over the 14 sources, best of 15 in one process after a build; hand 9c6bc181 and
J91-3; ms):

| Path, method | 3.12 hand | 3.12 J91-3 | 3.14 hand | 3.14 J91-3 |
|---|---|---|---|---|
| open + query, total | 3.60 | 4.15 | 3.43 | 4.18 |
| reading 70 shards (`readShard`) | 2.26 | 2.49 | 2.24 | 2.64 |
| of which `JSON.parse` / `_loads` | 1.37 | 1.55 | 1.38 | 1.49 |
| of which `new Map(entries(terms))` (`_js_map_entries`) | - | 0.10 | - | 0.27 |
| the 14 heads (`load` / `_load`) | 0.49 | 0.88 | 0.48 | 0.76 |
| full refresh, total | 12.55 | 13.18 | 12.29 | 12.82 |
| `write` | 5.28 | 5.89 | 5.54 | 5.73 |
| the tails' parse and checks (`_complete_tail`; hand: `_loads`) | 2.28 | 3.59 | 2.24 | 3.59 |
| the stat listing | 3.58 | 1.94 | 3.19 | 1.94 |
| `check` / `patch` | 0.85 | 1.25 | 0.88 | 1.20 |

Where the time goes, function by function: the JSON parse's integer check (the full refresh's 14
tails, 600 KB: 1.03 ms before J91-3's byte probe, 0.69 after; the decode itself is hand's, 2.20
against 2.17); the Map built from each shard's terms (`set(map(type, ...))` over the keys, the
copy, the digit scan: 0.28 ms for all 448 tables); the head's checks in `load` (each property a
`_js_get` dispatch, and `isCols`' per-element range loop over every doc, where hand takes `min` /
`max` at C speed); `write`'s property reads (J91-3 reads each family's prints once); the tails'
`files` loop (J91-3 narrows the for-of `const` `v` by `Array.isArray`, so its reads are list reads).

**Measured** (n = 11 interleaved fresh processes per side, each round started at a 1-minute load
of 1.5 or less: 1.19 to 1.50; hand = 9c6bc181, main = a9ae1ff7, J91-2 = b696340a, J91-3 = f5dbfe2f;
comp = each tree's mypyc wheel; median [min..max] ms; verdict = J91-3 pure against hand's range
without its maximum):

| Path | 3.12 hand | 3.12 main | 3.12 J91-2 | 3.12 J91-3 | comp main / J91-2 / J91-3 | verdict |
|---|---|---|---|---|---|---|
| import | 131.58 [86.2..144.8] | 94.75 | 93.72 | 93.63 | 104.96 / 104.45 / 103.73 | under |
| hot cold build | 416.06 [377.3..433.3] | 390.55 | 388.32 | 383.42 [379.1..396.3] | 348.29 / 347.56 / 347.64 | under |
| hot open + query | 4.27 [4.0..4.9] | 4.81 | 4.76 | 4.78 [4.6..4.9] | 4.28 / 4.80 / 4.87 | **over** (+12.1%) |
| hot held query x20 | 4.74 [4.6..4.8] | 5.02 | 4.95 | 5.03 [4.8..5.4] | 3.50 / 3.58 / 3.49 | **over** (+6.0%; main the same) |
| hot full refresh | 13.76 [13.3..14.6] | 14.63 | 14.74 | 14.24 [13.6..24.5] | 13.59 / 14.02 / 13.47 | **over** (+3.5%) |
| cold build | 81.23 [79.5..84.5] | 80.74 | 81.07 | 69.25 [68.6..71.0] | 43.93 / 43.70 / 41.93 | under |
| cold query x20 | 34.16 | 19.22 | 19.33 | 19.48 | 12.06 / 12.25 / 12.25 | under |
| cold compact with keep | 49.11 [47.4..51.8] | 51.10 | 50.35 | 45.17 [44.4..46.2] | 31.16 / 31.48 / 30.69 | under |
| retention run | 1198.88 | 1170.83 | 1169.36 | 1000.74 | 906.03 / 905.85 / 822.03 | under |
| tier lines x5 | 1361.00 | 734.75 | 734.75 | 742.18 | 668.19 / 672.78 / 671.74 | under |
| first `memory_save` | 29.51 | 28.13 | 28.08 | 27.63 | 21.39 / 21.45 / 21.40 | under |
| #204 bar recall p50 | 7.81 | 7.30 | 7.36 | 7.36 | 7.24 / 7.30 / 7.38 | under |

| Path | 3.14 hand | 3.14 main | 3.14 J91-2 | 3.14 J91-3 | comp main / J91-2 / J91-3 | verdict |
|---|---|---|---|---|---|---|
| import | 125.26 [78.2..171.0] | 89.55 | 88.89 | 88.68 | 100.83 / 101.95 / 98.99 | under |
| hot cold build | 371.39 [366.3..389.7] | 388.17 | 386.84 | 380.55 [376.8..403.5] | 349.69 / 349.56 / 344.12 | in (+2.5%) |
| hot open + query | 4.56 [4.3..5.0] | 4.63 | 4.72 | 4.81 [4.6..5.3] | 4.25 / 4.77 / 4.74 | **over** (+5.4%) |
| hot held query x20 | 5.02 [4.6..5.1] | 4.97 | 5.09 | 5.01 | 3.67 / 3.71 / 3.62 | in |
| hot full refresh | 13.77 [13.1..14.1] | 14.67 | 14.88 | 14.35 [13.5..15.4] | 13.46 / 13.39 / 13.36 | **over** (+4.2%) |
| cold build | 78.19 [77.0..82.9] | 78.23 | 77.84 | 65.73 [64.8..68.7] | 48.89 / 48.71 / 45.47 | under |
| cold query x20 | 29.27 | 19.53 | 19.58 | 19.57 | 12.70 / 12.64 / 12.63 | under |
| cold compact with keep | 47.99 [46.9..49.3] | 49.63 | 49.38 | 44.01 [43.4..45.4] | 34.26 / 33.99 / 32.56 | under |
| retention run | 1159.15 | 1148.63 | 1148.55 | 964.89 | 922.83 / 921.51 / 831.01 | under |
| tier lines x5 | 1468.50 | 727.26 | 727.00 | 728.29 | 685.79 / 690.68 / 691.85 | under |
| first `memory_save` | 29.42 | 27.85 | 27.74 | 27.02 | 22.09 / 21.99 / 21.71 | under |
| #204 bar recall p50 | 7.46 | 7.20 | 7.16 | 7.22 | 7.34 / 7.45 / 7.46 | under |

Against main, the cold build (-14% / -16%), compaction (-12% / -11%) and the retention run (-15% /
-16%) moved most (3.12 / 3.14): they parse the
same large JSON texts the byte probe now checks without a loop step per 16-digit string. The hot
build is under hand on 3.12 and inside hand's range on 3.14. Compiled, J91-3 is no slower than main
on any path beyond the spread; the open path's compiled 4.28 (main) against 4.80 / 4.87 is J91-1's
and J91-2's (n = 15 in *The pure build after J91-2*: the three trees inside each other's spread).

Node (TypeScript changed: three respellings; n = 11 and 15 interleaved, main a9ae1ff7 dist against
J91-3's): the build 208.30 / 208.30, the open path 4.17 / 4.22, the full refresh 13.50 / 13.68,
compaction 28.61 / 28.58 (n = 15). The refresh's 0.2 ms is the noise of identical code: an A/A run
(n = 11) put main's dist at 13.17, a byte-identical copy of it at 13.43 and J91-3's at 13.18; and
J91-3's dist with `write`'s old loop restored measured 13.53 against J91-3's 13.52 (n = 15).

**Not closed: the floor.** Open + query is over by 12.1% (3.12) and 5.4% (3.14), the full refresh
by 3.5% and 4.2%; in-process, 0.55 / 0.75 ms and 0.63 / 0.53 ms. Each piece is a fixed Python cost
of JS's semantics that hand does not pay:

- `JSON.parse` of a shard keeps a JS number exact: a text with no `-0` and no 16-digit integer
  token takes CPython's own integers, any other the per-token hook. CPython's scanner calls a
  `parse_int` hook through Python unless it is `int` itself
  ([Modules/_json.c](https://github.com/python/cpython/blob/main/Modules/_json.c),
  `_match_number_unicode`: `custom_func` is NULL only when `parse_int` is `PyLong_Type`), so the
  check runs first over every text, at about 1.1 ns a byte with the probe.
- `new Map(Object.entries(terms))` must answer a Map whose order is JS's (array-index keys first),
  so the keys are scanned for type and digits and the dict copied; hand returns the parsed dict.
- The head's checks read each property through `_js_get` (a JS property read: an own key or
  `undefined`), and `isCols` checks every doc's length and type in a counted loop where hand takes
  `min` and `max` of each column at C speed ([Python/bltinmodule.c](https://github.com/python/cpython/blob/main/Python/bltinmodule.c),
  `min_max`). The loop is the TypeScript's own (the fastest form in Node); taking `min` / `max`
  would need proof that no element is NaN, which `isIntList`'s `Number.isInteger` gives JS but not
  a fact ts2py reads.
- The adaptive interpreter specializes the loop's operations per instruction but still dispatches
  each ([PEP 659](https://peps.python.org/pep-0659/)); the 3.14 run here is 3.14.5, whose collector
  is 3.13's generational one again ([What's New in 3.14](https://docs.python.org/3.14/whatsnew/3.14.html),
  *Garbage collection*), so 3.14's larger `_js_map_entries` share (0.27 against 0.10 ms) is the
  collection the first allocation after a parse pays, not a different collector.

The compiled wheel answers the full refresh (13.47 / 13.36 against hand's 13.76 / 13.77); its open
path (4.87 / 4.74) is J91-1's and J91-2's, as above, and stays over hand's pure 4.27 / 4.56.

## Concurrency

Measured, not assumed: 12 pipelined saves all land in order; a recall behind a save **sees**
the save in Node and does **not** in Python; two processes over 8 trials × 15 saves gave 0
disagreements.

One hazard existed and was **not** a port defect: concurrent same-unit `clock_out` lost a
history entry, 10/10 on Node **and** 10/10 on CPython — reproduced, not introduced, and
job65 (#116) measured the wider shape, two DIFFERENT units of one wave losing 10 of 20 `ok`
answers. Closed on both sides at once: `clock_out` holds `<checkpoint>.lock` (O_EXCL, one
protocol in both runtimes, so a Python writer and a Node writer serialise against each
other) and writes through a per-writer temp name. The `shiftwork` suite's `concurrency/`
cases pin the lock refusal and the old temp name's sibling surviving, per side.

## The published export surface, and the one break in it

`runtime-ts/src/index.ts:161–170` re-exports `clockIn`, `clockOut`, `HISTORY_RING_SIZE`,
`SCHEMA_NAME`, `status`, `TERMINAL_UNIT_STATUS` and `timestamp` from `./shiftwork.js`, plus the
type `ClockOptions`; `runtime-ts/package.json:29–30` points `main` and `types` at
`./dist/index.js` and `./dist/index.d.ts`. So those names are the npm package's **public API**,
not internals — `import { clockIn } from 'bantamkit-mcp'` is a supported call, and its arity is
part of what the package publishes. Nothing else in this repository says so, which is how the
next paragraph happened.

**Two seams that did not meet (#176, job67 J67-3).** Both are Node-only module surfaces — the
Python package publishes no `parseFactText`/`formatFact` and no `PyValue` — so neither is a
divergence and neither has a row above. `formatFact` now also accepts `parseFactText`'s
`{meta, body}` and maps it the way `_facts` builds a `Fact` (`name`/`description`/`type`
required and named when absent, `links` = `list(meta.get("links") or [])`); `codec.mjs` pins
`formatFact(parseFactText(x))` against the reference's `reemit` bytes for every x the port reads
(`#176 per side: …`). `validate` and `iterErrors` refuse a value that is not a tagged `PyValue`
with `<the instance|the schema> must be a PyValue — convert a plain JS value with fromJs() — got
<a plain JS object|a JS array|…>`, where `{a: 1}` used to be answered `got undefined`. Pinned in
`runtime-ts/test/codec.test.mjs`.

**`clockIn` changed arity in job60 and nobody outside this repository was told.** The unit id
went in as the **second positional parameter**, ahead of the options object:

```ts
// before — runtime-ts/src/shiftwork.ts:335 at 1e07fbb^
export function clockIn(checkpoint: string, options: ClockOptions = {}): PyValue
// after  — runtime-ts/src/shiftwork.ts:420, today
export function clockIn(checkpoint: string, unitId: string | null = null, options: ClockOptions = {}): PyValue
```

A caller who wrote `clockIn(path, { now })` now hands the options object to the slot a unit id
occupies. TypeScript stops that at the type. Plain JavaScript does not stop it at all: the
object is read as the id, the call asks for a unit named `[object Object]`, and `now` is
silently dropped — a wrong answer, not an error.

That break is **measured, not predicted**, because this repository walked into it. The
conformance suite's own call site was exactly that shape, and `--suite shiftwork` went
`FAIL 1558 cases, 201 failures` → `PASS 1558 cases, 0 failures` on the arity fix alone
(commit `efb4413`, whose message carries both lines). The fixed call site reads
`shiftwork.clockIn(target, call.unit_id ?? null, { now: clock.now })`, in
`tools/conformance/suites/shiftwork.mjs`.

**What a caller must do.** Put the id — or `null` — in the second slot:
`clockIn(path, null, { now })` for the old default-path call, `clockIn(path, 'U3')` to brief a
named ready unit. `clockOut` is untouched: the same seven parameters in the same order
(`runtime-ts/src/shiftwork.ts:730–738`). `runtime-ts/package.json:3` reads `0.35.3` in the tree;
this section is the declaration for whichever published version first carries job60.

**This is not a divergence, and job60 added no row above.** `runtime-py` grew the same parameter
in the same job — `def clock_in(checkpoint: str, unit_id: str | None = None)` at
`runtime-py/src/bantamkit/shiftwork.py:289` (commit `3023f89`) — but there it was **appended**
to `def clock_in(checkpoint: str)` and displaced nothing, because the Python function has no
trailing options argument: `ClockOptions` is a Node-only seam carrying `now`
(`runtime-ts/src/shiftwork.ts:237–240`). Same behaviour, same `unit_id` tool input, same refusal
sentences on both sides. The Node call surface broke only because it is the one with a parameter
standing behind `unitId`.
