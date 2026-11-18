# Changelog

All notable changes to bantamkit are recorded here. The format follows
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/). Releases before 1.0.0 are described in their
[GitHub release notes](https://github.com/Ink01101011/bantamkit/releases); this file starts with
the changes 1.0.0 makes for Python users.

## [Unreleased] — 1.0.0

### Changed (Python)

Since 0.40.1, the last release, most of the Python package's core is generated from the same TypeScript the npm
package runs (`bantamkit/_generated/`, #314, #315, #316). The public Python API is unchanged.
The old hand-written Python skipped JavaScript semantics in a few places, so on the inputs below
the PyPI package now gives a different answer than the 0.40 releases gave. In every entry the new answer is
the one the npm package gives. In most entries that is the answer the npm package already gave;
in entry 10 the npm package's answer changed as well (both runtimes now write one new sentence),
and entry 13 is a ruled difference where the npm package answers otherwise. Each "before" answer was
measured on the released 0.40.0 source and each "after" answer on this tree, with the same
input. 0.40.1 changed only the host install (`hostinstall`) and the version number from 0.40.0
and gives the same "before" answers, so below "0.40" names both releases. The 1.0.0 Python migration note,
[docs/python-1.0.0-migration.md](docs/python-1.0.0-migration.md), maps each entry to the
conformance case that pins it.

Unless an entry names an interpreter, it was measured on CPython 3.12.13 and Node v26.13.0.

1. **Numbers in log files are read the way JavaScript reads them.** `LogSegment.read()` (the
   append-only logs under `.bantamkit/`) parses each line's JSON numbers
   as doubles. For a line `{"f":1.0}`, `{"z":-0}`, `{"b":18446744073709551616}`, 0.40
   returned `{'f': 1.0}`, `{'z': 0}`, `{'b': 18446744073709551616}`. Now it returns `{'f': 1}`,
   `{'z': -0.0}` and `{'b': 1.8446744073709552e+19}`. Node: `1`, `-0`, `18446744073709552000`.
2. **Archived-search scores past 2^53 are rounded as doubles.** A cold-index query whose
   term-frequency sum passes 2^53 (two rows of `9007199254740993` for one name) returned
   `18014398509481986` in 0.40. Now it returns `1.8014398509481984e+16`, which is Node's
   `18014398509481984`. The cold-index row check still accepts an integer past 2^53, and that
   integer is now rounded the way JavaScript rounds it.
3. **Price-table JSON numbers are doubles.** `decode_price_json('9007199254740993')` returned
   `9007199254740993` and now returns `9007199254740992`. `decode_price_json('3000000.0')`
   returned `3000000.0` and now returns `3000000`. Node gives the same two answers.
4. **Work-plan refusals spell numbers as JavaScript does.** `workplan.plan()` (and the
   `work_plan` tool) refuses a `touches` entry that is not a path, and the refusal quotes the
   value. For `1e+21`, 0.40 wrote `node a touches 1000000000000000000000, which is not a plain
   relative path`; now it writes `node a touches 1e+21, …`. `1e-7` was written `1e-07` and is now
   `1e-7`. `12345678901234567890` was quoted exactly and is now `12345678901234567000`. Node
   gives each new spelling.
5. **Work-plan priorities past 2^53 tie.** Two nodes with priority `9007199254740992` and
   `9007199254740993` were ordered `["b", "a"]`, because the larger integer outranked the other.
   As doubles the two priorities are equal, so the nodes now keep insertion order, `["a", "b"]`,
   as on Node.
6. **A work-plan node with no `id` is refused, not a crash.** The library call
   `workplan.plan([{"depends_on": []}])` raised `KeyError: 'id'`. Now it returns
   `{"result": "error", "reason": "nodes[0].id must be a string"}`, as on Node. The `work_plan`
   MCP tool keeps its existing `KeyError` answer (unchanged, pinned by `--suite workplan`).
7. **A price-table path that is a directory, or empty, is a `PriceTableError`.**
   `load_price_table(<a directory>)` raised `IsADirectoryError` and now raises
   `PriceTableError: price table is not valid JSON: <path>`. `load_price_table('')` raised
   `IsADirectoryError: [Errno 21] Is a directory: '.'` and now raises
   `PriceTableError: price table not found: ` (with nothing after the colon). Node raises the same two errors.
8. **`format_micros` outside its contract.** The function takes a non-negative whole number of
   micro-dollars, which is all a price produces. Three other inputs now give Node's answer:
   `format_micros(-1)` returned `-1.999999` and now returns `0.0000-1`; `format_micros(0.5)` raised
   `ValueError: Unknown format code 'd' for object of type 'float'` and now raises `RangeError: The
   number 0.5 cannot be converted to a BigInt because it is not an integer` (a `ValueError`
   subclass); `format_micros(10**30)` returned `1000000000000000000000000.000000` and now returns
   `1000000000000000019884624.838656`, because the integer is read as a double first. None of the
   new answers is more meaningful than the old one. They are listed only because they changed.
9. **An empty rotated log segment counts as skipped.** A log whose `<log>.1.gz` is an empty file
   read with `skipped` 0 and now reads with `skipped` 1. The rows read are the same. Node also
   gives 1.
10. **An unreadable cold-index file has one sentence.** A cold-index manifest that is not JSON
    (`{x`) raised `ColdIndexError: cold index manifest unreadable: Expecting property name
    enclosed in double quotes: line 1 column 2 (char 1)`. Now it raises
    `cold index manifest unreadable: the file is not JSON`. A segment or a shard reads
    `cold index segment <id> unreadable: …` or `cold index shard <NN> unreadable: …`, with the same
    ending. Node's sentence changed to match, so both runtimes now write it.
11. **`BANTAMKIT_RETENTION` and `BANTAMKIT_SKILL_AUDIT` are trimmed as JavaScript trims.** The
    value `off` followed by U+001C was read as off and is now read as on. The value `off`
    followed by U+FEFF was read as on and is now read as off. Node gives both new answers. Plain
    spellings (`off`, ` OFF `, `0`, `false`, `no`) are unchanged.
12. **A dotless or dotted *i* in a relative date no longer crashes the dream pass.**
    `absolutise("Ship it tonıght.", …)` (U+0131) raised `KeyError: 'tonıght'` out of
    `memory_dream`. Now the term is reported unresolved and the body is left as written. The
    same holds for `TONİGHT` (U+0130) and `yeſterday` (U+017F). Node gives the same answer.
13. **A memory config that crashed the reader is now refused.** A `config.yaml` beside the
    project store that holds an impossible date (`k: 2001-02-30`) raised `ValueError: day is out
    of range for month`. One nested 1,000 levels deep raised `RecursionError`. Both now raise
    `MemoryValidationError: invalid memory config <path>: day is out of range for month` and
    `… the document is nested too deeply to read`. `docs/porting.md` (*Three crashes ruled*) lists
    five more documents that crashed the same way and are refused the same way. **Node differs here, and the difference is
    ruled.** Node's config reader does not read these documents the way PyYAML does: it returns
    `[]` for the date and refuses the nesting with
    `a nested sequence is outside this reader` (`docs/porting.md`, *Where the two runtimes
    deliberately differ*).
14. **Fact files: Unicode line separators are kept, and control characters are read.** A quoted
    `description: "x<U+2028> y"` read as `x y`, because YAML 1.1 folds U+2028 as a line break. It
    now reads with the separator kept, and the store's `description` shows `x  y`. U+0085 and
    U+2029 behave the same way. A fact whose value holds a raw control character
    (`description: bell <U+0007> here`) was skipped as
    `malformed fact file f2.md: unacceptable character #x0007 …`. It is now read. Node gives both
    new answers. PyYAML still writes such a value, and the first rewrite adds two spaces, after
    which the value is stable (`docs/porting.md`, *The fact-file codec*).
15. **Command-line error wording is the same on every CPython (3.11, 3.13, 3.14).** On 3.11.15,
    3.13 and 3.14, an invalid choice was quoted with reprs:
    `argument --install: invalid choice: 'nope' (choose from 'claude', 'claude-desktop', 'copilot', 'cursor')`.
    Now, as on 3.12 and Node, it reads `(choose from claude, claude-desktop, copilot, cursor)`.
    This covers `bantamkit-mcp` and `python -m bantamkit.memory`. On 3.13 and 3.14 the memory
    CLI's wrapped usage line printed `{status,list,lint,compact,candidates,merge,archived,archive,restore} ...`
    and now prints `...`. bantamkit now ships CPython 3.12.13's argparse (`bantamkit/_argparse312.py`),
    so the help text and errors no longer depend on the interpreter.
16. **A checkpoint that is not JSON has 3.12's sentence on 3.13 and 3.14.** A shift-work
    checkpoint `{"version": 1,}` was refused on 3.13 and 3.14 with
    `checkpoint is not parseable as JSON: Illegal trailing comma before end of object: line 1 column 14 (char 13)`.
    Now every interpreter writes
    `… Expecting property name enclosed in double quotes: line 1 column 15 (char 14)`. That is
    the 3.12 sentence, which `--suite shiftwork` compares with Node's.
17. **Date errors have 3.12's sentence on 3.14.** On 3.14 the impossible date of entry 13 read
    `day 30 must be in range 1..28 for month 2 in year 2001` (and crashed, as on every
    interpreter). It now reads `day is out of range for month`, the sentence 3.12 gives. 3.14's
    other date sentences (`month must be in 1..12, not 13`, `year must be in 1..9999, not 0`)
    are pinned back to 3.12's the same way.

18. **A lock file is created `0o644`, not executable.** The `.lock` file `exclusive()` creates
    beside an index, a log or retention's state (umask 022) had mode `0o755` and now has `0o644`.
    Node also creates it `0o644`. The file is empty and removed when the lock is released; only a
    lock left by a killed process stays long enough to be seen.
19. **Stale temp files left by a killed writer are deleted.** Every storage writer writes
    `<file>.<pid>.tmp` and renames it over `<file>`. A process killed between the two left the temp
    forever. Now each writer deletes its own leftover temps once they are older than 10 s (the
    lock's stale window): the hot index on each write, the cold index on each `add` / `compact`,
    and retention at the start of each run, which reports each one in `deleted`. Only a regular
    file named `<a file this writer writes>.<digits>.tmp` is deleted; any other name, a directory
    and a fresh temp are kept. Before: a hot-index temp `<sha16>.json.31.tmp` dated 2023 was still
    there after the next write. Now it is gone, and `unrelated.json.32.tmp` beside it is kept.
    Node gives the same answer.
20. **A memory store reached through a dangling symlink gets a new index file.** The hot index is
    named by a hash of the store's real path. For a store path that is a symlink to a missing
    target, 0.40 followed the link (`os.path.realpath`) and named the index after the missing
    target; it now keeps the link as spelled, as Node's `realpath` does. For one such path
    0.40 wrote `893fccfc6afacc12.json` (its source named `missing-target`) and now writes
    `ee0575503420fafd.json` (named `dangle`), the file Node writes. The old file is not read
    again; the index is rebuilt once under the new name, from the same facts.
21. **A hand-edited hot-index file is read as Node reads it.** These files are written only by
    bantamkit; the inputs below are hand edits. A head whose `lens_total` holds `1.0` was rebuilt
    and is now read as `1` and trusted (`refresh` answers `fresh`, not `rebuilt`). A head whose
    `full_at` stamp is spelled with a lowercase `t` and `z` was trusted and is now unreadable, so
    the next refresh rewrites it (`…T…Z`). A postings shard whose run length is `1.0` made every
    query on that shard raise `ValueError: malformed postings`; it now reads as `1` and the query
    answers. Node gives each new answer.
22. **Retention drops an archived job whose recorded file is absolute.** Compaction keeps a job in
    the job cold index while `<root>/<file>` is a file, and now joins the two as Node's
    `path.join` does: an absolute `file` names a path under the root, not the absolute file. A doc
    whose `file` was an absolute path to an existing file (outside the root or inside it) was kept
    and is now dropped, so a later archived search no longer finds it. bantamkit records a
    relative path for every job it archives, so only a hand-built doc has an absolute one. Over
    docs `a` (absolute, outside), `b` (`real.json`), `c` (gone), `d` (`../root/real.json`), `f`
    (absolute, inside) and a later `e`, 0.40 kept `a b d e f` and now keeps `b d e`, as Node does.

Not listed: changes that never reached a release. Some answers broke inside the 1.0.0 branch and
were fixed before any release, for example the hot index's held-head `ino` and three
compiled-build faults. Also not listed are answers recorded in `docs/porting.md` that this note
did not re-run. The migration note says which ones those are.
