# The repo map

A ranked listing of a source tree's definitions: which files matter to the file you are
about to edit, and what each of them defines, truncated to a byte budget.

Roadmap row 10. Shipped 2026-09-07 by job45 — `runtime-py/src/bantamkit/repomap.py`,
`runtime-ts/src/repomap.ts`, and the `repo_map` MCP tool on both servers.

---

## It is a precision feature and it is not a token saving

This is the first thing to say about it because the row it came from asked for the
opposite.

Row 10's own build gate was *"build only after #4 shows discovery tokens dominate"*. #4 was
built, and it **refuted** the gate:

| | |
|---|---|
| discovery tokens | 4,266.6 k est |
| share of tool-result bytes | 33.8 % |
| share of **real prompt tokens** | **0.114 %** |
| share of the real bill that is `cache_read` | **97.8 %** |

A prompt is paid for overwhelmingly as cache reads, so making the discovery phase smaller
buys approximately nothing. The user ruled *"build it anyway, full spec"*, and it ships as
a **precision** feature: the right file found sooner, not fewer bytes spent.

Nothing in the module, its tests, its tool description or this page says otherwise, and
that is enforced rather than promised — every `repo_map` reply ends with the refutation
(`REPO_MAP_TAIL`), and a `repomap` conformance case pins that sentence as a typed literal
against **each** runtime separately, because a differential goes green the moment someone
softens it on both sides at once.

## The budget is UTF-8 BYTES

Row 10 said "1 K-token budget". Neither runtime can honour that unit honestly.

- The exported `tokens()` in `memory/store.py` is an ASCII word split returning a **set**.
  It is a similarity primitive. It is not a counter and it is not a model tokenizer.
- No tokenizer exists in either runtime, and **adding one is the dependency the pure-node
  `npx` ruling forbids**.

So the budget is stated, enforced and reported in **UTF-8 bytes of the listing**, and
`DEFAULT_BUDGET = 4000`.

**4000 is "1 K tokens" only at the char/4 convention** this repository already uses in
`tools/hooks/bantamkit-hook.mjs`. **That convention is an ESTIMATE and its error bar is
not measured**, here or anywhere in this repository — because measuring it would require
running a real tokenizer over the same text, which is the dependency that is refused.
Bytes are what is enforced; the token figure records where 4000 came from and nothing
else. No sentence anywhere converts back.

## What it does

```
repo_map(root, focus=[...], budget=4000)
```

1. **Walk.** Every file under `root`, relative, POSIX, code-point sorted. Directory
   symlinks are not followed; `SKIP_DIRS` (`.git`, `node_modules`, …) are not descended.
   The walk returns files it has **no** dialect for as well — the language filter is one
   stage later, which is what makes an unreadable file a *counted omission* instead of a
   silent skip.
2. **Scan.** Dispatch on **suffix**, not on magic bytes, and that is a deliberate departure
   from `docread`: a suffix is measurably a lie about a *container*, but `.py` and `.ts`
   name a **grammar** and there is no magic number for a grammar. Comments and docstrings
   are blanked first, one output line per input line, so a `line` a caller jumps to is a
   line of the original file.
3. **Graph.** An edge is a **name reference**, never an import. `A -> B` weighted by how
   many names `A` mentions that **only** `B` defines. Two filters decide which names may
   carry identity: a name defined in more than one file is dropped, and a name referenced
   by more than an eighth of the files is dropped.
4. **Rank.** Personalised PageRank, damping 0.20, 30 rounds, no early stop. `focus` is the
   personalisation vector; with no focus it is uniform and the answer is plain centrality.
5. **Render.** Greedy in rank order, within the byte budget, definitions inside a file
   ordered by kind then by how widely the name is referenced.
6. **Disclose.** Everything the map does not carry is a counted `Omission`.

## Nothing is dropped silently

There is no parser, so "unparsable" is not one thing. Every file the map does not carry
resolves into a **named** subject with a count:

| subject | when | also carries |
|---|---|---|
| `unknown-language` | no dialect for the suffix | bytes |
| `unreadable-bytes` | `OSError`, or not strict UTF-8 | bytes |
| `size-cap` | larger than `MAX_FILE_BYTES` (1 MiB) | bytes, `cap_bytes` |
| `no-definitions` | scanned clean, held nothing | — |
| `unreachable` | scored exactly 0.0 from the focus | — |
| `per-file-cap` | definitions past `MAX_DEFINITIONS_PER_FILE` (4) | `per_file` |
| `budget` | files the byte budget could not carry | `definitions`, `files_partial`, `budget_bytes`, `listing_bytes` |

**The `# omitted: …` footer is NOT charged against the budget.** A budget that can suppress
the disclosure of what it dropped is the defect the footer exists to close, and a footer
that only fits when there is nothing to say would do exactly that. `listing_bytes` is what
the budget governs; `len(text)` may exceed it by the footer.

## The constants, and what each one beat

Every number was chosen against a ground truth that is **not an input to the ranking**:
*with file F as the focus, where in the ranking do F's own resolved in-repo imports land?*
Imports are the yardstick precisely because they are not edges. Measured over this
repository's 235 tracked source files, 19 focal files, 83 (focus, import) pairs.

| constant | value | what it beat |
|---|---|---|
| `DAMPING` | 0.20 | 0.10 / 0.30 / 0.50 / 0.85 → recall@10 0.614 / 0.590 / 0.566 / 0.313. 0.85 is calibrated for global web authority; this is a local query |
| `ITERATIONS` | 30 | the vector reaches an exact fixed point at round 16; 30 is past it with no early stop, which is one fewer float comparison for the port to reproduce |
| `MIN_REFERENCE_LENGTH` | 3 | 4 and 5 measure better and are overfitting — they drop real API names (`run`, `key`, `page`, `Fact`) |
| unique definer | exactly 1 | 2 / 3 / 5 / 10 / any → 0.566 / 0.518 / 0.530 / 0.518 / 0.506 against 0.614 |
| `REFERENCE_DF_MAX_NUM/_DEN` | 1/8 | none / ½ / ¼ / ⅛ / 1⁄16 / 1⁄32 / 1⁄64 → 0.614 / 0.614 / 0.687 / **0.735** / 0.627 / 0.554 / 0.229. The only curve that TURNS |
| `MAX_DEFINITIONS_PER_FILE` | 4 | a file's identity, not its contents |

**The DF filter has a FLOOR at `REFERENCE_DF_MAX_DEN` files**, so on a tree of eight files
or fewer it cannot reject anything: a fraction of a tree smaller than the denominator is
less than one file, and without the floor a three-file project came back with an empty map.

Result at a 4000-byte budget: **median rank of a true import 4**, recall@1/@5/@10
0.169 / 0.506 / **0.735**, and **76 of 83 true imports inside the rendered map (0.916)**.
The pre-tuning baseline was recall@10 0.361 and median rank 32.

**What the yardstick cannot do**, stated so nobody quotes it further than it goes: it is
file-level, so it cannot arbitrate the ordering *within* a file's block; it **understates**
the map on this repository, because a Python import can never name `runtime-ts/src/memory/
store.ts` and the port of the file you are editing is one of the two most useful things
this map can surface; and it is one repository, so nothing here generalises.

## Determinism across the two runtimes

PageRank is floating-point iteration and both runtimes must produce the same ranking from
the same tree. IEEE-754 `+`, `*` and `/` are correctly rounded and identical in CPython and
V8, so bit-identity is achievable — but only if nothing in the loop is clever. Four traps
were probed rather than assumed:

- **`sum()` over floats is compensated in CPython and is not in JS.** Nothing here calls it;
  every accumulation is a written-out loop, and a test reads the function body to keep it so.
- **`float` → `str` disagrees in form** (`1.0`/`1`, `1e-07`/`1e-7`, `1e+16`/`1e16`). **No
  raw float is ever rendered.** `RepoMap.text` carries no score; `rank_units` is an integer.
- **`round()` is banker's in CPython and half-up in JS.** Never used. `rank_units` is
  `floor(score * 1e9)`, and `math.floor` / `Math.floor` agreed on every probed value.
- **`sorted()` on `str` is code-point order; JS's default `Array.sort` is UTF-16 code-UNIT
  order**, and the two disagree above the BMP. Every sort routes through one comparator
  (`_by_code_point` / `cmpCodepoint`).

The last of those is **the one rule no Python test can make non-vacuous**: CPython's `str`
comparison *is* code-point comparison, so no CPython fixture can tell the comparator from
the identity. It is pinned instead by a conformance case over a tree holding two files
whose names differ only above the BMP (`🐔widget.py` and `！widget.py`) and whose scores
tie to the last bit, so the comparator is the only thing that decides the order.

## The `repo_map` tool

Served thirteenth on both servers; `assets/tools/repo_map.json` is the one description both
read.

| argument | |
|---|---|
| `root` | required. The directory to map |
| `focus` | the files you are working on, relative to `root`, POSIX-separated. Excluded from the listing. A name that is not a scanned source is **ignored**, not refused |
| `budget` | UTF-8 bytes of listing; default 4000 |

Three refusals, all argument failures, both runtimes word for word:

```
root must not be empty; name the directory to map
budget must not be negative; got <n>
no such directory: <root>
<root> is a file, not a directory to map
```

**Those checks live in the handler, not in the module**, and that is deliberate:
`repo_map()` over a missing directory answers an **empty map** on both runtimes, which is
right for a library and wrong for a tool — a caller who typed the path wrong would be told
the tree holds no source.

The event log records the decision (`mapped` / `refused`) and the five counts. It never
records `root`, never a focus path and never a mapped path: those are the operator's, not
decisions this handler made.

## The gate

`node tools/conformance/run.mjs --suite repomap` — **195 cases** over five purpose-built
trees (ordinary, boundary, astral, single-file, document-frequency), comparing the walk,
the per-file scan, the whole edge map, every node's **IEEE-754 score bits**, every rendered
listing as bytes, every omission, and the tool's rendered reply.

Every float travels as its big-endian bit pattern in hex and every string as base64. A
differential that compared `String(x)` would be measuring the serialisers.

**The corpus is built, never this repository.** J45-10 measured three separate wrong answers
from mapping the checkout while writing into it: adding one test file produced 40 phantom
edge rows; adding one note moved `unknown-language` 1689 → 1690 and scored four *equivalent*
mutants as KILLED; editing a header shifted four `Definition.line` values.

**Five cases are not differential at all.** The constants, the astral tie-break, the
omission vocabulary, the tail sentence and the empty-listing sentence are compared to typed
literals on **each side separately**, because a rule written twice and asserted nowhere is
invisible to a comparison between the two — measured: reversing the by-path tie-break on
both runtimes at once leaves all 193 differential cases green and reddens only the astral
literal.

See [conformance.md](conformance.md).
